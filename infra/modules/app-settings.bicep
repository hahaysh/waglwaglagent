param webName string
param apiName string
param appConfigurationEndpoint string
param acrLoginServer string
param usePlaceholderImages bool
resource webSettings 'Microsoft.Web/sites/config@2024-11-01' = {
  name: '${webName}/appsettings'
  properties: {
    WAGL_ENVIRONMENT: 'production'
    WAGL_APP_CONFIG_ENDPOINT: appConfigurationEndpoint
    WAGL_APP_CONFIG_LABEL: 'production-web'
    WEBSITES_PORT: usePlaceholderImages ? '80' : '3000'
    WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
    DOCKER_REGISTRY_SERVER_URL: 'https://${acrLoginServer}'
  }
}
resource apiSettings 'Microsoft.Web/sites/config@2024-11-01' = {
  name: '${apiName}/appsettings'
  properties: {
    WAGL_ENVIRONMENT: 'production'
    WAGL_APP_CONFIG_ENDPOINT: appConfigurationEndpoint
    WAGL_APP_CONFIG_LABEL: 'production-api'
    LITELLM_TELEMETRY: 'False'
    WEBSITES_PORT: usePlaceholderImages ? '80' : '8000'
    WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
    DOCKER_REGISTRY_SERVER_URL: 'https://${acrLoginServer}'
  }
}
