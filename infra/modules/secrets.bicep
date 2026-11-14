param kvName string
param redisName string
param postgresFqdn string
param authGithubId string
@secure()
param postgresAdminPassword string
@secure()
param waglInternalSecret string
@secure()
param waglEncryptionKey string
@secure()
param authSecret string
@secure()
param authGithubSecret string
param copilotClientId string = ''
@secure()
param copilotClientSecret string = ''

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: kvName }
resource redis 'Microsoft.Cache/redisEnterprise@2025-07-01' existing = { name: redisName }
resource redisDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' existing = {
  parent: redis
  name: 'default'
}

resource internalSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'waglwaglagent-internal-secret'
  properties: { value: waglInternalSecret }
}
resource encryptionSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'waglwaglagent-encryption-key'
  properties: { value: waglEncryptionKey }
}
resource authSecretResource 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'waglwaglagent-auth-secret'
  properties: { value: authSecret }
}
resource githubId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(authGithubId) && !empty(authGithubSecret)) {
  parent: vault
  name: 'waglwaglagent-github-id'
  properties: { value: authGithubId }
}
resource githubSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(authGithubId) && !empty(authGithubSecret)) {
  parent: vault
  name: 'waglwaglagent-github-secret'
  properties: { value: authGithubSecret }
}
resource copilotId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(copilotClientId) && !empty(copilotClientSecret)) {
  parent: vault
  name: 'waglwaglagent-copilot-id'
  properties: { value: copilotClientId }
}
resource copilotSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(copilotClientId) && !empty(copilotClientSecret)) {
  parent: vault
  name: 'waglwaglagent-copilot-secret'
  properties: { value: copilotClientSecret }
}
resource postgresPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'waglwaglagent-postgres-password'
  properties: { value: postgresAdminPassword }
}
resource databaseUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'waglwaglagent-database-url'
  properties: {
    value: format('postgresql+psycopg://{0}/waglwaglagent?sslmode=require', 'wagladmin:${uriComponent(postgresAdminPassword)}@${postgresFqdn}:5432')
  }
}
resource redisUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'waglwaglagent-redis-url'
  properties: {
    value: format('rediss://{0}/0', ':${uriComponent(redisDatabase.listKeys().primaryKey)}@${redis.properties.hostName}:10000')
  }
}
