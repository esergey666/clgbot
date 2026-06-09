$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envPath = Join-Path $projectRoot ".env"

Write-Host "This will update:" $envPath
$token = Read-Host "Paste the new Telegram bot token"
$token = $token.Trim().Trim('"').Trim("'")

if ($token -notmatch '^\d{8,12}:[A-Za-z0-9_-]{30,}$') {
    Write-Host "Token format looks wrong. It should look like 1234567890:AA..." -ForegroundColor Red
    exit 1
}

$admins = ""
if (Test-Path $envPath) {
    $existing = Get-Content -LiteralPath $envPath
    foreach ($line in $existing) {
        if ($line -match '^\s*(admins|ADMIN_IDS)\s*=\s*(.+)\s*$') {
            $admins = $matches[2].Trim()
            break
        }
    }
}

if (-not $admins) {
    $admins = Read-Host "Paste your Telegram admin id"
}

$content = @(
    "bot=$token",
    "admins=$admins"
)

Set-Content -LiteralPath $envPath -Value $content -Encoding ascii

$secret = ($token -split ":", 2)[1]
$preview = ($token -split ":", 2)[0] + ":" + $secret.Substring(0, [Math]::Min(4, $secret.Length)) + "..." + $secret.Substring([Math]::Max(0, $secret.Length - 4))
Write-Host "Saved token preview:" $preview -ForegroundColor Green
Write-Host "Now run check_bot_token.bat"
