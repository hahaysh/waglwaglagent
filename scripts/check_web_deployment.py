"""Fail before deployment if the selected Web App or its production settings are incomplete."""

import json
import os
import re
import shutil
import subprocess
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

REFERENCE_TYPE = "application/vnd.microsoft.appconfig.keyvaultref+json"


def https_origin(value: str) -> str:
    uri = urlsplit(value)
    if (
        uri.scheme != "https" or not uri.hostname or uri.username or uri.password
        or uri.path not in {"", "/"} or uri.query or uri.fragment or uri.port not in {None, 443}
        or uri.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("Production URLs must be public HTTPS origins")
    return value.rstrip("/")


def validate_configuration(settings: list[dict], web_url: str) -> str:
    values = {setting["key"]: setting for setting in settings}
    for field in ("AUTH_URL", "WAGL_PUBLIC_URL"):
        if https_origin(values.get(field, {}).get("value", "")) != https_origin(web_url):
            raise ValueError(f"{field} must match the target Web App HTTPS origin")
    if values.get("AUTH_TRUST_HOST", {}).get("value") != "true":
        raise ValueError("AUTH_TRUST_HOST must be true behind the App Service proxy")
    vault_url = https_origin(values.get("WAGL_KEY_VAULT_URL", {}).get("value", ""))
    if not urlsplit(vault_url).hostname.endswith(".vault.azure.net"):
        raise ValueError("Expected Azure Key Vault URL")
    for field in ("AUTH_SECRET", "AUTH_GITHUB_ID", "AUTH_GITHUB_SECRET", "WAGL_INTERNAL_SECRET"):
        setting = values.get(field, {})
        if (setting.get("content_type") or setting.get("contentType") or "").split(";")[0] != REFERENCE_TYPE:
            raise ValueError(f"{field} must be a native Key Vault reference, not a plaintext value")
        try:
            uri = urlsplit(json.loads(setting["value"])["uri"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Invalid Key Vault reference for {field}") from None
        if (
            f"{uri.scheme}://{uri.netloc}" != vault_url or uri.username or uri.password
            or uri.query or uri.fragment
            or not re.fullmatch(r"/secrets/[a-zA-Z0-9-]+(?:/[a-zA-Z0-9]+)?", uri.path)
        ):
            raise ValueError(f"{field} references an unexpected Key Vault")
    if values.get("WAGL_OAUTH_CALLBACK_CONFIRMED", {}).get("value") != "true":
        raise ValueError(
            "Production GitHub OAuth callback is not confirmed. Register the production OAuth app, "
            "save its ID/secret in Key Vault, and set WAGL_OAUTH_CALLBACK_CONFIRMED=true."
        )
    api_url = values.get("WAGL_API_URL", {}).get("value", "")
    if not api_url:
        raise ValueError(
            "WAGL_API_URL is missing in production-web. Provision/configure the FastAPI backend "
            "with production Azure SQL/Redis before deploying the frontend."
        )
    api_url = https_origin(api_url)
    if api_url == https_origin(web_url):
        raise ValueError("WAGL_API_URL must target the separate FastAPI backend, not this Next.js app")
    return api_url


def azure(*args: str):
    result = subprocess.run(
        [shutil.which("az") or "az", *args, "--output", "json", "--only-show-errors"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ValueError("Azure configuration lookup failed; check OIDC roles and resource names")
    return json.loads(result.stdout)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    subscription = os.environ["AZURE_SUBSCRIPTION_ID"]
    app = azure(
        "webapp", "show", "--subscription", subscription,
        "--resource-group", os.environ["AZURE_RESOURCE_GROUP"],
        "--name", os.environ["AZURE_WEB_APP"],
    )
    web_url = os.environ["AZURE_WEB_APP_URL"].rstrip("/")
    if web_url != f"https://{app['defaultHostName']}" or not (app.get("identity") or {}).get("principalId"):
        raise ValueError("Target Web App hostname or Managed Identity does not match")
    configuration = azure(
        "webapp", "config", "show", "--subscription", subscription,
        "--resource-group", os.environ["AZURE_RESOURCE_GROUP"],
        "--name", os.environ["AZURE_WEB_APP"],
    )
    if configuration.get("linuxFxVersion") != "NODE|24-lts":
        raise ValueError("The target Web App must use the Node 24 LTS Linux runtime")
    settings = azure(
        "appconfig", "kv", "list", "--subscription", subscription,
        "--endpoint", os.environ["WAGL_APP_CONFIG_ENDPOINT"],
        "--label", os.environ["WAGL_APP_CONFIG_LABEL"], "--auth-mode", "login",
    )
    api_url = validate_configuration(settings, web_url)
    try:
        with build_opener(NoRedirect()).open(api_url + "/ready", timeout=20) as response:
            if response.status != 200 or json.load(response).get("status") != "ok":
                raise ValueError("The production FastAPI health check failed")
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError("Production API is not reachable; no archive was uploaded") from None
    print("Production target, Key Vault references, OAuth readiness and API health verified.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as error:
        raise SystemExit(f"Deployment preflight failed: {error}") from None
