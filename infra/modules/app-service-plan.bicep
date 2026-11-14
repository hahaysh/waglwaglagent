param name string
param location string
param tags object
resource plan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: name
  location: location
  tags: tags
  kind: 'linux'
  properties: { reserved: true }
  sku: { name: 'B2', tier: 'Basic', size: 'B2', family: 'B', capacity: 1 }
}
output id string = plan.id
