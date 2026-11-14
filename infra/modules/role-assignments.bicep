param keyVaultId string
param acrId string
param deployIdentityPrincipalId string
param deployerObjectId string
param webPrincipalId string
param apiPrincipalId string
param webId string
param apiId string
var kvSecretsOfficer = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var kvSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var acrPush = '8311e382-0749-4cb8-b61a-304f252e45ec'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var websiteContributor = 'de139f84-1756-47ae-9be6-808fbbe84772'
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: last(split(keyVaultId, '/')) }
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: last(split(acrId, '/')) }
resource web 'Microsoft.Web/sites@2024-11-01' existing = { name: last(split(webId, '/')) }
resource api 'Microsoft.Web/sites@2024-11-01' existing = { name: last(split(apiId, '/')) }
resource deployerKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultId, deployerObjectId, kvSecretsOfficer)
  scope: keyVault
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsOfficer), principalId: deployerObjectId, principalType: 'User' }
}
resource runtimeWebKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultId, webPrincipalId, kvSecretsUser)
  scope: keyVault
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUser), principalId: webPrincipalId, principalType: 'ServicePrincipal' }
}
resource runtimeApiKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultId, apiPrincipalId, kvSecretsUser)
  scope: keyVault
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUser), principalId: apiPrincipalId, principalType: 'ServicePrincipal' }
}
resource deployAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acrId, deployIdentityPrincipalId, acrPush)
  scope: acr
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPush), principalId: deployIdentityPrincipalId, principalType: 'ServicePrincipal' }
}
resource runtimeWebAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acrId, webPrincipalId, acrPull)
  scope: acr
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull), principalId: webPrincipalId, principalType: 'ServicePrincipal' }
}
resource runtimeApiAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acrId, apiPrincipalId, acrPull)
  scope: acr
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull), principalId: apiPrincipalId, principalType: 'ServicePrincipal' }
}
resource deployWeb 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(webId, deployIdentityPrincipalId, websiteContributor)
  scope: web
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', websiteContributor), principalId: deployIdentityPrincipalId, principalType: 'ServicePrincipal' }
}
resource deployApi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(apiId, deployIdentityPrincipalId, websiteContributor)
  scope: api
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', websiteContributor), principalId: deployIdentityPrincipalId, principalType: 'ServicePrincipal' }
}
