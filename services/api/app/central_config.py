import json
import re
from urllib.parse import urlsplit

from azure.appconfiguration import AzureAppConfigurationClient
from azure.core.exceptions import AzureError

from app.vault import SecretStoreError

REFERENCE_TYPE = "application/vnd.microsoft.appconfig.keyvaultref+json"


def load_configuration(
    endpoint: str, label: str, environment: str, tenant_id: str = "", client_id: str = "",
) -> dict[str, str]:
    if not re.fullmatch(r"https://[a-zA-Z0-9-]+\.azconfig\.io/?", endpoint) or not label:
        raise SecretStoreError("Invalid App Configuration endpoint or missing environment label")
    # Share the deterministic authentication choice with the vault client.
    from azure.identity import AzureCliCredential, ManagedIdentityCredential

    credential = (
        ManagedIdentityCredential(client_id=client_id or None)
        if environment == "production" else AzureCliCredential(tenant_id=tenant_id or None)
    )
    try:
        with AzureAppConfigurationClient(endpoint, credential, logging_enable=False) as client:
            result = {}
            hosts = set()
            for setting in client.list_configuration_settings(label_filter=label):
                if setting.value is None:
                    raise SecretStoreError("App Configuration contains an empty setting")
                value = setting.value
                if (setting.content_type or "").split(";")[0] == REFERENCE_TYPE:
                    uri = urlsplit(json.loads(value)["uri"])
                    parts = uri.path.strip("/").split("/")
                    if (
                        uri.scheme != "https" or len(parts) not in {2, 3} or parts[0] != "secrets"
                        or uri.query or uri.fragment or uri.username or uri.password
                    ):
                        raise SecretStoreError("Invalid App Configuration Key Vault reference")
                    # Preserve the host for validation after all settings have been read.
                    value = f"kv://{parts[1]}" + (f"/{parts[2]}" if len(parts) == 3 else "")
                    hosts.add(uri.netloc)
                result[setting.key] = value
            expected = urlsplit(result.get("WAGL_KEY_VAULT_URL", "")).netloc
            if hosts and hosts != {expected}:
                raise SecretStoreError("App Configuration references an unexpected Key Vault")
            if not result:
                raise SecretStoreError("App Configuration environment label is empty")
            return result
    except (AzureError, ValueError, KeyError, TypeError):
        raise SecretStoreError("App Configuration read failed; check access and settings") from None
