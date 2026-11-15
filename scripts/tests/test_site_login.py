import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "configure_site_login", Path(__file__).parents[1] / "configure_site_login.py",
)
site_login = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site_login)


def test_callback_urls_are_environment_specific_and_never_redirect_to_arbitrary_paths():
    assert site_login.callback_url(
        "http://localhost:3000", "local", "google",
    ) == "http://localhost:3000/api/auth/callback/google"
    for origin in (
        "http://localhost:3000", "http://example.test", "https://user:secret@example.test",
        "https://example.test/path", "https://example.test?redirect=other",
    ):
        with pytest.raises(ValueError):
            site_login.callback_url(origin, "production", "google")


def test_google_credentials_require_official_web_client_and_production_redirects(tmp_path):
    path = tmp_path / "google.json"
    web = {
        "client_id": "test.apps.googleusercontent.com", "client_secret": "test-only-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["https://site.example/api/auth/callback/google"],
    }
    path.write_text(json.dumps({"web": web}))
    assert site_login.google_credentials(path, web["redirect_uris"][0], "production")[0] == (
        "test.apps.googleusercontent.com"
    )
    for override in (
        {"redirect_uris": web["redirect_uris"] + ["http://localhost:3000/api/auth/callback/google"]},
        {"token_uri": "https://evil.test/token"},
    ):
        path.write_text(json.dumps({"web": web | override}))
        with pytest.raises(ValueError, match="unapproved redirects"):
            site_login.google_credentials(path, web["redirect_uris"][0], "production")


def test_existing_site_configuration_is_not_overwritten_or_given_new_registration(monkeypatch):
    class ExistingSettings:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_configuration_setting(self, **kwargs):
            return object()

    monkeypatch.setattr(site_login, "AzureAppConfigurationClient", ExistingSettings)
    monkeypatch.setattr(site_login, "AzureCliCredential", lambda **kwargs: object())
    monkeypatch.setattr(site_login, "az", lambda *args: {
        "properties": {"endpoint": "https://test.azconfig.io", "vaultUri": "https://test.vault.azure.net"},
    })

    def forbidden(*args):
        pytest.fail("Existing settings must be reviewed before creating a registration")

    monkeypatch.setattr(site_login, "create_microsoft", forbidden)
    with pytest.raises(RuntimeError, match="Existing site login setting"):
        site_login.configure(Namespace(
            public_url="https://site.example", environment="production",
            provider="microsoft-entra-id", google_client_json=None, tenant="test",
            resource_group="test", vault="test", configuration="test",
        ))
