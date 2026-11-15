"""Configure one site provider without changing GitHub/Copilot or deploying code."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import AzureCliCredential
from azure.keyvault.secrets import SecretClient

from scripts.configure_webapp import REFERENCE_TYPE, SECRET_USER_ROLE, assign_role, az


def callback_url(origin: str, environment: str, provider: str) -> str:
    uri = urlsplit(origin)
    local = uri.scheme == "http" and uri.hostname in {"localhost", "127.0.0.1"}
    if (
        uri.username or uri.password or uri.query or uri.fragment
        or uri.path not in {"", "/"} or not uri.hostname
        or (environment == "production" and uri.scheme != "https")
        or (uri.scheme != "https" and not (environment == "local" and local))
    ):
        raise ValueError("Expected a public HTTPS origin or a local loopback origin")
    return origin.rstrip("/") + f"/api/auth/callback/{provider}"


def google_credentials(path: Path, callback: str, environment: str) -> tuple[str, str]:
    try:
        web = json.loads(path.read_text(encoding="utf-8"))["web"]
        redirects = web["redirect_uris"]
        if (
            callback not in redirects or web["auth_uri"] != "https://accounts.google.com/o/oauth2/auth"
            or web["token_uri"] != "https://oauth2.googleapis.com/token"
            or not web["client_id"].endswith(".apps.googleusercontent.com")
            or not web["client_secret"]
            or (environment == "production" and any(
                urlsplit(uri).scheme != "https"
                or urlsplit(uri).hostname in {"localhost", "127.0.0.1"} for uri in redirects
            ))
        ):
            raise ValueError("Invalid Google client or callback")
        return web["client_id"], web["client_secret"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Google Web client JSON is invalid or has unapproved redirects") from None


def create_microsoft(credential, name: str, callback: str) -> tuple[str, str]:
    token = credential.get_token("https://graph.microsoft.com/.default").token
    with httpx.Client(
        base_url="https://graph.microsoft.com/v1.0/",
        headers={"Authorization": f"Bearer {token}"}, follow_redirects=False, timeout=30,
    ) as graph:
        existing = graph.get("applications", params={
            "$filter": f"displayName eq '{name}'", "$select": "id,appId", "$top": "2",
        })
        if existing.status_code != 200:
            raise RuntimeError("Entra registration lookup failed; official user login may be required")
        if existing.json().get("value"):
            raise RuntimeError(
                "This registration already exists; stop rather than reset its credentials. "
                "Resume its explicit setup with the operator."
            )
        response = graph.post("applications", json={
            "displayName": name, "signInAudience": "PersonalMicrosoftAccount",
            "web": {"redirectUris": [callback], "implicitGrantSettings": {
                "enableAccessTokenIssuance": False, "enableIdTokenIssuance": False,
            }},
            "requiredResourceAccess": [],
        })
        if response.status_code != 201:
            raise RuntimeError("Microsoft personal-only app creation failed; check registration rights")
        application = response.json()
        password = graph.post(f"applications/{application['id']}/addPassword", json={
            "passwordCredential": {"displayName": "waglwaglagent-site-login"},
        })
        if password.status_code != 200:
            raise RuntimeError(
                f"Registration {application['appId']} created but secret setup failed; "
                "do not recreate or remove it without reviewing this partial result"
            )
        secret = password.json().get("secretText")
        if not secret:
            raise RuntimeError("Entra did not return a client secret")
        return application["appId"], secret


def configure(args):
    callback = callback_url(args.public_url, args.environment, args.provider)
    if args.provider == "google" and not args.google_client_json:
        raise ValueError("Google requires the official downloaded Web client JSON")
    if args.provider != "google" and args.google_client_json:
        raise ValueError("Google credentials cannot configure Microsoft")
    credential = AzureCliCredential(tenant_id=args.tenant)
    vault = az(args, "keyvault", "show", "--resource-group", args.resource_group,
               "--name", args.vault)
    store = az(
        args, "resource", "show", "--resource-group", args.resource_group,
        "--resource-type", "Microsoft.AppConfiguration/configurationStores",
        "--name", args.configuration, "--api-version", "2024-06-01",
    )
    field = "GOOGLE" if args.provider == "google" else "MICROSOFT_ENTRA_ID"
    label = args.environment + "-web"
    with AzureAppConfigurationClient(
        store["properties"]["endpoint"], credential, logging_enable=False,
    ) as settings:
        for key in (f"AUTH_{field}_ID", f"AUTH_{field}_SECRET", f"WAGL_{field}_CALLBACK_CONFIRMED"):
            try:
                settings.get_configuration_setting(key=key, label=label)
            except ResourceNotFoundError:
                continue
            raise RuntimeError(f"Existing site login setting {key}/{label}; explicit review required")
    name = f"waglwaglagent-{args.environment}-{args.provider}-site"
    secret_name = name + "-secret"
    vault_url = vault["properties"]["vaultUri"]
    with SecretClient(vault_url, credential, logging_enable=False) as client:
        try:
            existing_version = next(iter(client.list_properties_of_secret_versions(secret_name)), None)
        except ResourceNotFoundError:
            existing_version = None
        if existing_version:
            raise RuntimeError(f"Existing site secret {secret_name}; explicit review required")
    client_id, secret = (
        google_credentials(args.google_client_json, callback, args.environment)
        if args.provider == "google" else create_microsoft(credential, name, callback)
    )
    print(json.dumps({"client_id": client_id, "callback": callback, "configuration": "in_progress"}))
    with SecretClient(vault_url, credential, logging_enable=False) as client:
        saved = client.set_secret(secret_name, secret, logging_enable=False)
        if not saved.properties.version:
            raise RuntimeError("Key Vault did not confirm the saved secret version")
        if client.get_secret(secret_name, version=saved.properties.version).value != secret:
            raise RuntimeError("Key Vault secret verification failed")
    if args.environment == "production":
        app = az(args, "webapp", "show", "--resource-group", args.resource_group, "--name", args.app)
        principal = (app.get("identity") or {}).get("principalId")
        if not principal:
            raise ValueError("Production Web App has no Managed Identity")
        assign_role(args, principal, SECRET_USER_ROLE, vault["id"] + "/secrets/" + secret_name)
    with AzureAppConfigurationClient(
        store["properties"]["endpoint"], credential, logging_enable=False,
    ) as settings:
        settings.add_configuration_setting(ConfigurationSetting(
            key=f"AUTH_{field}_ID", label=label, value=client_id,
        ))
        settings.add_configuration_setting(ConfigurationSetting(
            key=f"AUTH_{field}_SECRET", label=label, content_type=REFERENCE_TYPE,
            value=json.dumps({
                "uri": vault_url.rstrip("/")
                + f"/secrets/{secret_name}/{saved.properties.version}",
            }),
        ))
        settings.add_configuration_setting(ConfigurationSetting(
            key=f"WAGL_{field}_CALLBACK_CONFIRMED", label=label, value="true",
        ))
    print(json.dumps({
        "provider": args.provider, "environment": args.environment,
        "client_id": client_id, "callback": callback, "secret_name": secret_name,
        "configured": True, "real_login_verified": False,
    }))
    credential.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("subscription", "tenant", "resource-group", "vault", "configuration", "public-url"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--provider", choices=["google", "microsoft-entra-id"], required=True)
    parser.add_argument("--environment", choices=["local", "production"], required=True)
    parser.add_argument("--app", default="waglwaglagent")
    parser.add_argument("--google-client-json", type=Path)
    args = parser.parse_args()
    try:
        configure(args)
    except AzureError:
        raise SystemExit("Azure login configuration failed; check login and scoped permissions") from None
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
