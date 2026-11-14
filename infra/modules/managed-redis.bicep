param name string
param location string
param tags object
resource cluster 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Balanced_B0' }
  properties: { highAvailability: 'Disabled', minimumTlsVersion: '1.2', publicNetworkAccess: 'Enabled' }
}
resource database 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: cluster
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    clusteringPolicy: 'NoCluster'
    evictionPolicy: 'NoEviction'
    port: 10000
    accessKeysAuthentication: 'Enabled'
  }
}
output id string = cluster.id
output hostName string = cluster.properties.hostName
