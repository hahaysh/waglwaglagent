import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packager = load_script("package_web")
preflight = load_script("check_web_deployment")
configuration = load_script("configure_webapp")


def production_settings():
    values = {
        "AUTH_URL": "https://example.azurewebsites.net",
        "AUTH_TRUST_HOST": "true",
        "WAGL_PUBLIC_URL": "https://example.azurewebsites.net",
        "WAGL_KEY_VAULT_URL": "https://example.vault.azure.net/",
        "WAGL_API_URL": "https://api.azurewebsites.net",
        "WAGL_OAUTH_CALLBACK_CONFIRMED": "true",
    }
    settings = [{"key": key, "value": value} for key, value in values.items()]
    for key in ("AUTH_SECRET", "AUTH_GITHUB_ID", "AUTH_GITHUB_SECRET", "WAGL_INTERNAL_SECRET"):
        settings.append({
            "key": key,
            "value": json.dumps({"uri": "https://example.vault.azure.net/secrets/example"}),
            "content_type": preflight.REFERENCE_TYPE + ";charset=utf-8",
        })
    return settings


def test_standalone_archive_has_correct_root_static_and_public_layout(tmp_path):
    web = tmp_path / "apps" / "web"
    standalone = web / ".next" / "standalone"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("standalone-server")
    (standalone / "package.json").write_text("{}")
    static = web / ".next" / "static"
    static.mkdir()
    (static / "chunk.js").write_text("static-asset")
    public = web / "public"
    public.mkdir()
    (public / "logo.svg").write_text("public-asset")
    output = tmp_path / "release.zip"
    packager.package_web(tmp_path, output)
    with zipfile.ZipFile(output) as archive:
        assert archive.read("server.js") == b"standalone-server"
        assert archive.read(".next/static/chunk.js") == b"static-asset"
        assert archive.read("public/logo.svg") == b"public-asset"
        assert "apps/web/server.js" not in archive.namelist()
    (standalone / ".env.local").write_text("PRIVATE=must-not-be-packaged")
    with pytest.raises(ValueError, match="private configuration"):
        packager.package_web(tmp_path, tmp_path / "unsafe.zip")


def test_production_preflight_accepts_native_references_and_separate_https_api():
    assert preflight.validate_configuration(
        production_settings(), "https://example.azurewebsites.net",
    ) == "https://api.azurewebsites.net"


@pytest.mark.parametrize("key,value,reason", [
    ("AUTH_URL", "http://localhost:3000", "public HTTPS"),
    ("WAGL_API_URL", "", "missing"),
    ("WAGL_API_URL", "https://example.azurewebsites.net", "separate FastAPI"),
    ("WAGL_OAUTH_CALLBACK_CONFIRMED", "false", "callback is not confirmed"),
    ("AUTH_SECRET", "private-plaintext-token", "native Key Vault"),
])
def test_preflight_blocks_incomplete_or_unsafe_production_configuration(key, value, reason):
    settings = production_settings()
    selected = next(setting for setting in settings if setting["key"] == key)
    selected["value"] = value
    if key == "AUTH_SECRET":
        selected.pop("content_type")
    with pytest.raises(ValueError, match=reason):
        preflight.validate_configuration(settings, "https://example.azurewebsites.net")


@pytest.mark.parametrize("uri", [
    "https://other.vault.azure.net/secrets/example",
    "https://example.vault.azure.net/secrets/",
    "https://example.vault.azure.net/secrets/example?version=untrusted",
])
def test_preflight_rejects_wrong_vault_or_malformed_secret_reference(uri):
    settings = production_settings()
    reference = next(setting for setting in settings if setting["key"] == "AUTH_SECRET")
    reference["value"] = json.dumps({"uri": uri})
    with pytest.raises(ValueError, match="unexpected Key Vault"):
        preflight.validate_configuration(settings, "https://example.azurewebsites.net")


def test_target_without_managed_identity_is_rejected_explicitly(monkeypatch):
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "test-subscription")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "test-resource-group")
    monkeypatch.setenv("AZURE_WEB_APP", "test-app")
    monkeypatch.setenv("AZURE_WEB_APP_URL", "https://example.azurewebsites.net")
    monkeypatch.setattr(preflight, "azure", lambda *args: {
        "defaultHostName": "example.azurewebsites.net", "identity": None,
    })
    with pytest.raises(ValueError, match="Managed Identity"):
        preflight.main()


@pytest.mark.parametrize("prefix,immutable", [
    ("repo:example@123/test@456", True),
    ("repo:example/test", False),
])
def test_federation_uses_github_reported_subject_prefix(monkeypatch, prefix, immutable):
    def github_settings(executable, *args):
        assert executable == "gh"
        assert args == ("api", "repos/example/test/actions/oidc/customization/sub")
        return {
            "use_default": True, "use_immutable_subject": immutable, "sub_claim_prefix": prefix,
        }

    monkeypatch.setattr(configuration, "command", github_settings)
    assert configuration.github_oidc_subject("example/test") == (
        prefix + ":environment:azure-production"
    )


@pytest.mark.parametrize("settings", [
    {"use_default": False, "sub_claim_prefix": "custom-subject"},
    {"use_default": True},
    {"use_default": True, "sub_claim_prefix": ""},
])
def test_unknown_or_custom_oidc_template_does_not_create_incorrect_trust(monkeypatch, settings):
    monkeypatch.setattr(configuration, "command", lambda *args: settings)
    with pytest.raises(RuntimeError, match="default OIDC subject prefix"):
        configuration.github_oidc_subject("example/test")
