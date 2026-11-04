$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$enable = Join-Path $root 'scripts\Enable-IsolatedMicrosoftOAuth.ps1'
$tokens = $null; $parseErrors = $null
[void][Management.Automation.Language.Parser]::ParseFile($enable, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'PowerShell syntax error.' }
$previous = $env:LOCALAPPDATA
$temp = Join-Path ([IO.Path]::GetTempPath()) ('CmaisOAuthTest_' + [guid]::NewGuid().ToString('N'))
$env:LOCALAPPDATA = $temp
$global:CmaisOAuthTest = @{ Calls=0; Ups=0; BadSnapshot=$false; TestEnabled=$false }
function Read-Host { param([string]$Prompt,[switch]$AsSecureString) ConvertTo-SecureString 'FAKE_ONLY_FOR_LOCAL_TESTS' -AsPlainText -Force }
function docker {
    $global:LASTEXITCODE = 0
    $global:CmaisOAuthTest.Calls++
    if ($args -contains 'config') {
        return @{services=@{web=@{env_file=@(@{path=(Join-Path $env:LOCALAPPDATA 'CmaisServiceDesk\isolated\microsoft.env')})}}} | ConvertTo-Json -Depth 8 -Compress
    }
    if ($args -contains 'up') {
        if ($args -contains 'worker' -or $args -contains 'beat' -or $args[-1] -ne 'web' -or $args -notcontains '--no-deps') { throw 'Only isolated web may be recreated.' }
        $global:CmaisOAuthTest.Ups++
        $global:CmaisOAuthTest.TestEnabled = $args -contains 'compose.planner-test.isolated.yaml'
        return
    }
    if ($args -contains 'exec') {
        $snapshot = 'unchanged'
        if ($global:CmaisOAuthTest.BadSnapshot -and $global:CmaisOAuthTest.Ups -eq 2) { $snapshot = 'changed' }
        return @{snapshot=@{test=$snapshot}; pending=0; test_attempts=0; oauth_enabled=($global:CmaisOAuthTest.Ups -eq 2); test_enabled=$global:CmaisOAuthTest.TestEnabled; container_secret_matches=$true} | ConvertTo-Json -Compress
    }
    throw 'Unexpected Docker command.'
}
try {
    & (Join-Path $root 'scripts\Configure-IsolatedMicrosoft.ps1') -InitializeOnly | Out-Null
    $caught = $false
    try { & $enable -ValidateOnly | Out-Null } catch { $caught = $true }
    if (-not $caught -or $global:CmaisOAuthTest.Calls -ne 0) { throw 'Empty secret must block before Docker.' }
    $privateFile = Join-Path $env:LOCALAPPDATA 'CmaisServiceDesk\isolated\microsoft.env'
    $shortContent = ([IO.File]::ReadAllText($privateFile) -replace 'GRAPH_CLIENT_SECRET=', 'GRAPH_CLIENT_SECRET=*')
    [IO.File]::WriteAllText($privateFile, $shortContent, [Text.UTF8Encoding]::new($false))
    $caught = $false
    try { & $enable -ValidateOnly | Out-Null } catch { $caught = $true }
    if (-not $caught -or $global:CmaisOAuthTest.Calls -ne 0) { throw 'Short secret must block before Docker.' }
    & (Join-Path $root 'scripts\Configure-IsolatedMicrosoft.ps1') | Out-Null
    & $enable -ValidateOnly | Out-Null
    if ($global:CmaisOAuthTest.Ups -ne 0) { throw 'ValidateOnly must not recreate any container.' }
    $output = @(& $enable)
    if ($global:CmaisOAuthTest.Ups -ne 2 -or ($output -join "`n") -notlike '*OAuth delegado habilitado*' -or
        ($output -join "`n").Contains('FAKE_ONLY_FOR_LOCAL_TESTS')) { throw 'Activation/output failed.' }
    $global:CmaisOAuthTest.Ups = 0; $global:CmaisOAuthTest.TestEnabled = $false
    $testOutput = @(& $enable -EnablePlannerTest)
    if ($global:CmaisOAuthTest.Ups -ne 2 -or -not $global:CmaisOAuthTest.TestEnabled -or
        ($testOutput -join "`n") -notlike '*Teste controlado do Planner habilitado*') { throw 'Controlled test activation failed.' }
    $global:CmaisOAuthTest.Ups = 0; $global:CmaisOAuthTest.BadSnapshot = $true
    $caught = $false
    try { & $enable | Out-Null } catch { $caught = $true }
    if (-not $caught -or $global:CmaisOAuthTest.Ups -ne 3) { throw 'Verification failure must roll back OAuth flags.' }
    Write-Output 'PASS: syntax, empty-secret block, read-only validation, web-only activation, protected data check, rollback, safe output (fake Docker only).'
} finally {
    $env:LOCALAPPDATA = $previous
    $full = [IO.Path]::GetFullPath($temp)
    $prefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $full.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $full) -notmatch '^CmaisOAuthTest_[0-9a-f]{32}$') { throw 'Unsafe cleanup rejected.' }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
    Remove-Variable -Name CmaisOAuthTest -Scope Global -ErrorAction SilentlyContinue
}
