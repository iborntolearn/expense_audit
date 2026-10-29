"""Ask AI responder adapter (Build Brief 4 & 7: every model call behind a thin
adapter; provider via config, never hardcoded) - mirrors adapters/vision.py's
ABC + Simulated + Anthropic + AzureOpenAI shape.

`assistant/engine.py`'s deterministic intent matching only recognises a fixed
set of hardcoded phrasings and reuses almost none of dashboard/queries.py's
richer aggregations (user_analytics, consolidated_insights, per-OE/currency
spend, top rules, trend, reviewer outcomes...). The real responders below let
an LLM reason over the actual question, call those same read-only aggregation
functions as tools to ground its answer in real data, and reference prior
turns via `history` for genuine follow-up questions - while
`SimulatedAssistantResponder` keeps today's engine as the offline, zero-cost
default so nothing changes unless a provider is explicitly configured.

Both real responders fail open to the deterministic engine on any tool-loop
error (bad model output, network failure, exhausted round budget) - Ask AI
degrading to "less smart" beats surfacing a hard error on what is ultimately
a Q&A convenience feature over data the deterministic engine can already
answer at least partially.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Optional

from assistant.engine import Answer, answer as _deterministic_answer
from dashboard.queries import (
    compute_company_abi,
    compute_dashboard,
    compute_expense_reports,
    consolidated_insights,
    list_employees,
    user_analytics,
)

logger = logging.getLogger("assistant.responder")

_MAX_TOOL_ROUNDS = 4

_SYSTEM_PROMPT = (
    "You are Veriflow's expense-audit data analyst. Answer the user's question "
    "about their organisation's T&E expense audit data using ONLY the provided "
    "tools - never invent numbers. Call as many tools as needed to gather the "
    "facts, then ALWAYS finish by calling submit_answer exactly once with your "
    "final answer - never reply in plain prose instead of calling submit_answer. "
    "Keep `text` to 1-3 sentences. Populate `metric` for a single headline "
    "number, `chart` for a ranking/breakdown of up to ~15 rows, and `table` "
    "for a list of records - omit whichever doesn't naturally fit the "
    "question. If a conversation history is provided, resolve follow-ups "
    "(e.g. \"what about just DE?\") against it."
)

_QUERY_TOOL_SPECS: list[dict] = [
    {
        "name": "dashboard_summary",
        "description": (
            "Company-wide KPIs and breakdowns: automation/straight-through/"
            "exception rates, total and flagged spend, average risk score, "
            "review backlog, spend by category/OE/currency, top violated "
            "policy rules, exception reasons, risk-score histogram, daily "
            "submission trend, most recent decisions, and reviewer outcome "
            "counts."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "expense_reports",
        "description": (
            "Individual expense reports (one row per submission): status, "
            "risk band/score, violations, flags, and reason - optionally "
            "filtered by status, risk band, or employee."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["SUBMITTED", "APPROVED", "REJECTED"]},
                "risk_band": {"type": "string", "enum": ["LOW", "PENDING", "HIGH"]},
                "employee_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max rows, default 50, max 200"},
            },
            "required": [],
        },
    },
    {
        "name": "employee_analytics",
        "description": (
            "Deep-dive analytics for one employee: T&E spend, rejected/"
            "high-risk spend, ABI behavioural score (0-100, higher is "
            "cleaner), auto-approved count, spend by expense category, "
            "behavioural trend counts, and spend by geography (OE)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "Call list_employees first if unsure of the exact id",
                },
                "period_days": {
                    "type": "integer",
                    "description": "Restrict to the last N days relative to the latest "
                                    "submission in the data; omit for all time",
                },
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "behaviour_scores",
        "description": (
            "Behavioural integrity (ABI) score, 0-100 (higher is cleaner), "
            "for every employee, ranked lowest (most flagged) first."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "submission_insights",
        "description": (
            "Every distinct risk insight (policy violation, duplicate match, "
            "authenticity/tamper flag, subtotal mismatch, velocity, "
            "split-transaction, merchant sanctions/PEP, cumulative "
            "compliance, low-confidence extraction) that fired on one "
            "specific expense report."
        ),
        "parameters": {
            "type": "object",
            "properties": {"submission_id": {"type": "string"}},
            "required": ["submission_id"],
        },
    },
    {
        "name": "list_employees",
        "description": "Every distinct employee_id present in the (OE-scoped) audit data.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]

_SUBMIT_ANSWER_SPEC = {
    "name": "submit_answer",
    "description": (
        "Submit your final answer to the user's question. ALWAYS call this "
        "exactly once as your last step, never reply in plain prose instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "1-3 sentence plain-language answer"},
            "metric": {
                "type": "object",
                "description": "A single headline number, e.g. {label: 'Automation "
                                "rate', value: '68%'}. Omit if there's no one natural "
                                "headline number.",
                "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                "required": ["label", "value"],
            },
            "chart": {
                "type": "object",
                "description": "A horizontal bar chart. Omit unless the question is "
                                "naturally a ranking/breakdown.",
                "properties": {
                    "label": {"type": "string", "description": "Category/x-axis key "
                                                                 "name used in each `data` row, e.g. 'Employee'"},
                    "value": {"type": "string", "description": "Numeric/y-axis key name "
                                                                "used in each `data` row, e.g. 'Spend'"},
                    "data": {"type": "array", "items": {"type": "object"},
                             "description": "Up to ~15 rows, each with exactly the "
                                            "`label` and `value` keys set above"},
                },
                "required": ["label", "value", "data"],
            },
            "table": {
                "type": "array",
                "items": {"type": "object"},
                "description": "A row-per-record table, each object sharing the same "
                               "keys. Omit unless the question is naturally a list.",
            },
        },
        "required": ["text"],
    },
}


@dataclass
class _ToolContext:
    rows: dict
    subtotal_tol: float
    conf_cutoff: float
    auto_approve_cutoff: float
    auto_reject_cutoff: float


def _run_query_tool(name: str, args: dict, ctx: _ToolContext) -> dict:
    rows = ctx.rows
    try:
        if name == "dashboard_summary":
            return asdict(compute_dashboard(rows, subtotal_tol=ctx.subtotal_tol, conf_cutoff=ctx.conf_cutoff))
        if name == "expense_reports":
            reports = compute_expense_reports(
                rows, auto_approve_cutoff=ctx.auto_approve_cutoff,
                auto_reject_cutoff=ctx.auto_reject_cutoff,
                subtotal_tol=ctx.subtotal_tol, conf_cutoff=ctx.conf_cutoff,
            )
            if args.get("status"):
                reports = [r for r in reports if r["status"] == args["status"]]
            if args.get("risk_band"):
                reports = [r for r in reports if r["risk_band"] == args["risk_band"]]
            if args.get("employee_id"):
                reports = [r for r in reports if r["employee_id"] == args["employee_id"]]
            limit = min(int(args.get("limit") or 50), 200)
            return {"count": len(reports), "reports": reports[:limit]}
        if name == "employee_analytics":
            employee_id = args.get("employee_id") or ""
            if employee_id not in list_employees(rows):
                return {"error": f"no such employee_id {employee_id!r}. "
                                  "Call list_employees to see valid ids."}
            return user_analytics(
                rows, employee_id, subtotal_tol=ctx.subtotal_tol, conf_cutoff=ctx.conf_cutoff,
                auto_reject_cutoff=ctx.auto_reject_cutoff, period_days=args.get("period_days"),
            )
        if name == "behaviour_scores":
            abi = compute_company_abi(rows, subtotal_tol=ctx.subtotal_tol, conf_cutoff=ctx.conf_cutoff)
            return {"scores": [{"employee_id": e, "abi_score": s}
                                for e, s in sorted(abi.items(), key=lambda x: x[1])]}
        if name == "submission_insights":
            sid = args.get("submission_id") or ""
            reports = compute_expense_reports(
                rows, auto_approve_cutoff=ctx.auto_approve_cutoff,
                auto_reject_cutoff=ctx.auto_reject_cutoff,
                subtotal_tol=ctx.subtotal_tol, conf_cutoff=ctx.conf_cutoff,
            )
            report = next((r for r in reports if r["submission_id"] == sid), None)
            if report is None:
                return {"error": f"no such submission_id {sid!r}"}
            insights = consolidated_insights(sid, rows, subtotal_tol=ctx.subtotal_tol,
                                              conf_cutoff=ctx.conf_cutoff)
            return {"report": report, "insights": insights}
        if name == "list_employees":
            return {"employees": list_employees(rows)}
        return {"error": f"unknown tool {name!r}"}
    except Exception as exc:  # pragma: no cover - defensive, args are model-supplied
        logger.warning("assistant tool %s failed: %s", name, exc)
        return {"error": str(exc)}


def _answer_from_submit_args(args: dict) -> Answer:
    metric = None
    m = args.get("metric")
    if m and m.get("label") and m.get("value") is not None:
        metric = (str(m["label"]), str(m["value"]))
    return Answer(
        text=args.get("text") or "I couldn't compute an answer for that.",
        metric=metric,
        chart=args.get("chart"),
        table=args.get("table"),
        suggestions=[],
    )


class AssistantResponder(ABC):
    @abstractmethod
    def answer(
        self, question: str, rows: dict, *, subtotal_tol: float, conf_cutoff: float,
        auto_approve_cutoff: float, auto_reject_cutoff: float,
        history: Optional[list[dict]] = None,
    ) -> Answer:
        ...


class SimulatedAssistantResponder(AssistantResponder):
    """Today's deterministic intent-matching engine, unchanged - the offline,
    zero-cost default. `history` is accepted for interface parity but ignored:
    the deterministic engine has no notion of conversational context."""

    def answer(
        self, question: str, rows: dict, *, subtotal_tol: float, conf_cutoff: float,
        auto_approve_cutoff: float, auto_reject_cutoff: float,
        history: Optional[list[dict]] = None,
    ) -> Answer:
        return _deterministic_answer(
            question, rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff,
            auto_reject_cutoff=auto_reject_cutoff,
        )


class AnthropicAssistantResponder(AssistantResponder):
    """Real LLM reasoning via Claude's tool use."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise RuntimeError(
                "assistant.provider=anthropic requires ANTHROPIC_API_KEY. "
                "Use provider=simulated for the offline default."
            )
        import anthropic  # noqa: F401

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def answer(
        self, question: str, rows: dict, *, subtotal_tol: float, conf_cutoff: float,
        auto_approve_cutoff: float, auto_reject_cutoff: float,
        history: Optional[list[dict]] = None,
    ) -> Answer:  # pragma: no cover - requires live API
        ctx = _ToolContext(rows, subtotal_tol, conf_cutoff, auto_approve_cutoff, auto_reject_cutoff)
        tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                 for t in (*_QUERY_TOOL_SPECS, _SUBMIT_ANSWER_SPEC)]
        messages: list = [{"role": h["role"], "content": h["content"]} for h in (history or [])]
        messages.append({"role": "user", "content": question})

        try:
            for _ in range(_MAX_TOOL_ROUNDS):
                resp = self._client.messages.create(
                    model=self.model, max_tokens=1024, system=_SYSTEM_PROMPT,
                    tools=tools, messages=messages,
                )
                tool_uses = [b for b in resp.content if b.type == "tool_use"]
                submit = next((b for b in tool_uses if b.name == "submit_answer"), None)
                if submit:
                    return _answer_from_submit_args(submit.input)
                if not tool_uses:
                    text = "".join(b.text for b in resp.content if b.type == "text")
                    return Answer(text=text or "I couldn't compute an answer for that.")
                messages.append({"role": "assistant", "content": resp.content})
                results = [
                    {"type": "tool_result", "tool_use_id": b.id,
                     "content": json.dumps(_run_query_tool(b.name, b.input, ctx))}
                    for b in tool_uses
                ]
                messages.append({"role": "user", "content": results})
        except Exception as exc:
            logger.warning("Anthropic assistant responder failed, falling back to deterministic: %s", exc)
        return _deterministic_answer(
            question, rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff,
            auto_reject_cutoff=auto_reject_cutoff,
        )


