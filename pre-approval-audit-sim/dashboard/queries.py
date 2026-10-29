"""Business-dashboard aggregation.

Pure-Python aggregation over `AuditStore.analytics_rows()` so it works identically
on both storage backends (no SQL dialect concerns). For simulation dataset sizes
(hundreds to low thousands of rows) in-memory aggregation is more than fast
enough; a production deployment would push these to SQL views.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field


def _f(x) -> float:
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _truthy(x) -> bool:
    return bool(x) and x not in (0, "0")


def submission_ids_for_oe(rows: dict[str, list[dict]], oe_code: str | None) -> set[str] | None:
    """Submission ids belonging to one OE, or None if `oe_code` is None (no
    scoping - the caller is a global admin viewing every OE)."""
    if oe_code is None:
        return None
    return {s["submission_id"] for s in rows.get("submissions", []) if s.get("oe_code") == oe_code}


def filter_rows_by_oe(rows: dict[str, list[dict]], oe_code: str | None) -> dict[str, list[dict]]:
    """Restrict every table in `rows` (as returned by AuditStore.analytics_rows())
    to one OE's submissions. Every table besides `submissions` carries a
    `submission_id` FK, so filtering `submissions` first and keeping only rows
    whose submission_id is in that set scopes the whole dict generically -
    none of the aggregation functions below need their own oe_code plumbing.
    `oe_code=None` returns `rows` unchanged (global/all-OE view)."""
    allowed = submission_ids_for_oe(rows, oe_code)
    if allowed is None:
        return rows
    return {
        table: (
            [r for r in table_rows if r.get("oe_code") == oe_code] if table == "submissions"
            else [r for r in table_rows if r.get("submission_id") in allowed]
        )
        for table, table_rows in rows.items()
    }


def filter_cases_by_oe(
    cases: list[dict], rows: dict[str, list[dict]], oe_code: str | None,
) -> list[dict]:
    """Same idea as filter_rows_by_oe but for AuditStore.list_case_statuses()
    rows, which are fetched separately from analytics_rows()."""
    allowed = submission_ids_for_oe(rows, oe_code)
    if allowed is None:
        return cases
    return [c for c in cases if c.get("submission_id") in allowed]


@dataclass
class Dashboard:
    kpis: dict = field(default_factory=dict)
    routing: dict = field(default_factory=dict)
    spend_by_category: dict = field(default_factory=dict)
    spend_by_oe: dict = field(default_factory=dict)
    spend_by_currency: dict = field(default_factory=dict)
    top_rules: list = field(default_factory=list)
    exception_reasons: dict = field(default_factory=dict)
    risk_histogram: dict = field(default_factory=dict)
    trend: list = field(default_factory=list)
    recent_decisions: list = field(default_factory=list)
    reviewer_outcomes: dict = field(default_factory=dict)


def _reason_for(sid, *, fail_subs, ver_by_sub, lowconf_subs, subtotal_tol) -> str:
    """Highest-priority human-readable risk reason for a submission."""
    v = ver_by_sub.get(sid, {})
    if sid in fail_subs:
        return "Cost out of range"
    if v.get("authenticity_flags"):
        return "Receipt verification"
    if v.get("duplicate_match_ids"):
        return "Duplicate"
    if _f(v.get("subtotal_variance_pct")) > subtotal_tol:
        return "Amount mismatch"
    if sid in lowconf_subs:
        return "Low confidence"
    return ""


def consolidated_insights(
    sid: str, rows: dict[str, list[dict]], *, subtotal_tol: float, conf_cutoff: float,
    violations: list[str] | None = None,
) -> list[dict]:
    """Every DISTINCT insight type that fired on this one submission, as a
    single merged list (BR-TE-AU-20) - when a transaction trips several
    independent checks (e.g. a duplicate match AND a merchant watchlist hit),
    this is the one place a reviewer sees the union of evidence, instead of
    having to piece it together across separate tabs/cases. The submission's
    existing single approve/reject action already resolves all of them at
    once - this just makes that consolidation visible."""
    ver_by_sub = {v["submission_id"]: v for v in rows["verification"]}
    v = ver_by_sub.get(sid, {})
    if violations is None:
        violations = [
            p["rule_id"] for p in rows["policy_evaluations"]
            if p["submission_id"] == sid and not _truthy(p.get("passed"))
        ]
    lowconf = any(
        e["submission_id"] == sid and (e.get("amount") is None or _f(e.get("confidence")) < conf_cutoff)
        for e in rows["extracted_line_items"]
    )

    insights = []
    if violations:
        insights.append({"type": "policy_violation", "label": "Policy violation",
                         "detail": ", ".join(violations)})
    if v.get("duplicate_match_ids"):
        details = v.get("duplicate_match_details") or []
        structured = any(d.get("match_type") == "invoice_number" for d in details)
        insights.append({
            "type": "duplicate",
            "label": "Duplicate match (invoice number)" if structured else "Duplicate match",
            "detail": ", ".join(v["duplicate_match_ids"]),
        })
    if v.get("authenticity_flags"):
        insights.append({"type": "authenticity", "label": "Authenticity / tamper",
                         "detail": ", ".join(v["authenticity_flags"])})
    if _f(v.get("subtotal_variance_pct")) > subtotal_tol:
        insights.append({"type": "subtotal_variance", "label": "Subtotal mismatch",
                         "detail": f"{v.get('subtotal_variance_pct')}% (tolerance {subtotal_tol}%)"})
    if v.get("velocity_flags"):
        insights.append({"type": "velocity", "label": "Velocity",
                         "detail": ", ".join(v["velocity_flags"])})
    if v.get("split_transaction_flags"):
        insights.append({"type": "split_transaction", "label": "Split-transaction",
                         "detail": ", ".join(v["split_transaction_flags"])})
    if v.get("merchant_flags"):
        insights.append({"type": "merchant_blocklist", "label": "Merchant sanctions/PEP",
                         "detail": ", ".join(v["merchant_flags"])})
    if v.get("compliance_flags"):
        insights.append({"type": "compliance_cumulative", "label": "Cumulative compliance (FCPA)",
                         "detail": ", ".join(v["compliance_flags"])})
    if v.get("peer_outlier_flags"):
        insights.append({"type": "peer_outlier", "label": "Unusual vs. peers",
                         "detail": ", ".join(v["peer_outlier_flags"])})
    if v.get("merchant_network_flags"):
        insights.append({"type": "merchant_network", "label": "Merchant network signal",
                         "detail": ", ".join(v["merchant_network_flags"])})
    if lowconf:
        insights.append({"type": "low_confidence", "label": "Low-confidence extraction", "detail": ""})
    return insights


def compute_expense_reports(
    rows: dict[str, list[dict]],
    *,
    auto_approve_cutoff: float,
    auto_reject_cutoff: float,
    subtotal_tol: float,
    conf_cutoff: float,
) -> list[dict]:
    """AppZen-style risk-based audit rows, one per submission."""
    submissions = {s["submission_id"]: s for s in rows["submissions"]}
    risk = {r["submission_id"]: r for r in rows["risk_decisions"]}
    reviewer = {ra["submission_id"]: ra for ra in rows["reviewer_actions"]}
    ver_by_sub = {v["submission_id"]: v for v in rows["verification"]}

    total_by_sub: dict = defaultdict(float)
    cur_by_sub: dict = {}
    for l in rows["report_lines"]:
        total_by_sub[l["submission_id"]] += _f(l.get("entered_amount"))
        cur_by_sub[l["submission_id"]] = l.get("currency") or ""

    fail_counts: dict = Counter(
        p["submission_id"] for p in rows["policy_evaluations"] if not _truthy(p.get("passed"))
    )
    fail_subs = set(fail_counts)
    lowconf_subs = {
        e["submission_id"] for e in rows["extracted_line_items"]
        if e.get("amount") is None or _f(e.get("confidence")) < conf_cutoff
    }
    violations_by_sub: dict = defaultdict(list)
    for p in rows["policy_evaluations"]:
        if not _truthy(p.get("passed")):
            violations_by_sub[p["submission_id"]].append(p["rule_id"])

    def band(score: float) -> str:
        if score >= auto_reject_cutoff:
            return "HIGH"
        if score <= auto_approve_cutoff:
            return "LOW"
        return "PENDING"

    def status(sid: str, routing: str) -> str:
        ra = reviewer.get(sid)
        if ra:
            return ra["final_decision"].upper()
        return {"auto_approve": "APPROVED", "auto_reject": "REJECTED",
                "human_review": "SUBMITTED"}.get(routing, "SUBMITTED")

    reports = []
    for sid, r in risk.items():
        sub = submissions.get(sid, {})
        score = _f(r.get("risk_score"))
        routing = r.get("routing_decision") or "human_review"
        flags = len(ver_by_sub.get(sid, {}).get("authenticity_flags", []) or []) + len(
            ver_by_sub.get(sid, {}).get("duplicate_match_ids", []) or []
        )
        insight_count = len(consolidated_insights(
            sid, rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff,
            violations=violations_by_sub.get(sid, []),
        ))
        reports.append({
            "submission_id": sid,
            "employee_id": sub.get("employee_id", ""),
            "submitted_at": (sub.get("submitted_at") or "")[:10],
            "total": round(total_by_sub.get(sid, 0.0), 2),
            "currency": cur_by_sub.get(sid, ""),
            "risk_score": round(score, 3),
            "risk_band": band(score),
            "risk_reason": _reason_for(sid, fail_subs=fail_subs, ver_by_sub=ver_by_sub,
                                       lowconf_subs=lowconf_subs, subtotal_tol=subtotal_tol),
            "approver": (reviewer.get(sid) or {}).get("reviewer_id") or "-",
            "violations": fail_counts.get(sid, 0),
            "flags": flags,
            "insight_count": insight_count,
            "status": status(sid, routing),
            "routing_decision": routing,
        })
    reports.sort(key=lambda x: x["submitted_at"], reverse=True)
    return reports


def list_employees(rows: dict[str, list[dict]]) -> list[str]:
    return sorted({s["employee_id"] for s in rows["submissions"] if s.get("employee_id")})


def _submission_signals(rows, *, subtotal_tol, conf_cutoff) -> dict:
    fail_counts = Counter(
        p["submission_id"] for p in rows["policy_evaluations"] if not _truthy(p.get("passed"))
    )
    ver = {v["submission_id"]: v for v in rows["verification"]}
    lowconf = {
        e["submission_id"] for e in rows["extracted_line_items"]
        if e.get("amount") is None or _f(e.get("confidence")) < conf_cutoff
    }
    sigs: dict = {}
    for r in rows["risk_decisions"]:
        sid = r["submission_id"]
        v = ver.get(sid, {})
        sigs[sid] = {
            "violations": fail_counts.get(sid, 0),
            "duplicate": bool(v.get("duplicate_match_ids")),
            "authenticity": bool(v.get("authenticity_flags")),
            "subtotal": _f(v.get("subtotal_variance_pct")) > subtotal_tol,
            "lowconf": sid in lowconf,
        }
    return sigs


def _abi(flag_events: int, n_reports: int) -> int:
    """Behavioral integrity score 0-100 (higher = cleaner). 0 flags/report -> 100."""
    if n_reports == 0:
        return 100
    return int(round(max(0.0, min(100.0, 100.0 - (flag_events / n_reports) * 25.0))))


def _period_cutoff(submissions: dict[str, dict], period_days: int | None) -> str | None:
    """ISO date cutoff (inclusive), relative to the latest submitted_at in the
    dataset - not "today", since synthetic runs are dated in the past. None
    disables filtering (all time). Shared by user_analytics() and
    compute_company_abi() so a period selection means the same window in both
    the individual score and the company-wide comparison it's plotted against."""
    if not period_days:
        return None
    all_dates = [(s.get("submitted_at") or "")[:10] for s in submissions.values()]
    all_dates = [d for d in all_dates if d]
    if not all_dates:
        return None
    from datetime import date, timedelta

    latest = date.fromisoformat(max(all_dates))
    return (latest - timedelta(days=period_days)).isoformat()


