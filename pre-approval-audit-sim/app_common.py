"""Shared resources for the unified Streamlit app.

One data layer + pipeline + review service, shared across the Dashboard, Review,
and Settings pages via st.cache_resource. Settings edits config files, then calls
reload() to rebuild everything against the new config.
"""
from __future__ import annotations

import streamlit as st

from adapters.factory import build_vision_extractor
from config.settings import get_settings
from data.factory import build_data_layer
from pipeline.config import load_pipeline_config
from pipeline.factory import build_pipeline
from review_ui.service import ReviewService


@st.cache_resource
def get_data_layer():
    data = build_data_layer(get_settings())
    data.migrate()
    return data


@st.cache_resource
def get_pipeline():
    return build_pipeline(get_data_layer(), get_settings())


@st.cache_resource
def get_vision_extractor():
    """Standalone accessor for the configured VisionExtractor, used by the
    custom-submission auto-detect flow to itemize an uploaded invoice BEFORE a
    submission (and its report_lines) exist - i.e. outside the pipeline proper."""
    return build_vision_extractor(get_settings(), load_pipeline_config())


@st.cache_resource
def get_review_service() -> ReviewService:
    return ReviewService(get_data_layer(), get_pipeline())


def reload() -> None:
    """Drop cached settings + resources so config changes take effect."""
    get_settings.cache_clear()
    st.cache_resource.clear()
