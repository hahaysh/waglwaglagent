"""Validate the existing API target and native configuration references before upload."""

import os

from check_web_deployment import REFERENCE_TYPE, azure, https_origin


def validate_api_configuration(settings: list[dict], web_url: str):
    values = {setting["key"]: setting for setting in settings}
    if https_origin(values.get("WAGL_PUBLIC_URL", {}).get("value", "")) != https_origin(web_url):
        raise ValueError("API public URL must match the frontend")
    vault_url = https_origin(values.get("WAGL_KEY_VAULT_URL", {}).get("value", ""))
    import json
    import re

    for key in (
        "WAGL_INTERNAL_SECRET", "WAGL_ENCRYPTION_KEY", "WAGL_DATABASE_URL", "WAGL_REDIS_URL",
        "WAGL_COPILOT_CLIENT_ID", "WAGL_COPILOT_CLIENT_SECRET",
    ):
        setting = values.get(key, {})
        if (setting.get("contentType") or setting.get("content_type") or "").split(";")[0] != REFERENCE_TYPE:
            raise ValueError(f"{key} requires a native Key Vault reference")
        reference = json.loads(setting.get("value", "{}")).get("uri", "")
        if not re.fullmatch(re.escape(vault_url) + r"/secrets/[a-zA-Z0-9-]+", reference):
            raise ValueError(f"{key} references an unexpected vault or secret")
    if values.get("WAGL_COPILOT_CALLBACK_CONFIRMED", {}).get("value") != "true":
        raise ValueError("Production Copilot OAuth callback is not confirmed")


def main():
    subscription = os.environ["AZURE_SUBSCRIPTION_ID"]
    group = os.environ["AZURE_RESOURCE_GROUP"]
    app = azure(
        "webapp", "show", "--subscription", subscription,
        "--resource-group", group, "--name", os.environ["AZURE_API_APP"],
    )
    if (
        f"https://{app['defaultHostName']}" != os.environ["AZURE_API_URL"]
        or not (app.get("identity") or {}).get("principalId")
    ):
        raise ValueError("API target hostname or Managed Identity is incorrect")
    configuration = azure(
        "webapp", "config", "show", "--subscription", subscription,
        "--resource-group", group, "--name", os.environ["AZURE_API_APP"],
    )
    if configuration.get("linuxFxVersion") != "PYTHON|3.12":
        raise ValueError("API requires the Python 3.12 Linux runtime")
    settings = azure(
        "appconfig", "kv", "list", "--subscription", subscription,
        "--endpoint", os.environ["WAGL_APP_CONFIG_ENDPOINT"],
        "--label", "production-api", "--auth-mode", "login",
    )
    validate_api_configuration(settings, os.environ["AZURE_WEB_APP_URL"])
    print("API target and production references verified; no secret values requested.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"API deployment preflight failed: {error}") from None
