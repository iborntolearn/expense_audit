"""Natural-language "Ask" engine over the audit data.

Deterministic intent matching (no LLM, no API key, no cost) that maps a plain
question to a computed answer: a headline metric, an optional bar chart, and an
optional table. Reliable and offline - the right default for simulation mode. A
future LLM router can sit in front of this to widen phrasing coverage without
changing the answer computations.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from dashboard.queries import (
    _f,
    _truthy,
    compute_company_abi,
)


@dataclass
class Answer:
    text: str
    metric: Optional[tuple[str, str]] = None       # (label, value)
    chart: Optional[dict] = None                    # {"label": str, "value": str, "data": [...]}
    table: Optional[list[dict]] = None
    suggestions: list[str] = field(default_factory=list)


EXAMPLES = [
    "Show me all employee unauthorized spend",
    "Unauthorized spend by category",
    "How many duplicates were found?",
    "What is the automation rate?",
    "Top spenders",
    "How many reports need manual review?",
    "Show high risk reports",
    "Best and worst behaviour scores",
]


def _context(rows: dict, *, subtotal_tol: float, conf_cutoff: float):
    subs = {s["submission_id"]: s for s in rows["submissions"]}
    risk = {r["submission_id"]: r for r in rows["risk_decisions"]}
    ver = {v["submission_id"]: v for v in rows["verification"]}
    fail_counts = Counter(
        p["submission_id"] for p in rows["policy_evaluations"] if not _truthy(p.get("passed"))
    )
    total_by_sub: dict = defaultdict(float)
    for l in rows["report_lines"]:
        total_by_sub[l["submission_id"]] += _f(l.get("entered_amount"))
    return subs, risk, ver, fail_counts, total_by_sub


def _cur(rows) -> str:
    curs = {s.get("currency") for s in rows["submissions"] if s.get("currency")}
    return next(iter(curs)) if len(curs) == 1 else ""


# --------------------------------------------------------------------------- #
def answer(question: str, rows: dict, *, subtotal_tol: float, conf_cutoff: float,
           auto_reject_cutoff: float) -> Answer:
    ql = question.lower().strip()
    subs, risk, ver, fail_counts, total_by_sub = _context(
        rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff)
    cur = _cur(rows)

    def money(v: float) -> str:
        return f"{v:,.2f} {cur}".strip()

    unauth_sids = set(fail_counts)  # submissions with >=1 policy violation

    # --- unauthorized / policy-violation spend ---
    if any(w in ql for w in ("unauthorized", "unauthorised", "violation", "policy", "out of range")):
        by_emp: dict = defaultdict(float)
        by_cat_spend: dict = defaultdict(float)
        by_cat_count: dict = defaultdict(int)
        for l in rows["report_lines"]:
            sid = l["submission_id"]
            if sid not in unauth_sids:
                continue
            emp = subs.get(sid, {}).get("employee_id", "?")
            by_emp[emp] += _f(l.get("entered_amount"))
            by_cat_spend[l.get("category") or "uncategorised"] += _f(l.get("entered_amount"))
            by_cat_count[l.get("category") or "uncategorised"] += 1
        total = sum(by_emp.values())
        if "categor" in ql:
            table = [{"Unauthorized category": c,
                      "Count of expense lines": by_cat_count[c],
                      "Sum of line items": round(by_cat_spend[c], 2)}
                     for c in sorted(by_cat_spend, key=by_cat_spend.get, reverse=True)]
            return Answer(
                text=f"Unauthorized spend by category across {len(unauth_sids)} flagged reports.",
                metric=("Total unauthorized spend", money(total)), table=table)
        chart = {"label": "Employee", "value": "Unauthorized spend",
                 "data": [{"Employee": e, "Unauthorized spend": round(v, 2)}
                          for e, v in sorted(by_emp.items(), key=lambda x: x[1], reverse=True)[:15]]}
        table = [{"Unauthorized category": c,
                  "Count of expense lines": by_cat_count[c],
                  "Sum of line items": round(by_cat_spend[c], 2)}
                 for c in sorted(by_cat_spend, key=by_cat_spend.get, reverse=True)]
        return Answer(
            text=f"{len(unauth_sids)} reports contain unauthorized (policy-violating) spend.",
            metric=("Total unauthorized spend", money(total)), chart=chart, table=table)

    # --- duplicates ---
    if "duplicate" in ql:
        dups = [sid for sid, v in ver.items() if v.get("duplicate_match_ids")]
        table = [{"Report": sid, "Duplicate of": ", ".join(ver[sid]["duplicate_match_ids"]),
                  "Employee": subs.get(sid, {}).get("employee_id", "?")}
                 for sid in dups[:50]]
        return Answer(text=f"Found {len(dups)} reports flagged as duplicates.",
                      metric=("Duplicate reports", str(len(dups))), table=table)

    # --- high risk ---
    if "high risk" in ql or "risky" in ql or "high-risk" in ql:
        hi = [(sid, r) for sid, r in risk.items() if _f(r.get("risk_score")) >= auto_reject_cutoff]
        hi.sort(key=lambda x: _f(x[1].get("risk_score")), reverse=True)
        table = [{"Report": sid, "Risk score": round(_f(r.get("risk_score")), 2),
                  "Employee": subs.get(sid, {}).get("employee_id", "?"),
                  "Amount": round(total_by_sub.get(sid, 0), 2)} for sid, r in hi[:50]]
        return Answer(text=f"{len(hi)} high-risk reports (score >= {auto_reject_cutoff}).",
                      metric=("High-risk reports", str(len(hi))), table=table)

    # --- automation ---
    if "automation" in ql or "auto" in ql or "straight" in ql:
        total = len(risk)
        auto = sum(1 for r in risk.values()
                   if r.get("routing_decision") in ("auto_approve", "auto_reject"))
        rate = (auto / total * 100) if total else 0
        return Answer(text=f"{auto} of {total} reports were decided automatically.",
                      metric=("Automation rate", f"{rate:.0f}%"))

    # --- manual review / queue ---
    if any(w in ql for w in ("manual", "review", "pending", "queue", "exception")):
        reviewed = {ra["submission_id"] for ra in rows["reviewer_actions"]}
        pending = [sid for sid, r in risk.items()
                   if r.get("routing_decision") == "human_review" and sid not in reviewed]
        return Answer(text=f"{len(pending)} reports are awaiting manual review.",
                      metric=("Review backlog", str(len(pending))))

    # --- behaviour scores ---
    if "abi" in ql or "behav" in ql or "score" in ql:
        abi = compute_company_abi(rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff)
        ranked = sorted(abi.items(), key=lambda x: x[1])
        table = [{"Employee": e, "ABI score": s} for e, s in ranked]
        return Answer(text="Behavioural integrity scores (0-100, higher is cleaner). "
                           "Lowest first.",
                      table=table,
                      chart={"label": "Employee", "value": "ABI score",
                             "data": [{"Employee": e, "ABI score": s} for e, s in ranked[:15]]})

    # --- spend (by employee / category / total) ---
    if "spend" in ql or "spent" in ql or "total" in ql:
        if "categor" in ql:
            by_cat: dict = defaultdict(float)
            for l in rows["report_lines"]:
                by_cat[l.get("category") or "uncategorised"] += _f(l.get("entered_amount"))
            data = [{"Category": c, "Spend": round(v, 2)}
                    for c, v in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)]
            return Answer(text="Total spend by category.",
                          metric=("Total spend", money(sum(v['Spend'] for v in data))),
                          chart={"label": "Category", "value": "Spend", "data": data})
        # by employee / top spenders / total
        by_emp: dict = defaultdict(float)
        for sid, s in subs.items():
            by_emp[s.get("employee_id", "?")] += total_by_sub.get(sid, 0.0)
        ranked = sorted(by_emp.items(), key=lambda x: x[1], reverse=True)
        data = [{"Employee": e, "Spend": round(v, 2)} for e, v in ranked[:15]]
        return Answer(text="Total spend by employee (top 15).",
                      metric=("Total spend", money(sum(by_emp.values()))),
                      chart={"label": "Employee", "value": "Spend", "data": data})

    # --- fallback ---
    return Answer(
        text="I can answer questions about unauthorized spend, duplicates, high-risk reports, "
             "automation, review backlog, spend, and behaviour scores. Try one of these:",
        suggestions=EXAMPLES,
    )
