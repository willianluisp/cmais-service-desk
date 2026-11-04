# Disposable fake data only. Compatible with Windows PowerShell 5.1 and PS7.
$ErrorActionPreference = 'Stop'
$scriptPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\scripts\Configure-IsolatedMicrosoft.ps1'))
$tokens = $null; $parseErrors = $null
[void][Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Script syntax validation failed.' }
$originalLocalAppData = $env:LOCALAPPDATA
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CmaisMicrosoftAclTest_' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($testRoot)
$global:CmaisAclTestState = @{Mode='pass'; PromptCount=0; FakeSecret=$null}
$global:CmaisAclTestState.FakeSecret = 'FAKE-ONLY-not-a-Microsoft-secret'
function Set-Acl {
    [CmdletBinding()]param([string]$LiteralPath, [object]$AclObject)
    if ($global:CmaisAclTestState.Mode -eq 'throw') { throw 'Simulated ACL failure.' }
    if ($global:CmaisAclTestState.Mode -eq 'filethrow' -and $LiteralPath.EndsWith('microsoft.env')) { throw 'Simulated file ACL failure.' }
    if ($global:CmaisAclTestState.Mode -eq 'privilege') { throw [Security.AccessControl.PrivilegeNotHeldException]::new('SeSecurityPrivilege') }
    if ($global:CmaisAclTestState.Mode -eq 'noop') { return }
    Microsoft.PowerShell.Security\Set-Acl -LiteralPath $LiteralPath -AclObject $AclObject -ErrorAction Stop
}
function Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    $global:CmaisAclTestState.PromptCount++
    if (-not $AsSecureString) { throw 'Credential prompt must hide input.' }
    return ConvertTo-SecureString $global:CmaisAclTestState.FakeSecret -AsPlainText -Force
}
function Assert-PrivateAcl([string]$Path) {
    $acl = Microsoft.PowerShell.Security\Get-Acl -LiteralPath $Path
    $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    $allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18')
    if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 2) { throw 'Expected protected ACL with exactly two rules.' }
    foreach ($rule in $rules) {
        if ($rule.IdentityReference.Value -notin $allowed -or $rule.IsInherited -or
            $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl') { throw 'Unexpected ACL rule.' }
    }
}
function New-TestCase([string]$Name) {
    $env:LOCALAPPDATA = Join-Path $testRoot $Name
    $directory = Join-Path $env:LOCALAPPDATA 'CmaisServiceDesk\isolated'
    [void][IO.Directory]::CreateDirectory($directory)
    $file = Join-Path $directory 'microsoft.env'
    [IO.File]::WriteAllText($file, "GRAPH_CLIENT_SECRET=old-fake`nPLANNER_ENABLED=false`nEMAIL_ENABLED=false`nKEEP_VALUE=preserve-me`n")
    return $file
}
try {
    $file = New-TestCase 'success'
    $output = @(& $scriptPath)
    if (($output -join "`n") -notlike '*Client Secret presente: SIM*' -or
        -not (($output -join "`n").Contains($file))) { throw 'Output must identify the storage path and presence without revealing the value.' }
    if ($global:CmaisAclTestState.PromptCount -ne 1) { throw 'Expected one hidden prompt.' }
    Assert-PrivateAcl (Split-Path -Parent $file); Assert-PrivateAcl $file
    $content = [IO.File]::ReadAllText($file)
    foreach ($expected in @(('GRAPH_CLIENT_SECRET=' + $global:CmaisAclTestState.FakeSecret), 'KEEP_VALUE=preserve-me', 'PLANNER_ENABLED=false', 'EMAIL_ENABLED=false')) {
        if (-not $content.Contains($expected)) { throw 'Configuration not preserved.' }
    }
    $key = @($content.Split("`n") | Where-Object { $_.StartsWith('GRAPH_TOKEN_ENCRYPTION_KEY=') })[0]
    if (($output -join "`n").Contains($global:CmaisAclTestState.FakeSecret) -or ($output -join "`n").Contains($key)) { throw 'Output exposed fake credentials.' }
    try { & $scriptPath -InitializeOnly | Out-Null } catch {
        if ($_.Exception.InnerException) { Write-Output ('ACL diagnostic: ' + $_.Exception.InnerException.Message) }
        throw
    }
    if ($global:CmaisAclTestState.PromptCount -ne 1 -or -not ([IO.File]::ReadAllText($file)).Contains($key)) { throw 'InitializeOnly changed the key or prompted.' }
    Write-Output 'PASS: PS syntax, private folder/file ACL, hidden input, preservation, InitializeOnly, safe output.'
    $global:CmaisAclTestState.Mode = 'privilege'
    & $scriptPath -InitializeOnly | Out-Null
    Assert-PrivateAcl $file
    Write-Output 'PASS: DACL-only fallback for SeSecurityPrivilege; ACL still verified.'
    foreach ($mode in @('throw', 'noop', 'filethrow')) {
        $file = New-TestCase $mode; $before = [IO.File]::ReadAllText($file)
        $global:CmaisAclTestState.PromptCount = 0; $global:CmaisAclTestState.Mode = $mode; $caught = $false
        try { & $scriptPath | Out-Null } catch { $caught = $true }
        if (-not $caught -or $global:CmaisAclTestState.PromptCount -ne 0 -or [IO.File]::ReadAllText($file) -ne $before) { throw 'ACL failure did not stop before prompt/write.' }
        Write-Output ('PASS: ACL ' + $mode + ' failure stops before prompt/write.')
    }
    $global:CmaisAclTestState.Mode = 'pass'
    $file = New-TestCase 'fresh'
    Remove-Item -LiteralPath $file -Force
    $ownerBefore = (Microsoft.PowerShell.Security\Get-Acl -LiteralPath (Split-Path -Parent $file)).Owner
    $global:CmaisAclTestState.PromptCount = 0
    $freshOutput = @(& $scriptPath -InitializeOnly)
    if (($freshOutput -join "`n") -notlike '*Client Secret presente: NAO*') { throw 'Fresh initialization must not claim a secret is configured.' }
    Assert-PrivateAcl $file
    Assert-PrivateAcl (Split-Path -Parent $file)
    if ($global:CmaisAclTestState.PromptCount -ne 0 -or
        (Microsoft.PowerShell.Security\Get-Acl -LiteralPath (Split-Path -Parent $file)).Owner -ne $ownerBefore) {
        throw 'Initialization must preserve owner and never prompt.'
    }
    Write-Output 'PASS: fresh initialization, no prompt, owner preserved and private ACL.'
    $file = New-TestCase 'invalid-input'
    $before = [IO.File]::ReadAllText($file)
    $global:CmaisAclTestState.FakeSecret = "FAKE`nINVALID"
    $caught = $false
    try { & $scriptPath | Out-Null } catch { $caught = $true }
    if (-not $caught -or [IO.File]::ReadAllText($file) -ne $before) { throw 'Invalid input must not replace configuration.' }
    Write-Output 'PASS: invalid multiline input stops without replacing configuration.'
    $file = New-TestCase 'short-input'
    $before = [IO.File]::ReadAllText($file)
    $global:CmaisAclTestState.FakeSecret = '*'
    $caught = $false
    try { & $scriptPath | Out-Null } catch { $caught = $true }
    if (-not $caught -or [IO.File]::ReadAllText($file) -ne $before) { throw 'Short input must not replace configuration.' }
    Write-Output 'PASS: implausibly short secret stops without replacing configuration.'
} finally {
    $env:LOCALAPPDATA = $originalLocalAppData; $global:CmaisAclTestState.Mode = 'pass'; $global:CmaisAclTestState.FakeSecret = $null
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolved) -notmatch '^CmaisMicrosoftAclTest_[0-9a-f]{32}$') { throw 'Refusing unsafe test cleanup.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
    Remove-Variable -Name CmaisAclTestState -Scope Global -ErrorAction SilentlyContinue
}