def compute_company_abi(
    rows, *, subtotal_tol, conf_cutoff, period_days: int | None = None
) -> dict[str, int]:
    sigs = _submission_signals(rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff)
    submissions = {s["submission_id"]: s for s in rows["submissions"]}
    cutoff = _period_cutoff(submissions, period_days)

    def in_period(sid: str) -> bool:
        if not cutoff:
            return True
        return (submissions.get(sid, {}).get("submitted_at") or "")[:10] >= cutoff

    emp_of = {sid: s.get("employee_id") for sid, s in submissions.items()}
    per_emp_flags: dict = defaultdict(int)
    per_emp_reports: dict = defaultdict(int)
    for sid, s in sigs.items():
        if not in_period(sid):
            continue
        emp = emp_of.get(sid)
        if not emp:
            continue
        per_emp_reports[emp] += 1
        per_emp_flags[emp] += (
            s["violations"] + int(s["duplicate"]) + int(s["authenticity"])
            + int(s["subtotal"]) + int(s["lowconf"])
        )
    return {emp: _abi(per_emp_flags[emp], per_emp_reports[emp]) for emp in per_emp_reports}


def user_analytics(
    rows, employee_id, *, subtotal_tol, conf_cutoff, auto_reject_cutoff, period_days=None
) -> dict:
    submissions = {s["submission_id"]: s for s in rows["submissions"]}
    risk = {r["submission_id"]: r for r in rows["risk_decisions"]}
    reviewer = {ra["submission_id"]: ra for ra in rows["reviewer_actions"]}
    sigs = _submission_signals(rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff)

    # period cutoff relative to the latest submission in the data - same helper
    # compute_company_abi() uses, so the individual score and the company-wide
    # distribution it's plotted against always share the same window.
    cutoff = _period_cutoff(submissions, period_days)

    def in_period(sid) -> bool:
        if not cutoff:
            return True
        return (submissions[sid].get("submitted_at") or "")[:10] >= cutoff

    my_subs = [
        sid for sid, s in submissions.items()
        if s.get("employee_id") == employee_id and in_period(sid)
    ]

    total_by_sub: dict = defaultdict(float)
    lines_by_cat: dict = defaultdict(lambda: {"spend": 0.0, "lines": 0})
    for l in rows["report_lines"]:
        if l["submission_id"] in submissions and submissions[l["submission_id"]].get(
            "employee_id"
        ) == employee_id and in_period(l["submission_id"]):
            amt = _f(l.get("entered_amount"))
            total_by_sub[l["submission_id"]] += amt
            c = lines_by_cat[l.get("category") or "uncategorised"]
            c["spend"] += amt
            c["lines"] += 1

    te_spend = sum(total_by_sub.values())
    rejected_high = 0.0
    auto_approved = 0
    geo: dict = defaultdict(float)
    high_risk_by_cat: dict = defaultdict(float)
    trends = Counter()

    for sid in my_subs:
        r = risk.get(sid, {})
        score = _f(r.get("risk_score"))
        routing = r.get("routing_decision")
        ra = reviewer.get(sid)
        final = ra["final_decision"] if ra else None
        is_rejected = final == "rejected" or routing == "auto_reject"
        if routing == "auto_approve" and not final:
            auto_approved += 1
        if is_rejected or score >= auto_reject_cutoff:
            rejected_high += total_by_sub.get(sid, 0.0)
        geo[submissions[sid].get("oe_code") or "?"] += total_by_sub.get(sid, 0.0)

        s = sigs.get(sid, {})
        if s.get("violations"):
            trends["Cost out of range"] += s["violations"]
        if s.get("authenticity"):
            trends["Receipt verification"] += 1
        if s.get("duplicate"):
            trends["Duplicate within report"] += 1
        if s.get("subtotal"):
            trends["Amount mismatch"] += 1
        if s.get("lowconf"):
            trends["Low confidence"] += 1

    # high-risk spend by category (categories on high-risk submissions)
    high_sids = {
        sid for sid in my_subs
        if _f(risk.get(sid, {}).get("risk_score")) >= auto_reject_cutoff
        or (reviewer.get(sid, {}) or {}).get("final_decision") == "rejected"
        or risk.get(sid, {}).get("routing_decision") in ("auto_reject", "human_review")
    }
    for l in rows["report_lines"]:
        if l["submission_id"] in high_sids:
            high_risk_by_cat[l.get("category") or "uncategorised"] += _f(l.get("entered_amount"))

    company = compute_company_abi(
        rows, subtotal_tol=subtotal_tol, conf_cutoff=conf_cutoff, period_days=period_days
    )
    my_abi = company.get(employee_id, 100)

    return {
        "employee_id": employee_id,
        "kpis": {
            "te_spend": round(te_spend, 2),
            "rejected_high_risk_spend": round(rejected_high, 2),
            "abi_score": my_abi,
            "auto_approved": auto_approved,
            "total_reports": len(my_subs),
        },
        "spend_by_type": {k: {"spend": round(v["spend"], 2), "lines": v["lines"]}
                          for k, v in lines_by_cat.items()},
        "high_risk_spend_by_type": {k: round(v, 2) for k, v in high_risk_by_cat.items()},
        "behavioral_trends": [{"trend": t, "value": n} for t, n in trends.most_common()],
        "spend_by_geo": {k: round(v, 2) for k, v in geo.items()},
        "company_abi": sorted(company.values()),
        "my_abi": my_abi,
    }


