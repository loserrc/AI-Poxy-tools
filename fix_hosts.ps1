# Trae-Poxy Hosts File Fix Script
# Run this script as Administrator

Write-Host "================================" -ForegroundColor Cyan
Write-Host "Trae-Poxy Hosts File Fix" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please:" -ForegroundColor Yellow
    Write-Host "1. Right-click on this script" -ForegroundColor Yellow
    Write-Host "2. Select 'Run with PowerShell as Administrator'" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Adding Trae domains to hosts file..." -ForegroundColor Green
Write-Host ""

$hostsPath = "C:\Windows\System32\drivers\etc\hosts"
$domains = @(
    "127.0.0.1 trae-api-sg.mchost.guru",
    "127.0.0.1 trae-api-us.mchost.guru",
    "127.0.0.1 api22-normal-alisg.mchost.guru",
    "127.0.0.1 api22-normal-useast1a.mchost.guru",
    "127.0.0.1 api16-normal-alisg.mchost.guru",
    "127.0.0.1 api16-normal-useast1a.mchost.guru",
    "127.0.0.1 api5-normal-alisg.mchost.guru",
    "127.0.0.1 api5-normal-useast1a.mchost.guru"
)

# Read existing hosts file
$hostsContent = Get-Content $hostsPath -Raw

# Add domains if they don't exist
$added = 0
foreach ($domain in $domains) {
    if ($hostsContent -notmatch [regex]::Escape($domain)) {
        Add-Content -Path $hostsPath -Value $domain
        Write-Host "Added: $domain" -ForegroundColor Green
        $added++
    } else {
        Write-Host "Already exists: $domain" -ForegroundColor Yellow
    }
}

Write-Host ""
if ($added -gt 0) {
    Write-Host "Successfully added $added domain(s) to hosts file!" -ForegroundColor Green
} else {
    Write-Host "All domains already exist in hosts file." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Flushing DNS cache..." -ForegroundColor Green
ipconfig /flushdns | Out-Null
Write-Host "DNS cache flushed!" -ForegroundColor Green

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Restart your proxy UI application" -ForegroundColor Yellow
Write-Host "2. Restart Trae" -ForegroundColor Yellow
Write-Host "3. Send a test message in Trae" -ForegroundColor Yellow
Write-Host ""
Write-Host "If successful, you should see requests in the proxy log!" -ForegroundColor Green
Write-Host ""

Read-Host "Press Enter to exit"
