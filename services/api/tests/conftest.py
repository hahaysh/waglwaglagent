import pytest


@pytest.fixture(autouse=True)
def isolate_central_configuration(monkeypatch):
    # Tests must never load the developer's central configuration or real credentials.
    monkeypatch.setenv("WAGL_APP_CONFIG_ENDPOINT", "")
    monkeypatch.setenv("WAGL_APP_CONFIG_LABEL", "")
    monkeypatch.setenv("WAGL_KEY_VAULT_URL", "")
    monkeypatch.setenv("WAGL_COPILOT_CLIENT_ID", "")
    monkeypatch.setenv("WAGL_COPILOT_CLIENT_SECRET", "")
