"""Shared test configuration: API auth stub and isolation from live LLM calls."""

import os

import pytest


def pytest_configure(config):
    """Prepare the environment before app.api.server is imported.

    ENVIRONMENT is read at module import time and now defaults to the hardened
    posture, so without this the suite would run against an API demanding a key
    on every call. The tests that care about auth set this themselves and reload
    the module; everything else wants the development posture. setdefault, so CI
    can still pin it explicitly.
    """
    os.environ.setdefault("API_KEY", "test-api-key-for-ci")
    os.environ.setdefault("ENVIRONMENT", "development")


@pytest.fixture(autouse=True)
def no_live_llm_calls(monkeypatch):
    """Keep the suite offline and deterministic.

    app/engines/groq_client.py calls load_dotenv() at import, so a real
    GROQ_API_KEY in .env would otherwise make Groq clients report themselves
    available and issue live network requests mid-test — turning a 3-second run
    into one that hangs on API timeouts and burns quota. Tests that need a
    client stub one in explicitly instead.
    """
    monkeypatch.setenv("GROQ_API_KEY", "")

    # The module-level singleton may already hold a client built from the real
    # key, so drop it and let the next caller rebuild it under the empty value.
    import app.engines.groq_client as groq_module

    monkeypatch.setattr(groq_module, "_client_instance", None)
    yield
    groq_module._client_instance = None
