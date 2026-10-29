"""Adapter selection from config."""
from __future__ import annotations

from adapters.embeddings import EmbeddingClient, SimulatedEmbeddingClient
from adapters.vision import (
    AnthropicVisionExtractor,
    AzureOpenAIVisionExtractor,
    SimulatedVisionExtractor,
    VisionExtractor,
)
from assistant.responder import (
    AnthropicAssistantResponder,
    AssistantResponder,
    AzureOpenAIAssistantResponder,
    SimulatedAssistantResponder,
)
from config.settings import Settings
from pipeline.config import PipelineConfig


def build_assistant_responder(settings: Settings, pcfg: PipelineConfig) -> AssistantResponder:
    provider = pcfg.assistant.provider.lower()
    if provider == "simulated":
        return SimulatedAssistantResponder()
    if provider == "anthropic":
        return AnthropicAssistantResponder(settings.anthropic_api_key, settings.llm_vision_model)
    if provider == "azure_openai":
        return AzureOpenAIAssistantResponder(
            settings.azure_openai_key,
            settings.azure_openai_endpoint,
            settings.azure_deployment_name,
            settings.azure_api_version,
        )
    raise ValueError(f"unknown assistant provider: {provider!r}")


def build_vision_extractor(settings: Settings, pcfg: PipelineConfig) -> VisionExtractor:
    provider = pcfg.extraction.provider.lower()
    if provider == "simulated":
        return SimulatedVisionExtractor(pcfg.extraction)
    if provider == "anthropic":
        return AnthropicVisionExtractor(
            pcfg.extraction, settings.anthropic_api_key, settings.llm_vision_model
        )
    if provider == "azure_openai":
        return AzureOpenAIVisionExtractor(
            pcfg.extraction,
            settings.azure_openai_key,
            settings.azure_openai_endpoint,
            settings.azure_deployment_name,
            settings.azure_api_version,
        )
    raise ValueError(f"unknown extraction provider: {provider!r}")


def build_embedding_client(settings: Settings) -> EmbeddingClient:
    # Only the simulated client exists in this build; a real embedding model
    # implements EmbeddingClient later with no change to callers.
    return SimulatedEmbeddingClient(settings.embedding_dim)