def compute_dashboard(
    rows: dict[str, list[dict]], *, subtotal_tol: float, conf_cutoff: float
) -> Dashboard:
    submissions = rows["submissions"]
    risk = rows["risk_decisions"]
    report_lines = rows["report_lines"]
    policy = rows["policy_evaluations"]
    verification = rows["verification"]
    reviewer = rows["reviewer_actions"]
    extracted = rows["extracted_line_items"]

    sub_by_id = {s["submission_id"]: s for s in submissions}
    oe_by_sub = {s["submission_id"]: s.get("oe_code") for s in submissions}
    routing_by_sub = {r["submission_id"]: r.get("routing_decision") for r in risk}
    total = len(risk)

    routing = Counter(r.get("routing_decision") for r in risk)
    auto = routing.get("auto_approve", 0) + routing.get("auto_reject", 0)

    # --- spend ---
    total_spend = sum(_f(l.get("entered_amount")) for l in report_lines)
    flagged_spend = sum(
        _f(l.get("entered_amount"))
        for l in report_lines
        if routing_by_sub.get(l["submission_id"]) in ("human_review", "auto_reject")
    )
    spend_cat: dict = defaultdict(float)
    spend_oe: dict = defaultdict(float)
    spend_cur: dict = defaultdict(float)
    for l in report_lines:
        amt = _f(l.get("entered_amount"))
        spend_cat[l.get("category") or "uncategorised"] += amt
        spend_oe[oe_by_sub.get(l["submission_id"]) or "?"] += amt
        spend_cur[l.get("currency") or "?"] += amt

    # --- KPIs ---
    reviewed_subs = {ra["submission_id"] for ra in reviewer}
    backlog = sum(
        1 for r in risk
        if r.get("routing_decision") == "human_review" and r["submission_id"] not in reviewed_subs
    )
    avg_risk = (sum(_f(r.get("risk_score")) for r in risk) / total) if total else 0.0

    kpis = {
        "total_submissions": total,
        "automation_rate": (auto / total) if total else 0.0,
        "straight_through_rate": (routing.get("auto_approve", 0) / total) if total else 0.0,
        "exception_rate": (routing.get("human_review", 0) / total) if total else 0.0,
        "total_spend": round(total_spend, 2),
        "flagged_spend": round(flagged_spend, 2),
        "avg_risk_score": round(avg_risk, 3),
        "review_backlog": backlog,
    }

    # --- top violated rules ---
    rule_fail = Counter(p["rule_id"] for p in policy if not _truthy(p.get("passed")))
    top_rules = [{"rule_id": k, "violations": v} for k, v in rule_fail.most_common(10)]

    # --- exception reasons (per human_review submission; a sub may hit several) ---
    human_subs = {r["submission_id"] for r in risk if r.get("routing_decision") == "human_review"}
    fail_subs = {p["submission_id"] for p in policy if not _truthy(p.get("passed"))}
    ver_by_sub = {v["submission_id"]: v for v in verification}
    lowconf_subs = {
        e["submission_id"] for e in extracted
        if e.get("amount") is None or _f(e.get("confidence")) < conf_cutoff
    }
    reasons: dict = Counter()
    for sid in human_subs:
        v = ver_by_sub.get(sid, {})
        if sid in fail_subs:
            reasons["policy_violation"] += 1
        if v.get("duplicate_match_ids"):
            reasons["duplicate"] += 1
        if v.get("authenticity_flags"):
            reasons["authenticity"] += 1
        if _f(v.get("subtotal_variance_pct")) > subtotal_tol:
            reasons["subtotal_variance"] += 1
        if sid in lowconf_subs:
            reasons["low_confidence"] += 1

    # --- risk histogram (0.0-1.0 in 0.1 bins) ---
    hist: dict = {f"{i/10:.1f}-{(i+1)/10:.1f}": 0 for i in range(10)}
    for r in risk:
        score = min(0.999, max(0.0, _f(r.get("risk_score"))))
        hist[f"{int(score*10)/10:.1f}-{(int(score*10)+1)/10:.1f}"] += 1

    # --- trend by day ---
    by_day_total: dict = defaultdict(int)
    by_day_auto: dict = defaultdict(int)
    for r in risk:
        s = sub_by_id.get(r["submission_id"])
        day = ((s.get("submitted_at") if s else "") or "")[:10] or "?"
        by_day_total[day] += 1
        if r.get("routing_decision") in ("auto_approve", "auto_reject"):
            by_day_auto[day] += 1
    trend = [
        {
            "date": d,
            "submissions": by_day_total[d],
            "automation_rate": round(by_day_auto[d] / by_day_total[d], 3) if by_day_total[d] else 0.0,
        }
        for d in sorted(by_day_total)
    ]

    # --- recent decisions ---
    recent = sorted(risk, key=lambda r: r.get("decided_at") or "", reverse=True)[:25]
    recent_decisions = [
        {
            "submission_id": r["submission_id"],
            "routing_decision": r.get("routing_decision"),
            "risk_score": _f(r.get("risk_score")),
            "model_version": r.get("model_version"),
            "decided_at": r.get("decided_at"),
        }
        for r in recent
    ]

    reviewer_outcomes = dict(Counter(ra.get("final_decision") for ra in reviewer))

    return Dashboard(
        kpis=kpis,
        routing=dict(routing),
        spend_by_category={k: round(v, 2) for k, v in spend_cat.items()},
        spend_by_oe={k: round(v, 2) for k, v in spend_oe.items()},
        spend_by_currency={k: round(v, 2) for k, v in spend_cur.items()},
        top_rules=top_rules,
        exception_reasons=dict(reasons),
        risk_histogram=hist,
        trend=trend,
        recent_decisions=recent_decisions,
        reviewer_outcomes=reviewer_outcomes,
    )


