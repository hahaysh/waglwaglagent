param name string
param kvName string
param webHostName string
param apiHostName string
param githubAuthConfigured bool
param copilotAuthConfigured bool
param webPrincipalId string
param apiPrincipalId string

resource configuration 'Microsoft.AppConfiguration/configurationStores@2024-06-01' existing = {
  name: name
}

var referenceType = 'application/vnd.microsoft.appconfig.keyvaultref+json;charset=utf-8'
var vaultUrl = 'https://${kvName}.vault.azure.net/'
var webSettings = {
  AUTH_TRUST_HOST: 'true'
  AUTH_URL: 'https://${webHostName}'
  WAGL_PUBLIC_URL: 'https://${webHostName}'
  WAGL_API_URL: 'https://${apiHostName}'
  WAGL_KEY_VAULT_URL: vaultUrl
  NEXT_TELEMETRY_DISABLED: '1'
}
var apiSettings = {
  WAGL_PUBLIC_URL: 'https://${webHostName}'
  WAGL_KEY_VAULT_URL: vaultUrl
}
var webSecrets = union({
  WAGL_INTERNAL_SECRET: 'waglwaglagent-internal-secret'
  AUTH_SECRET: 'waglwaglagent-auth-secret'
}, githubAuthConfigured ? {
  AUTH_GITHUB_ID: 'waglwaglagent-github-id'
  AUTH_GITHUB_SECRET: 'waglwaglagent-github-secret'
} : {})
var apiSecrets = union({
  WAGL_DATABASE_URL: 'waglwaglagent-database-url'
  WAGL_REDIS_URL: 'waglwaglagent-redis-url'
  WAGL_INTERNAL_SECRET: 'waglwaglagent-internal-secret'
  WAGL_ENCRYPTION_KEY: 'waglwaglagent-encryption-key'
}, copilotAuthConfigured ? {
  WAGL_COPILOT_CLIENT_ID: 'waglwaglagent-copilot-id'
  WAGL_COPILOT_CLIENT_SECRET: 'waglwaglagent-copilot-secret'
} : {})

resource webValues 'Microsoft.AppConfiguration/configurationStores/keyValues@2024-06-01' = [for setting in items(webSettings): {
  parent: configuration
  name: '${setting.key}$production-web'
  properties: { value: setting.value }
}]
resource apiValues 'Microsoft.AppConfiguration/configurationStores/keyValues@2024-06-01' = [for setting in items(apiSettings): {
  parent: configuration
  name: '${setting.key}$production-api'
  properties: { value: setting.value }
}]
resource webReferences 'Microsoft.AppConfiguration/configurationStores/keyValues@2024-06-01' = [for setting in items(webSecrets): {
  parent: configuration
  name: '${setting.key}$production-web'
  properties: {
    value: string({ uri: '${vaultUrl}secrets/${setting.value}' })
    contentType: referenceType
  }
}]
resource apiReferences 'Microsoft.AppConfiguration/configurationStores/keyValues@2024-06-01' = [for setting in items(apiSecrets): {
  parent: configuration
  name: '${setting.key}$production-api'
  properties: {
    value: string({ uri: '${vaultUrl}secrets/${setting.value}' })
    contentType: referenceType
  }
}]

var readerRole = '516239f1-63e1-4d78-a4de-a74fb236a071'
resource runtimeReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in [webPrincipalId, apiPrincipalId]: {
  name: guid(configuration.id, principalId, readerRole)
  scope: configuration
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]
output endpoint string = configuration.properties.endpoint
