"""Configure an existing Web App and GitHub OIDC. Never deploy application code."""

import argparse
import json
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import AzureCliCredential
from azure.keyvault.secrets import SecretClient

ENVIRONMENT = "azure-production"
READER_ROLE = "516239f1-63e1-4d78-a4de-a74fb236a071"
SECRET_USER_ROLE = "4633458b-17de-408a-b874-0445c86b69e6"
WEBSITE_ROLE = "de139f84-1756-47ae-9be6-808fbbe84772"
REFERENCE_TYPE = "application/vnd.microsoft.appconfig.keyvaultref+json;charset=utf-8"


def command(executable: str, *args: str, payload=None):
    binary = shutil.which(executable)
    if not binary:
        raise RuntimeError(f"Required CLI is not installed: {executable}")
    result = subprocess.run(
        [binary, *args], input=json.dumps(payload) if payload is not None else None,
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"{executable} command failed; operation: {' '.join(args[:3])}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def az(args, *parts):
    return command(
        "az", *parts, "--subscription", args.subscription, "--output", "json", "--only-show-errors",
    )


def assign_role(args, principal: str, role: str, scope: str):
    az(args, "role", "assignment", "create", "--assignee-object-id", principal,
       "--assignee-principal-type", "ServicePrincipal", "--role", role, "--scope", scope)


def github_oidc_subject(repository: str) -> str:
    settings = command("gh", "api", f"repos/{repository}/actions/oidc/customization/sub")
    prefix = settings.get("sub_claim_prefix")
    if settings.get("use_default") is not True or not isinstance(prefix, str) or not prefix:
        raise RuntimeError("GitHub must expose its default OIDC subject prefix; check OIDC settings")
    return f"{prefix}:environment:{ENVIRONMENT}"


def configure(args):
    subject = github_oidc_subject(args.repository)
    app = az(args, "webapp", "show", "--resource-group", args.resource_group, "--name", args.app)
    if app.get("kind") != "app,linux":
        raise RuntimeError("Only existing Linux code Web Apps are supported")
    host = app["defaultHostName"]
    app_id = app["id"]
    web_url = f"https://{host}"
    config = az(
        args, "resource", "show", "--resource-group", args.resource_group,
        "--resource-type", "Microsoft.AppConfiguration/configurationStores",
        "--name", args.configuration, "--api-version", "2024-06-01",
    )
    vault = az(args, "keyvault", "show", "--resource-group", args.resource_group,
               "--name", args.vault)
    endpoint = config["properties"]["endpoint"]
    vault_url = vault["properties"]["vaultUri"]
    identity = az(args, "webapp", "identity", "assign", "--resource-group", args.resource_group,
                  "--name", args.app)
    web_principal = identity["principalId"]
    assign_role(args, web_principal, READER_ROLE, config["id"])
    secret_names = {
        "AUTH_SECRET": f"{args.app}-production-auth-secret",
        "WAGL_INTERNAL_SECRET": f"{args.app}-production-internal-secret",
        "AUTH_GITHUB_ID": f"{args.app}-production-github-id",
        "AUTH_GITHUB_SECRET": f"{args.app}-production-github-secret",
    }
    for name in secret_names.values():
        assign_role(args, web_principal, SECRET_USER_ROLE, vault["id"] + "/secrets/" + name)

    credential = AzureCliCredential(tenant_id=args.tenant)
    with SecretClient(vault_url, credential, logging_enable=False) as secret_client:
        for field in ("AUTH_SECRET", "WAGL_INTERNAL_SECRET"):
            try:
                secret_client.get_secret(secret_names[field])
            except ResourceNotFoundError:
                value = secrets.token_urlsafe(48)
                secret_client.set_secret(secret_names[field], value, logging_enable=False)
                if secret_client.get_secret(secret_names[field]).value != value:
                    raise RuntimeError("Production secret read-back verification failed")

    with AzureAppConfigurationClient(endpoint, credential, logging_enable=False) as settings:
        ordinary = {
            "AUTH_URL": web_url,
            "AUTH_TRUST_HOST": "true",
            "WAGL_PUBLIC_URL": web_url,
            "WAGL_KEY_VAULT_URL": vault_url,
            "NEXT_TELEMETRY_DISABLED": "1",
        }
        for key, value in ordinary.items():
            settings.set_configuration_setting(ConfigurationSetting(
                key=key, label="production-web", value=value,
            ))
        try:
            settings.get_configuration_setting("WAGL_OAUTH_CALLBACK_CONFIRMED", label="production-web")
        except ResourceNotFoundError:
            settings.set_configuration_setting(ConfigurationSetting(
                key="WAGL_OAUTH_CALLBACK_CONFIRMED", label="production-web", value="false",
            ))
        for key, name in secret_names.items():
            settings.set_configuration_setting(ConfigurationSetting(
                key=key, label="production-web", content_type=REFERENCE_TYPE,
                value=json.dumps({"uri": vault_url.rstrip("/") + "/secrets/" + name}),
            ))
        # Never invent a backend URL or copy the local SQLite/API configuration.
        if args.api_url:
            from check_web_deployment import https_origin

            settings.set_configuration_setting(ConfigurationSetting(
                key="WAGL_API_URL", label="production-web", value=https_origin(args.api_url),
            ))

    deploy_identity = az(args, "identity", "create", "--resource-group", args.resource_group,
                         "--name", f"{args.app}-github-deploy", "--location", app["location"])
    az(args, "identity", "federated-credential", "create",
       "--resource-group", args.resource_group, "--identity-name", deploy_identity["name"],
       "--name", "github-main-production",
       "--issuer", "https://token.actions.githubusercontent.com",
       "--subject", subject,
       "--audiences", "api://AzureADTokenExchange")
    assign_role(args, deploy_identity["principalId"], WEBSITE_ROLE, app_id)
    assign_role(args, deploy_identity["principalId"], READER_ROLE, config["id"])

    with tempfile.TemporaryDirectory(prefix="wagl-runtime-") as directory:
        configuration = Path(directory) / "runtime.json"
        configuration.write_text(json.dumps({
            "linuxFxVersion": "NODE|24-lts",
            "alwaysOn": True,
            "ftpsState": "Disabled",
            "http20Enabled": True,
            "healthCheckPath": "/",
        }), encoding="utf-8")
        az(args, "webapp", "config", "set",
           "--resource-group", args.resource_group, "--name", args.app,
           "--generic-configurations", "@" + str(configuration))
    az(args, "webapp", "config", "appsettings", "set",
       "--resource-group", args.resource_group, "--name", args.app, "--settings",
       "WAGL_ENVIRONMENT=production", f"WAGL_APP_CONFIG_ENDPOINT={endpoint}",
       "WAGL_APP_CONFIG_LABEL=production-web", "SCM_DO_BUILD_DURING_DEPLOYMENT=false",
       "ENABLE_ORYX_BUILD=false", "NODE_ENV=production", "HOSTNAME=0.0.0.0")

    environment_path = f"repos/{args.repository}/environments/{ENVIRONMENT}"
    command("gh", "api", "--method", "PUT", environment_path, "--input", "-", payload={
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
    })
    policies = command("gh", "api", environment_path + "/deployment-branch-policies")
    if not any(item["name"] == "main" and item["type"] == "branch"
               for item in policies["branch_policies"]):
        command("gh", "api", "--method", "POST",
                environment_path + "/deployment-branch-policies", "--input", "-",
                payload={"name": "main", "type": "branch"})
    variables = {
        "AZURE_CLIENT_ID": deploy_identity["clientId"],
        "AZURE_TENANT_ID": args.tenant,
        "AZURE_SUBSCRIPTION_ID": args.subscription,
        "AZURE_RESOURCE_GROUP": args.resource_group,
        "AZURE_WEB_APP": args.app,
        "AZURE_WEB_APP_URL": web_url,
        "WAGL_APP_CONFIG_ENDPOINT": endpoint,
    }
    for key, value in variables.items():
        command("gh", "variable", "set", key, "--repo", args.repository,
                "--env", ENVIRONMENT, "--body", value)
    print("Configured existing Web App, production settings, runtime access and main-only OIDC.")
    print("No application archive uploaded, no deployment started, no workflow dispatched.")
    print("Before first deployment: production API URL and production GitHub OAuth are required.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--app", default="waglwaglagent")
    parser.add_argument("--configuration", default="waglwaglagent-config")
    parser.add_argument("--vault", default="waglwaglagent-kv")
    parser.add_argument("--repository", default="hahaysh/waglwaglagent")
    parser.add_argument("--api-url")
    try:
        configure(parser.parse_args())
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except AzureError as error:
        raise SystemExit(
            f"Azure data configuration failed ({type(error).__name__}); no values logged."
        ) from None
