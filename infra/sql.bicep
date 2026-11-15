targetScope = 'resourceGroup'

param location string = 'koreacentral'
param name string = 'waglwaglagent-sql'
param databaseName string = 'waglwaglagent-db'
param administratorObjectId string
param administratorName string
param apiName string = 'waglwaglagent-api'
param apiOutboundIpAddresses array

resource api 'Microsoft.Web/sites@2024-11-01' existing = {
  name: apiName
}
resource server 'Microsoft.Sql/servers@2023-08-01' = {
  name: name
  location: location
  tags: { application: 'waglwaglagent', environment: 'production' }
  properties: {
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      principalType: 'User'
      login: administratorName
      sid: administratorObjectId
      tenantId: subscription().tenantId
      azureADOnlyAuthentication: true
    }
  }
}
resource database 'Microsoft.Sql/servers/databases@2023-08-01' = {
  parent: server
  name: databaseName
  location: location
  sku: { name: 'Basic', tier: 'Basic', capacity: 5 }
  properties: {
    collation: 'Latin1_General_100_BIN2_UTF8'
    maxSizeBytes: 2147483648
    requestedBackupStorageRedundancy: 'Local'
    zoneRedundant: false
  }
}
resource backup 'Microsoft.Sql/servers/databases/backupShortTermRetentionPolicies@2023-08-01' = {
  parent: database
  name: 'default'
  properties: { retentionDays: 7 }
}
resource firewall 'Microsoft.Sql/servers/firewallRules@2023-08-01' = [
  for address in apiOutboundIpAddresses: {
    parent: server
    name: 'waglwaglagent-api-${replace(address, '.', '-')}'
    properties: { startIpAddress: address, endIpAddress: address }
  }
]
output sqlHost string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
output apiPrincipalId string = api.identity.principalId