class AzureOpenAIAssistantResponder(AssistantResponder):
    """Real LLM reasoning via Azure OpenAI (e.g. GPT-4.1) function calling."""

    def __init__(self, api_key: str, endpoint: str, deployment: str, api_version: str):
        if not api_key or not endpoint:
            raise RuntimeError(
                "assistant.provider=azure_openai requires AZURE_OPENAI_KEY and "
                "AZURE_OPENAI_ENDPOINT. Use provider=simulated for the offline default."
            )
        from openai import AzureOpenAI  # noqa: F401

        self.deployment = deployment
        self._client = AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=api_version)

    def answer(
        self, question: str, rows: dict, *, subtotal_tol: float, conf_cutoff: float,
        auto_approve_cutoff: float, auto_reject_cutoff: float,
        history: Optional[list[dict]] = None,
    ) -> Answer:  # pragma: no cover - requires live API
        ctx = _ToolContext(rows, subtotal_tol, conf_cutoff, auto_approve_cutoff, auto_reject_cutoff)
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                    "parameters": t["parameters"]}}
                 for t in (*_QUERY_TOOL_SPECS, _SUBMIT_ANSWER_SPEC)]
        messages: list = [{"role": "system", "content": _SYSTEM_PROMPT}]
        messages += [{"role": h["role"], "content": h["content"]} for h in (history or [])]
        messages.append({"role": "user", "content": question})

        try:
            for _ in range(_MAX_TOOL_ROUNDS):
                resp = self._client.chat.completions.create(
                    model=self.deployment, temperature=0, tools=tools, messages=messages,
                )
                msg = resp.choices[0].message
                calls = msg.tool_calls or []
                submit = next((c for c in calls if c.function.name == "submit_answer"), None)
                if submit:
                    return _answer_from_submit_args(json.loads(submit.function.arguments or "{}"))
                if not calls:
                    return Answer(text=msg.content or "I couldn't compute an answer for that.")
                messages.append(msg.model_dump(exclude_unset=True))
                for c in calls:
                    args = json.loads(c.function.arguments or "{}")
                    result = _run_query_tool(c.function.name, args, ctx)
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)})
        except Exception as exc:
            logger.warning("Azure OpenAI assistant responder failed, falling back to deterministic: %s", exc)
        return _deterministic_answer(
            question, rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff,
            auto_reject_cutoff=auto_reject_cutoff,
        )
