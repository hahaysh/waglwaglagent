param keyVaultId string
param deployerObjectId string

var secretsOfficer = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: last(split(keyVaultId, '/'))
}
resource access 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultId, deployerObjectId, secretsOfficer)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficer)
    principalId: deployerObjectId
    principalType: 'User'
  }
}
