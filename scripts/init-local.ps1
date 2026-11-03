param([ValidateRange(1024, 65535)][int]$Port = 3000)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$apiEnv = Join-Path $root ".env"
$webEnv = Join-Path $root "apps/web/.env.local"
if ((Test-Path $apiEnv) -or (Test-Path $webEnv)) {
    throw "Environment files already exist. They will not be overwritten."
}

function New-Secret([switch]$Hex) {
    $bytes = New-Object byte[] 32
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) } finally { $random.Dispose() }
    if ($Hex) { return [BitConverter]::ToString($bytes).Replace("-", "").ToLowerInvariant() }
    return [Convert]::ToBase64String($bytes)
}

$internalSecret = New-Secret
$encryptionKey = New-Secret
$authSecret = New-Secret
$databasePassword = New-Secret -Hex
$apiLines = @(
    "WAGL_ENVIRONMENT=local",
    "WAGL_DATABASE_URL=sqlite:///./.local/wagl.db",
    "WAGL_REDIS_URL=",
    "WAGL_INTERNAL_SECRET=$internalSecret",
    "WAGL_ENCRYPTION_KEY=$encryptionKey",
    "WAGL_POSTGRES_PASSWORD=$databasePassword",
    "LITELLM_TELEMETRY=False"
)
$webLines = @(
    "AUTH_SECRET=$authSecret",
    "AUTH_GITHUB_ID=",
    "AUTH_GITHUB_SECRET=",
    "AUTH_TRUST_HOST=true",
    "AUTH_URL=http://localhost:$Port",
    "WAGL_INTERNAL_SECRET=$internalSecret",
    "WAGL_API_URL=http://127.0.0.1:8000",
    "WAGL_PUBLIC_URL=http://localhost:$Port"
)
[IO.File]::WriteAllLines($apiEnv, $apiLines)
[IO.File]::WriteAllLines($webEnv, $webLines)
Write-Output "Local configuration created. Secret values were not printed. Configure GitHub OAuth in apps/web/.env.local."