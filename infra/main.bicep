targetScope = 'subscription'

@minLength(1)
param environmentName string
@minLength(1)
param location string
param sessionId string
param deployedBy string
param createdAt string
param deployerObjectId string
param postgresOutboundIpRanges array = []
param usePlaceholderImages bool = true
param enableDiagnostics bool = false
param authGithubId string = ''
param webImageTag string = 'pilot-placeholder'
param apiImageTag string = 'pilot-placeholder'
param configurationStoreName string = 'waglwaglagent-config'
param configurationResourceGroupName string = 'waglwaglagent_rg'
param copilotClientId string = ''
@secure()
param copilotClientSecret string = ''

@secure()
param postgresAdminPassword string
@secure()
param waglInternalSecret string
@secure()
param waglEncryptionKey string
@secure()
param authSecret string
@secure()
param authGithubSecret string = ''

var tags = {
  application: 'waglwaglagent'
  'app-onboard-skill': 'true'
  'app-onboard-session-id': sessionId
  'created-at': createdAt
  environment: environmentName
  'deployed-by': deployedBy
}
var rgName = 'waglwaglagent-6d0f-rg'
var planName = 'waglwaglagent-6d0f-plan'
var webName = 'waglwaglagent-6d0f-web'
var apiName = 'waglwaglagent-6d0f-api'
var pgName = 'waglwaglagent-6d0f-pg'
var redisName = 'waglwaglagent-6d0f-redis'
var acrName = 'waglwaglagent6d0facr'
var kvName = 'waglwaglagent-6d0f-kv'
var logsName = 'waglwaglagent-6d0f-logs'
var insightsName = 'waglwaglagent-6d0f-insights'
var deployIdentityName = 'waglwaglagent-6d0f-deploy'

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: rgName
  location: location
  tags: tags
}

module logs './modules/log-analytics.bicep' = {
  name: 'waglwaglagent-logs'
  scope: rg
  params: { name: logsName, location: location, tags: tags }
}
module insights './modules/application-insights.bicep' = {
  name: 'waglwaglagent-insights'
  scope: rg
  params: { name: insightsName, location: location, tags: tags, workspaceId: logs.outputs.id }
}
module kv './modules/key-vault.bicep' = {
  name: 'waglwaglagent-key-vault'
  scope: rg
  params: {
    name: kvName
    location: location
    tags: tags
  }
}
module acr './modules/acr.bicep' = {
  name: 'waglwaglagent-acr'
  scope: rg
  params: { name: acrName, location: location, tags: tags }
}
module identity './modules/deploy-identity.bicep' = {
  name: 'waglwaglagent-deploy-identity'
  scope: rg
  params: { name: deployIdentityName, location: location, tags: tags }
}
module plan './modules/app-service-plan.bicep' = {
  name: 'waglwaglagent-app-service-plan'
  scope: rg
  params: { name: planName, location: location, tags: tags }
}
module pg './modules/postgres.bicep' = {
  name: 'waglwaglagent-postgres'
  scope: rg
  params: {
    name: pgName
    location: location
    tags: tags
    administratorLogin: 'wagladmin'
    administratorLoginPassword: postgresAdminPassword
    outboundIpRanges: postgresOutboundIpRanges
  }
}
module redis './modules/managed-redis.bicep' = {
  name: 'waglwaglagent-managed-redis'
  scope: rg
  params: { name: redisName, location: location, tags: tags }
}
module web './modules/app-service.bicep' = {
  name: 'waglwaglagent-web'
  scope: rg
  params: {
    name: webName
    location: location
    tags: tags
    planId: plan.outputs.id
    component: 'web'
    acrLoginServer: acr.outputs.loginServer
    imageTag: webImageTag
    usePlaceholderImages: usePlaceholderImages
    healthPath: '/'
  }
}
module api './modules/app-service.bicep' = {
  name: 'waglwaglagent-api'
  scope: rg
  params: {
    name: apiName
    location: location
    tags: tags
    planId: plan.outputs.id
    component: 'api'
    acrLoginServer: acr.outputs.loginServer
    imageTag: apiImageTag
    usePlaceholderImages: usePlaceholderImages
    healthPath: '/health'
  }
}
module appSettings './modules/app-settings.bicep' = {
  name: 'waglwaglagent-app-settings'
  scope: rg
  dependsOn: [secrets]
  params: {
    webName: webName
    apiName: apiName
    appConfigurationEndpoint: centralSettings.outputs.endpoint
    acrLoginServer: acr.outputs.loginServer
    usePlaceholderImages: usePlaceholderImages
  }
}
module centralSettings './modules/central-settings.bicep' = {
  name: 'waglwaglagent-central-settings'
  scope: resourceGroup(configurationResourceGroupName)
  dependsOn: [secrets]
  params: {
    name: configurationStoreName
    kvName: kvName
    webHostName: web.outputs.defaultHostName
    apiHostName: api.outputs.defaultHostName
    githubAuthConfigured: !empty(authGithubId) && !empty(authGithubSecret)
    copilotAuthConfigured: !empty(copilotClientId) && !empty(copilotClientSecret)
    webPrincipalId: web.outputs.principalId
    apiPrincipalId: api.outputs.principalId
  }
}
module roles './modules/role-assignments.bicep' = {
  name: 'waglwaglagent-role-assignments'
  scope: rg
  params: {
    keyVaultId: kv.outputs.id
    acrId: acr.outputs.id
    deployIdentityPrincipalId: identity.outputs.principalId
    deployerObjectId: deployerObjectId
    webPrincipalId: web.outputs.principalId
    apiPrincipalId: api.outputs.principalId
    webId: web.outputs.id
    apiId: api.outputs.id
  }
}
module secrets './modules/secrets.bicep' = {
  name: 'waglwaglagent-secrets'
  scope: rg
  dependsOn: [roles, redis]
  params: {
    kvName: kvName
    redisName: redisName
    postgresFqdn: pg.outputs.fqdn
    postgresAdminPassword: postgresAdminPassword
    waglInternalSecret: waglInternalSecret
    waglEncryptionKey: waglEncryptionKey
    authSecret: authSecret
    authGithubId: authGithubId
    authGithubSecret: authGithubSecret
    copilotClientId: copilotClientId
    copilotClientSecret: copilotClientSecret
  }
}
module diagnostics './modules/diagnostics.bicep' = if (enableDiagnostics) {
  name: 'waglwaglagent-diagnostics'
  scope: rg
  params: { webId: web.outputs.id, apiId: api.outputs.id, workspaceId: logs.outputs.id }
}

output resourceGroupName string = rg.name
output webUrl string = 'https://${web.outputs.defaultHostName}'
output apiUrl string = 'https://${api.outputs.defaultHostName}'
output webOutboundIpAddresses string = web.outputs.outboundIpAddresses
output apiOutboundIpAddresses string = api.outputs.outboundIpAddresses
output registryLoginServer string = acr.outputs.loginServer
output deploymentClientId string = identity.outputs.clientId
output keyVaultName string = kvName
output postgresFqdn string = pg.outputs.fqdn
