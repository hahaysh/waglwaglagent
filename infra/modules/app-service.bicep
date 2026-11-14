param name string
param location string
param tags object
param planId string
param component string
param acrLoginServer string
param imageTag string
param usePlaceholderImages bool
param healthPath string
resource app 'Microsoft.Web/sites@2024-11-01' = {
  name: name
  location: location
  tags: tags
  kind: 'app,linux,container'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: planId
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: usePlaceholderImages
        ? 'DOCKER|mcr.microsoft.com/appsvc/staticsite@sha256:23edadf1c0aca901e8532eb145432f49d4e27a20bef92c48710bb4a81142d4ee'
        : 'DOCKER|${acrLoginServer}/waglwaglagent-${component}:${imageTag}'
      alwaysOn: true
      healthCheckPath: usePlaceholderImages ? '/' : healthPath
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      acrUseManagedIdentityCreds: true
    }
  }
}
resource scm 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: app
  name: 'scm'
  properties: { allow: false }
}
resource ftp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: app
  name: 'ftp'
  properties: { allow: false }
}
output id string = app.id
output principalId string = app.identity.principalId
output defaultHostName string = app.properties.defaultHostName
output outboundIpAddresses string = app.properties.possibleOutboundIpAddresses
