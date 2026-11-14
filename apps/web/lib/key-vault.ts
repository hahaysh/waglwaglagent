import { AzureCliCredential, ManagedIdentityCredential } from "@azure/identity";
import { SecretClient } from "@azure/keyvault-secrets";
import { AppConfigurationClient } from "@azure/app-configuration";

type SecretReader = {
  getSecret(
    name: string, options?: { version?: string; abortSignal?: AbortSignal },
  ): Promise<{ value?: string }>;
};

const fields = [
  "AUTH_SECRET", "AUTH_GITHUB_ID", "AUTH_GITHUB_SECRET", "WAGL_INTERNAL_SECRET",
] as const;

export async function resolveVaultEnvironment(
  env: Record<string, string | undefined>,
  client: SecretReader,
): Promise<Record<string, string>> {
  const resolved: Record<string, string> = {};
  for (const field of fields) {
    const value = env[field];
    if (!value) {
      if (field !== "AUTH_GITHUB_ID" && field !== "AUTH_GITHUB_SECRET") {
        throw new Error(`Missing required Key Vault reference: ${field}`);
      }
      continue;
    }
    const reference = /^kv:\/\/([a-zA-Z0-9-]{1,127})(?:\/([a-fA-F0-9]{32}))?$/.exec(value);
    if (!reference) throw new Error(`Expected a Key Vault reference: ${field}`);
    try {
      const secret = await client.getSecret(reference[1], {
        version: reference[2], abortSignal: AbortSignal.timeout(15000),
      });
      if (!secret.value) throw new Error("Empty secret");
      resolved[field] = secret.value;
    } catch {
      throw new Error(`Key Vault read failed for ${field}; check login, access and availability`);
    }
  }
  return resolved;
}

export async function loadVaultEnvironment(): Promise<void> {
  const env = process.env;
  const credential = env.WAGL_ENVIRONMENT === "production"
    ? new ManagedIdentityCredential(env.WAGL_MANAGED_IDENTITY_CLIENT_ID
      ? { clientId: env.WAGL_MANAGED_IDENTITY_CLIENT_ID } : {})
    : new AzureCliCredential({ tenantId: env.WAGL_AZURE_TENANT_ID });
  if (env.WAGL_APP_CONFIG_ENDPOINT) {
    if (!/^https:\/\/[a-zA-Z0-9-]+\.azconfig\.io\/?$/.test(env.WAGL_APP_CONFIG_ENDPOINT)
      || !env.WAGL_APP_CONFIG_LABEL) {
      throw new Error("Invalid App Configuration endpoint or missing label");
    }
    const configuration = new AppConfigurationClient(env.WAGL_APP_CONFIG_ENDPOINT, credential);
    const settings: Record<string, string> = {};
    const hosts = new Set<string>();
    const allowed = new Set<string>([
      ...fields, "AUTH_URL", "AUTH_TRUST_HOST", "WAGL_API_URL", "WAGL_PUBLIC_URL",
      "WAGL_KEY_VAULT_URL", "NEXT_TELEMETRY_DISABLED",
    ]);
    try {
      for await (const setting of configuration.listConfigurationSettings({
        labelFilter: env.WAGL_APP_CONFIG_LABEL,
        abortSignal: AbortSignal.timeout(30000),
      })) {
        if (!allowed.has(setting.key)) continue;
        if (typeof setting.value !== "string") throw new Error("Missing configuration value");
        let value = setting.value;
        if (setting.contentType?.split(";")[0]
          === "application/vnd.microsoft.appconfig.keyvaultref+json") {
          const uri = new URL(JSON.parse(value).uri);
          const match = /^\/secrets\/([a-zA-Z0-9-]+)(?:\/([a-fA-F0-9]{32}))?$/.exec(uri.pathname);
          if (uri.protocol !== "https:" || !match || uri.search || uri.hash
            || uri.username || uri.password) throw new Error("Invalid vault reference");
          hosts.add(uri.host);
          value = `kv://${match[1]}${match[2] ? `/${match[2]}` : ""}`;
        }
        settings[setting.key] = value;
      }
      if (!settings.WAGL_KEY_VAULT_URL || [...hosts].some(
        (host) => host !== new URL(settings.WAGL_KEY_VAULT_URL).host,
      )) throw new Error("Missing or mismatched Key Vault URL");
    } catch {
      throw new Error("App Configuration read failed; check login, access and environment label");
    }
    Object.assign(env, settings);
  } else if (env.WAGL_ENVIRONMENT === "production") {
    throw new Error("Production requires Azure App Configuration");
  }
  const url = env.WAGL_KEY_VAULT_URL;
  if (!url) {
    if (fields.some((field) => env[field]?.startsWith("kv://"))) {
      throw new Error("Key Vault references require WAGL_KEY_VAULT_URL");
    }
    if (env.WAGL_ENVIRONMENT === "production") {
      throw new Error("Production requires Azure Key Vault");
    }
    return;
  }
  if (!/^https:\/\/[a-zA-Z0-9-]+\.vault\.azure\.net\/?$/.test(url)) {
    throw new Error("Invalid Azure Key Vault URL");
  }
  const client = new SecretClient(url, credential, {
    retryOptions: { maxRetries: 2 },
  });
  Object.assign(env, await resolveVaultEnvironment(env, client));
}