def compute_compliance_packs(rows: dict[str, list[dict]], cases: list[dict]) -> dict:
    """SOX/ICFR + FCPA/sanctions + recoverable-funds evidence packs (BR-TE-AU-10),
    built entirely from data already captured elsewhere in this app - a
    starting evidence pack an external auditor can pull without database
    access, not a certified report. `cases` is AuditStore.list_case_statuses()
    - a separate call from analytics_rows(), so it's passed in rather than
    fetched here (this module stays pure/store-agnostic, like every other
    function here)."""
    subs_by_id = {s["submission_id"]: s for s in rows["submissions"]}
    risk_by_id = {r["submission_id"]: r for r in rows["risk_decisions"]}
    ver_by_id = {v["submission_id"]: v for v in rows["verification"]}

    total_subs = len(subs_by_id)
    routing_counts = Counter(r.get("routing_decision") for r in rows["risk_decisions"])
    fails = [p for p in rows["policy_evaluations"] if not _truthy(p.get("passed"))]
    rule_counts = Counter(p["rule_id"] for p in fails)
    sox_icfr = {
        "total_submissions": total_subs,
        "auto_approved_pct": round(routing_counts.get("auto_approve", 0) / total_subs, 4)
        if total_subs else 0.0,
        "auto_rejected_pct": round(routing_counts.get("auto_reject", 0) / total_subs, 4)
        if total_subs else 0.0,
        "human_review_pct": round(routing_counts.get("human_review", 0) / total_subs, 4)
        if total_subs else 0.0,
        "violations_by_rule": [
            {"rule_id": rid, "violation_count": n} for rid, n in rule_counts.most_common()
        ],
    }

    flagged = []
    for sid, v in ver_by_id.items():
        compliance = v.get("compliance_flags") or []
        merchant = v.get("merchant_flags") or []
        if not compliance and not merchant:
            continue
        sub = subs_by_id.get(sid, {})
        flagged.append({
            "submission_id": sid,
            "employee_id": sub.get("employee_id", ""),
            "submitted_at": (sub.get("submitted_at") or "")[:10],
            "routing_decision": risk_by_id.get(sid, {}).get("routing_decision", ""),
            "compliance_flags": compliance,
            "merchant_flags": merchant,
        })
    fcpa_sanctions = {"flagged": flagged}

    status_counts = Counter(c.get("status", "open") for c in cases)
    total_recovered = sum(_f(c.get("recovered_amount")) for c in cases if c.get("recovered_amount"))
    recoverable_funds = {
        "cases_tracked": len(cases),
        "claw_back_pending": status_counts.get("claw_back_pending", 0),
        "resolved": status_counts.get("resolved", 0),
        "total_recovered": round(total_recovered, 2),
        "cases": [
            {"submission_id": c["submission_id"], "status": c.get("status"),
             "recovered_amount": c.get("recovered_amount"), "updated_by": c.get("updated_by"),
             "updated_at": c.get("updated_at")}
            for c in cases
        ],
    }

    return {"sox_icfr": sox_icfr, "fcpa_sanctions": fcpa_sanctions,
            "recoverable_funds": recoverable_funds}
