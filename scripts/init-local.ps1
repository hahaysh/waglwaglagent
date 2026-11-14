param(
    [Parameter(Mandatory = $true)][string]$TenantId,
    [string]$ConfigurationEndpoint = "https://waglwaglagent-config.azconfig.io"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$apiEnv = Join-Path $root ".env"
$webEnv = Join-Path $root "apps\web\.env.local"
if ((Test-Path $apiEnv) -or (Test-Path $webEnv)) {
    throw "Environment files already exist. They will not be overwritten."
}

if ($ConfigurationEndpoint -notmatch '^https://[a-zA-Z0-9-]+\.azconfig\.io/?$') {
    throw "A public Azure App Configuration HTTPS endpoint is required."
}
$common = @(
    "WAGL_ENVIRONMENT=local",
    "WAGL_APP_CONFIG_ENDPOINT=$ConfigurationEndpoint",
    "WAGL_AZURE_TENANT_ID=$TenantId"
)
[IO.File]::WriteAllLines($apiEnv, $common + "WAGL_APP_CONFIG_LABEL=local-api")
[IO.File]::WriteAllLines($webEnv, $common + "WAGL_APP_CONFIG_LABEL=local-web")
Write-Output "Bootstrap configuration created. Sign in with az login; settings and secrets must already exist in Azure."