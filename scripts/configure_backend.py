"""Configure the provisioned shared-plan backend. Never deploy application code."""

import argparse
import json
from urllib.parse import quote

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import AzureError
from azure.identity import AzureCliCredential
from azure.keyvault.secrets import SecretClient
from check_api_deployment import validate_api_configuration
from configure_webapp import ENVIRONMENT, REFERENCE_TYPE, az, command


def database_url(host: str, username: str, password: str, database: str) -> str:
    if not host.endswith(".postgres.database.azure.com") or any(
        character in host for character in "/:@?#"
    ):
        raise ValueError("Unexpected PostgreSQL hostname")
    return (
        f"postgresql+psycopg://{quote(username, safe='')}:{quote(password, safe='')}@"
        f"{host}:5432/{quote(database, safe='')}?"
        "sslmode=verify-full&sslrootcert=system&connect_timeout=10"
    )


def sql_database_url(host: str, database: str) -> str:
    import re

    if not re.fullmatch(r"[a-zA-Z0-9-]+\.database\.windows\.net", host):
        raise ValueError("Unexpected Azure SQL hostname")
    return (
        f"mssql+mssqlpython://@{host}:1433/{quote(database, safe='')}?"
        "authentication=ActiveDirectoryMSI&encrypt=yes&trustservercertificate=no"
    )


def redis_url(host: str, password: str) -> str:
    if not host.endswith(".redis.azure.net") or any(
        character in host for character in "/:@?#"
    ):
        raise ValueError("Unexpected Redis hostname")
    return f"rediss://:{quote(password, safe='')}@{host}:10000/0?ssl_cert_reqs=required"


def store_secret(client, name: str, value: str):
    client.set_secret(name, value, logging_enable=False)
    if client.get_secret(name).value != value:
        raise RuntimeError("Production connection secret read-back failed")


def configure(args):
    web = az(args, "webapp", "show", "--resource-group", args.resource_group, "--name", args.web)
    api = az(args, "webapp", "show", "--resource-group", args.resource_group, "--name", args.api)
    if (
        api["appServicePlanId"].lower() != web["appServicePlanId"].lower()
        or not api.get("identity", {}).get("principalId")
        or api["location"].replace(" ", "").lower() != "koreacentral"
    ):
        raise RuntimeError("API must use the existing web plan and Korea Central identity")
    server = az(args, "sql", "server", "show", "--resource-group", args.resource_group,
                "--name", "waglwaglagent-sql")
    database = az(args, "sql", "db", "show", "--resource-group", args.resource_group,
                  "--server", server["name"], "--name", "waglwaglagent-db")
    entra_only = az(
        args, "sql", "server", "ad-only-auth", "get", "--resource-group", args.resource_group,
        "--name", server["name"],
    )
    redis = az(
        args, "resource", "show", "--resource-group", args.resource_group,
        "--resource-type", "Microsoft.Cache/redisEnterprise", "--name", "waglwaglagent-redis",
        "--api-version", "2025-07-01",
    )
    if (
        database["sku"]["name"] != "Basic"
        or database["maxSizeBytes"] != 2147483648
        or not entra_only["azureAdOnlyAuthentication"]
        or redis["sku"]["name"] != "Balanced_B0"
        or redis["properties"]["highAvailability"] != "Disabled"
    ):
        raise RuntimeError("Backend does not match the approved minimal SKU configuration")
    keys = az(
        args, "rest", "--method", "post", "--url",
        "https://management.azure.com" + redis["id"]
        + "/databases/default/listKeys?api-version=2025-07-01",
    )
    credential = AzureCliCredential(tenant_id=args.tenant)
    vault_url = "https://waglwaglagent-kv.vault.azure.net/"
    endpoint = "https://waglwaglagent-config.azconfig.io"
    web_url = f"https://{web['defaultHostName']}"
    api_url = f"https://{api['defaultHostName']}"
    references = {
        "WAGL_INTERNAL_SECRET": "waglwaglagent-production-internal-secret",
        "WAGL_ENCRYPTION_KEY": "waglwaglagent-production-encryption-key",
        "WAGL_DATABASE_URL": "waglwaglagent-production-database-url",
        "WAGL_REDIS_URL": "waglwaglagent-production-redis-url",
        "WAGL_COPILOT_CLIENT_ID": "waglwaglagent-production-copilot-id",
        "WAGL_COPILOT_CLIENT_SECRET": "waglwaglagent-production-copilot-secret",
    }
    with SecretClient(vault_url, credential, logging_enable=False) as vault:
        store_secret(vault, references["WAGL_DATABASE_URL"], sql_database_url(
            server["fullyQualifiedDomainName"], database["name"],
        ))
        store_secret(vault, references["WAGL_REDIS_URL"], redis_url(
            redis["properties"]["hostName"], keys["primaryKey"],
        ))
        for name in references.values():
            if not vault.get_secret(name).value:
                raise RuntimeError("Production secret is empty")

    with AzureAppConfigurationClient(endpoint, credential, logging_enable=False) as settings:
        # This flag is set only by the separately verified real OAuth registration.
        confirmed = settings.get_configuration_setting(
            "WAGL_COPILOT_CALLBACK_CONFIRMED", label="production-api"
        ).value
        if confirmed != "true":
            raise RuntimeError("Production Copilot callback has not been verified")
        for key, value in {
            "WAGL_PUBLIC_URL": web_url,
            "WAGL_KEY_VAULT_URL": vault_url,
        }.items():
            settings.set_configuration_setting(ConfigurationSetting(
                key=key, label="production-api", value=value,
            ))
        for key, name in references.items():
            settings.set_configuration_setting(ConfigurationSetting(
                key=key, label="production-api", content_type=REFERENCE_TYPE,
                value=json.dumps({"uri": vault_url + "secrets/" + name}),
            ))
        settings.set_configuration_setting(ConfigurationSetting(
            key="WAGL_API_URL", label="production-web", value=api_url,
        ))
        actual = [
            {"key": item.key, "value": item.value, "contentType": item.content_type}
            for item in settings.list_configuration_settings(label_filter="production-api")
        ]
        validate_api_configuration(actual, web_url)

    az(
        args, "webapp", "config", "appsettings", "set",
        "--resource-group", args.resource_group, "--name", args.api, "--settings",
        "WAGL_ENVIRONMENT=production", f"WAGL_APP_CONFIG_ENDPOINT={endpoint}",
        "WAGL_APP_CONFIG_LABEL=production-api", "SCM_DO_BUILD_DURING_DEPLOYMENT=false",
        "ENABLE_ORYX_BUILD=false",
    )
    for key, value in {"AZURE_API_APP": args.api, "AZURE_API_URL": api_url}.items():
        command("gh", "variable", "set", key, "--repo", args.repository,
                "--env", ENVIRONMENT, "--body", value)
    print("Verified backend SKU, stored connection secrets and configured native references.")
    print("No application upload or startup activation performed.")
    print(f"API: {api_url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--resource-group", default="waglwaglagent_rg")
    parser.add_argument("--web", default="waglwaglagent")
    parser.add_argument("--api", default="waglwaglagent-api")
    parser.add_argument("--repository", default="hahaysh/waglwaglagent")
    try:
        configure(parser.parse_args())
    except (RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(f"Backend configuration failed ({type(error).__name__}); no values logged.") from None
    except AzureError as error:
        raise SystemExit(f"Azure configuration failed ({type(error).__name__}); no values logged.") from None
