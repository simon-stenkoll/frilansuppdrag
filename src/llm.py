"""Shared OpenAI-compatible LLM client factory.

One place that knows how the pipeline authenticates, so classifier, portal extraction
and discovery always talk to the same provider. Endpoint, model and the name of the
key env var all come from src/config.py, which reads them from the environment, so
switching key, Google project or provider entirely never needs a code change.
"""

import os

from openai import OpenAI

from src.config import LLM_API_KEY_ENV, LLM_ENDPOINT


def api_key_env_name() -> str:
    """Name of the env var the API key is read from (for log lines)."""
    return LLM_API_KEY_ENV


def make_llm_client() -> OpenAI | None:
    """OpenAI-compatible client, or None when no API key is configured."""
    api_key = os.environ.get(LLM_API_KEY_ENV)
    if not api_key:
        return None
    return OpenAI(base_url=LLM_ENDPOINT, api_key=api_key)
