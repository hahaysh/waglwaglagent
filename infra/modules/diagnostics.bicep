param webId string
param apiId string
param workspaceId string
resource web 'Microsoft.Web/sites@2024-11-01' existing = { name: last(split(webId, '/')) }
resource api 'Microsoft.Web/sites@2024-11-01' existing = { name: last(split(apiId, '/')) }
resource webDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'waglwaglagent-diagnostics'
  scope: web
  properties: {
    workspaceId: workspaceId
    logs: [{ category: 'AppServiceHTTPLogs', enabled: true }, { category: 'AppServiceConsoleLogs', enabled: true }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}
resource apiDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'waglwaglagent-diagnostics'
  scope: api
  properties: {
    workspaceId: workspaceId
    logs: [{ category: 'AppServiceHTTPLogs', enabled: true }, { category: 'AppServiceConsoleLogs', enabled: true }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}
