param name string
param location string
param tags object
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: name
  location: location
  tags: tags
}
resource federation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2024-11-30' = {
  parent: identity
  name: 'waglwaglagent-github-main-azure-pilot'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:hahaysh/waglwaglagent:environment:azure-pilot'
    audiences: ['api://AzureADTokenExchange']
  }
}
output id string = identity.id
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
