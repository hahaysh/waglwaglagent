targetScope = 'resourceGroup'

param location string = 'koreacentral'
param planName string = 'waglwaglagent-asp'
param apiName string = 'waglwaglagent-api'
param postgresName string = 'waglwaglagent-postgres'
param redisName string = 'waglwaglagent-redis'
param vaultName string = 'waglwaglagent-kv'
param configurationName string = 'waglwaglagent-config'
param deploymentIdentityName string = 'waglwaglagent-github-deploy'
@secure()
param postgresPassword string

var tags = { application: 'waglwaglagent', environment: 'production' }

resource plan 'Microsoft.Web/serverfarms@2024-11-01' existing = {
  name: planName
}
resource vault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: vaultName
}
resource configuration 'Microsoft.AppConfiguration/configurationStores@2024-06-01' existing = {
  name: configurationName
}
resource deploymentIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: deploymentIdentityName
}
resource api 'Microsoft.Web/sites@2024-11-01' = {
  name: apiName
  location: location
  tags: tags
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      http20Enabled: true
    }
  }
}
module postgres './modules/postgres.bicep' = {
  name: 'waglwaglagent-postgres'
  params: {
    name: postgresName
    location: location
    tags: tags
    administratorLogin: 'wagladmin'
    administratorLoginPassword: postgresPassword
    databaseName: 'waglwaglagent-db'
    outboundIpRanges: split(api.properties.possibleOutboundIpAddresses, ',')
  }
}
module redis './modules/managed-redis.bicep' = {
  name: 'waglwaglagent-redis'
  params: { name: redisName, location: location, tags: tags }
}
var configurationReaderRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '516239f1-63e1-4d78-a4de-a74fb236a071'
)
resource apiConfigurationReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(configuration.id, api.id, configurationReaderRole)
  scope: configuration
  properties: {
    principalId: api.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: configurationReaderRole
  }
}
var secretsOfficerRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
)
resource apiSecretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, api.id, secretsOfficerRole)
  scope: vault
  properties: {
    principalId: api.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: secretsOfficerRole
  }
}
var websiteRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', 'de139f84-1756-47ae-9be6-808fbbe84772'
)
resource apiDeploymentRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(api.id, deploymentIdentity.id, websiteRole)
  scope: api
  properties: {
    principalId: deploymentIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: websiteRole
  }
}
output apiHost string = api.properties.defaultHostName
output apiPrincipalId string = api.identity.principalId
output postgresHost string = postgres.outputs.fqdn
output redisHost string = redis.outputs.hostName
