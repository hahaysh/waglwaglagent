targetScope = 'subscription'

param location string
param environmentName string
param sessionId string
param deployedBy string
param createdAt string
param deployerObjectId string

var tags = {
  application: 'waglwaglagent'
  'app-onboard-skill': 'true'
  'app-onboard-session-id': sessionId
  'created-at': createdAt
  environment: environmentName
  'deployed-by': deployedBy
}

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: 'waglwaglagent-6d0f-rg'
  location: location
  tags: tags
}

module vault './modules/key-vault.bicep' = {
  name: 'waglwaglagent-bootstrap-vault'
  scope: rg
  params: {
    name: 'waglwaglagent-6d0f-kv'
    location: location
    tags: tags
  }
}

module access './modules/bootstrap-access.bicep' = {
  name: 'waglwaglagent-bootstrap-access'
  scope: rg
  params: {
    keyVaultId: vault.outputs.id
    deployerObjectId: deployerObjectId
  }
}
