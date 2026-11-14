param name string
param location string
param tags object
param administratorLogin string
@secure()
param administratorLoginPassword string
param outboundIpRanges array = []
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '17'
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'waglwaglagent'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}
resource firewallRules 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = [for range in outboundIpRanges: {
  parent: postgres
  name: 'waglwaglagent-outbound-${replace(range, '.', '-')}'
  properties: { startIpAddress: range, endIpAddress: range }
}]
output id string = postgres.id
output fqdn string = postgres.properties.fullyQualifiedDomainName
