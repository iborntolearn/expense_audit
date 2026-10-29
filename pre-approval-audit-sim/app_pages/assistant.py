"""Ask page - conversational Q&A over the audit data."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app_common import get_data_layer
from assistant.engine import EXAMPLES, answer
from pipeline.config import load_pipeline_config


@st.cache_data(ttl=30)
def _rows():
    return get_data_layer().store.analytics_rows()


def _render(ans) -> None:
    st.markdown(ans.text)
    if ans.metric:
        st.metric(ans.metric[0], ans.metric[1])
    if ans.chart:
        df = pd.DataFrame(ans.chart["data"])
        if not df.empty:
            st.bar_chart(df, x=ans.chart["label"], y=ans.chart["value"], horizontal=True)
    if ans.table:
        st.dataframe(pd.DataFrame(ans.table), hide_index=True, width="stretch")
    if ans.suggestions:
        for s in ans.suggestions:
            st.markdown(f"- {s}")


if "chat" not in st.session_state:
    st.session_state.chat = []  # list of (role, question, answer_or_none)

st.caption("Ask about unauthorized spend, duplicates, high-risk reports, automation, and more.")

# example prompt chips
picked = st.pills("Examples", EXAMPLES, selection_mode="single", default=None)

rows = _rows()
pcfg = load_pipeline_config()


def _handle(question: str) -> None:
    ans = answer(
        question, rows,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
    )
    st.session_state.chat.append((question, ans))


# replay history
for question, ans in st.session_state.chat:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        _render(ans)

typed = st.chat_input("Ask a question about expense audit data")
if picked and (not st.session_state.chat or st.session_state.chat[-1][0] != picked):
    _handle(picked)
    st.rerun()
if typed:
    _handle(typed)
    st.rerun()
