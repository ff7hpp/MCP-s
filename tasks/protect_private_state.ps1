param([string]$Root = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath $Root).Path
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'pyproject.toml'))) {
    throw 'PRIVATE_ACL_ROOT_INVALID: expected project directory'
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed = @($identity.Value, 'S-1-5-18', 'S-1-5-32-544')
$browserCapabilities = @(
    'S-1-15-3-1024-395641907-2340533657-1796656376-1949871151-3167452726-3934347287-2361051074-3061173417',
    'S-1-15-3-1024-1528657515-1944437972-2795272136-1227674495-293963776-353393192-4060142787-1908764039')
$roots = @('data', 'downloads', 'browser-profile', 'ewi-browser-profile', 'uzem-browser-profile')
$original = @()
function Invoke-PrivateAcl([string[]]$Arguments) {
    # icacls changes DACLs without requiring access to mandatory integrity labels.
    & icacls.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'PRIVATE_ACL_UPDATE_FAILED' }
}
foreach ($name in $roots) {
    $path = Join-Path $projectRoot $name
    if (!(Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Path $path | Out-Null }
    $items = @(Get-Item -LiteralPath $path) + @(Get-ChildItem -LiteralPath $path -Recurse -Force)
    foreach ($item in $items) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'PRIVATE_ACL_LINK_REJECTED: inspect private directory links first'
        }
        $acl = Get-Acl -LiteralPath $item.FullName
        if ($item.FullName -ne $path -and $acl.AreAccessRulesProtected) {
            throw 'PRIVATE_ACL_CUSTOM_RULES: inspect explicit child permissions first'
        }
        $original += [pscustomobject]@{ Path = $item.FullName; Sddl = $acl.Sddl }
    }
}

# Data is protected first so the reversible ACL snapshot is private from creation.
foreach ($name in $roots) {
    $path = Join-Path $projectRoot $name
    Invoke-PrivateAcl @($path, '/inheritance:r', '/grant:r', "*$($identity.Value):(OI)(CI)F", '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F')
    if ($name -eq 'data') {
        $backup = Join-Path $path ('private-acl-backup-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff') + '.json')
        $original | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $backup -Encoding UTF8
        $backups = @(Get-ChildItem -LiteralPath $path -Filter 'private-acl-backup-*.json' -File | Sort-Object Name)
        if ($backups.Count -gt 5) {
            # Keep the initial rollback snapshot and the newest four generations.
            foreach ($old in $backups[1..($backups.Count - 5)]) {
                if ($old.DirectoryName -ne $path) { throw 'PRIVATE_ACL_BACKUP_OUTSIDE_DATA' }
                Remove-Item -LiteralPath $old.FullName
            }
        }
    }
}

foreach ($name in $roots) {
    $path = Join-Path $projectRoot $name
    $items = @(Get-Item -LiteralPath $path) + @(Get-ChildItem -LiteralPath $path -Recurse -Force)
    foreach ($item in $items) {
        $acl = Get-Acl -LiteralPath $item.FullName
        $permitted = $allowed
        if ($name -like '*browser-profile' -and $item.FullName -ne $path) {
            # Chromium's two existing sandbox capabilities are not interactive user accounts.
            $permitted += $browserCapabilities
        }
        foreach ($rule in @($acl.Access | Where-Object { !$_.IsInherited -and $_.AccessControlType -eq 'Allow' })) {
            $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            if ($sid -notin $permitted) {
                Invoke-PrivateAcl @($item.FullName, '/remove:g', "*$sid")
            }
        }
        $acl = Get-Acl -LiteralPath $item.FullName
        $rules = $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
        if (@($rules | Where-Object { $_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -notin $permitted }).Count) {
            throw 'PRIVATE_ACL_VERIFICATION_FAILED: unexpected access rule remains'
        }
    }
}
Write-Output 'PRIVATE_ACL_VERIFIED: private user access restricted; existing Chromium sandbox capabilities retained; original ACL metadata in data/'
