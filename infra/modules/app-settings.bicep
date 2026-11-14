param webName string
param apiName string
param kvName string
param acrLoginServer string
param githubAuthConfigured bool
param usePlaceholderImages bool
param webHostName string
param apiHostName string
resource webSettings 'Microsoft.Web/sites/config@2024-11-01' = {
  name: '${webName}/appsettings'
  properties: {
    AUTH_TRUST_HOST: 'true'
    AUTH_URL: 'https://${webHostName}'
    WAGL_PUBLIC_URL: 'https://${webHostName}'
    WAGL_API_URL: 'https://${apiHostName}'
    WAGL_INTERNAL_SECRET: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-internal-secret)'
    AUTH_SECRET: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-auth-secret)'
    AUTH_GITHUB_ID: githubAuthConfigured ? '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-github-id)' : ''
    AUTH_GITHUB_SECRET: githubAuthConfigured ? '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-github-secret)' : ''
    NEXT_TELEMETRY_DISABLED: '1'
    WEBSITES_PORT: usePlaceholderImages ? '80' : '3000'
    WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
    DOCKER_REGISTRY_SERVER_URL: 'https://${acrLoginServer}'
  }
}
resource apiSettings 'Microsoft.Web/sites/config@2024-11-01' = {
  name: '${apiName}/appsettings'
  properties: {
    WAGL_ENVIRONMENT: 'production'
    WAGL_DATABASE_URL: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-database-url)'
    WAGL_REDIS_URL: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-redis-url)'
    WAGL_INTERNAL_SECRET: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-internal-secret)'
    WAGL_ENCRYPTION_KEY: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=waglwaglagent-encryption-key)'
    LITELLM_TELEMETRY: 'False'
    WEBSITES_PORT: usePlaceholderImages ? '80' : '8000'
    WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
    DOCKER_REGISTRY_SERVER_URL: 'https://${acrLoginServer}'
  }
}
