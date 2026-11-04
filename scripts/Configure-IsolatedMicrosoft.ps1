param([switch]$InitializeOnly)

$ErrorActionPreference = 'Stop'

function Assert-PrivateMicrosoftAcl {
    param([string]$LiteralPath, [bool]$IsDirectory)
    $actual = Get-Acl -LiteralPath $LiteralPath -ErrorAction Stop
    $rules = @($actual.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if (-not $actual.AreAccessRulesProtected -or $rules.Count -ne 2) {
        throw 'ACL privada nao confirmada. Operacao interrompida antes de gravar credenciais.'
    }
    $seen = @{}
    foreach ($rule in $rules) {
        $sid = $rule.IdentityReference.Value
        $expectedInheritance = [Security.AccessControl.InheritanceFlags]::None
        if ($IsDirectory) { $expectedInheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' }
        if ($sid -notin @($identity.Value, 'S-1-5-18') -or $seen.ContainsKey($sid) -or
            $rule.IsInherited -or $rule.AccessControlType -ne 'Allow' -or
            $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or
            $rule.InheritanceFlags -ne $expectedInheritance -or
            $rule.PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None) {
            throw 'Permissoes inesperadas no armazenamento privado. Operacao interrompida.'
        }
        $seen[$sid] = $true
    }
}

function Protect-PrivateMicrosoftPath {
    param([string]$LiteralPath, [bool]$IsDirectory)
    try {
        # Build only the DACL. Reusing the complete Get-Acl object can mark
        # audit/owner sections for writing and require SeSecurityPrivilege.
        # A fresh access descriptor leaves owner, group and auditing untouched.
        if ($IsDirectory) {
            $acl = [Security.AccessControl.DirectorySecurity]::new()
        } else {
            $acl = [Security.AccessControl.FileSecurity]::new()
        }
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($sid in @($identity, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
            if ($IsDirectory) {
                $rule = [Security.AccessControl.FileSystemAccessRule]::new(
                    $sid, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow'
                )
            } else {
                $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'Allow')
            }
            $acl.AddAccessRule($rule)
        }
        try {
            Set-Acl -LiteralPath $LiteralPath -AclObject $acl -ErrorAction Stop
        } catch {
            # Some FileSystem providers attempt to write the audit section even
            # for a DACL-only descriptor. Fall back ONLY for that specific
            # privilege error, using the access-only .NET persistence method.
            $cause = $_.Exception
            while ($cause -and -not ($cause -is [Security.AccessControl.PrivilegeNotHeldException])) {
                $cause = $cause.InnerException
            }
            if (-not $cause -or $cause.PrivilegeName -ne 'SeSecurityPrivilege') { throw }
            if ($PSVersionTable.PSVersion.Major -lt 6) {
                if ($IsDirectory) {
                    [IO.DirectoryInfo]::new($LiteralPath).SetAccessControl($acl)
                } else {
                    [IO.FileInfo]::new($LiteralPath).SetAccessControl($acl)
                }
            } elseif ($IsDirectory) {
                [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($LiteralPath), $acl)
            } else {
                [IO.FileSystemAclExtensions]::SetAccessControl([IO.FileInfo]::new($LiteralPath), $acl)
            }
        }
        Assert-PrivateMicrosoftAcl -LiteralPath $LiteralPath -IsDirectory $IsDirectory
    } catch {
        throw [InvalidOperationException]::new('Nao foi possivel aplicar e confirmar a protecao do armazenamento local. Nenhuma credencial sera gravada.', $_.Exception)
    }
}

# Local machine storage, outside the repository and OneDrive. Never emit values.
$secretDirectory = Join-Path $env:LOCALAPPDATA 'CmaisServiceDesk\isolated'
$secretFile = Join-Path $secretDirectory 'microsoft.env'
# Refuse redirected storage (including junctions) and accidental project/cloud paths.
$projectPrefix = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\') + '\'
$candidate = [IO.Path]::GetFullPath($secretDirectory)
if ($candidate.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    $candidate -match '(?i)(^|[\\/])OneDrive([^\\/]*)?([\\/]|$)') {
    throw 'O armazenamento de credenciais deve ficar fora do projeto e do OneDrive.'
}
$candidate = [IO.Path]::GetFullPath($secretFile)
while ($candidate) {
    if (Test-Path -LiteralPath $candidate) {
        if ((Get-Item -LiteralPath $candidate -Force -ErrorAction Stop).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Links e junctions nao sao permitidos no armazenamento de credenciais.'
        }
    }
    $candidate = [IO.Path]::GetDirectoryName($candidate)
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
[void][IO.Directory]::CreateDirectory($secretDirectory)
Protect-PrivateMicrosoftPath -LiteralPath $secretDirectory -IsDirectory $true
if (-not (Test-Path -LiteralPath $secretFile)) {
    $emptyFile = [IO.File]::Create($secretFile)
    $emptyFile.Dispose()
}
# Secure existing files before reading or replacing any credential content.
Protect-PrivateMicrosoftPath -LiteralPath $secretFile -IsDirectory $false

$values = [ordered]@{}
if (Test-Path -LiteralPath $secretFile) {
    foreach ($line in [IO.File]::ReadAllLines($secretFile)) {
        $separator = $line.IndexOf('=')
        if ($separator -gt 0) {
            $values[$line.Substring(0, $separator)] = $line.Substring($separator + 1)
        }
    }
}
$values['GRAPH_TENANT_ID'] = '9063737b-9cf5-48b0-919f-d4b505baed97'
$values['GRAPH_CLIENT_ID'] = '360a498a-77f9-4046-a0aa-d8c0bab7dfd1'
$values['GRAPH_AUTH_STRATEGY'] = 'delegated'
if (-not $values['GRAPH_TOKEN_ENCRYPTION_KEY']) {
    $randomBytes = [byte[]]::new(32)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
    $values['GRAPH_TOKEN_ENCRYPTION_KEY'] = [Convert]::ToBase64String($randomBytes).Replace('+', '-').Replace('/', '_')
    [Array]::Clear($randomBytes, 0, $randomBytes.Length)
}
if (-not $values.Contains('GRAPH_CLIENT_SECRET')) { $values['GRAPH_CLIENT_SECRET'] = '' }
$values['GRAPH_PLAN_ID'] = 'OYsA-pTkhUm5MuVZj6PxK2UAHdk5'
if (-not $values.Contains('PLANNER_BUCKET_ENTRADA_ID')) { $values['PLANNER_BUCKET_ENTRADA_ID'] = '' }
if (-not $values.Contains('PLANNER_BUCKET_EM_ANDAMENTO_ID')) { $values['PLANNER_BUCKET_EM_ANDAMENTO_ID'] = '' }
if (-not $values.Contains('PLANNER_BUCKET_CONCLUIDO_ID')) { $values['PLANNER_BUCKET_CONCLUIDO_ID'] = '' }

if (-not $InitializeOnly) {
    $secureValue = Read-Host 'Cole o VALOR do client secret Microsoft (entrada oculta)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        $plainValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($plainValue) -or $plainValue.Length -lt 16 -or
            $plainValue -ne $plainValue.Trim() -or $plainValue.Contains("`n") -or $plainValue.Contains("`r")) {
            throw 'Valor invalido ou curto demais. Cole o campo Value do segredo; nada foi gravado.'
        }
        $values['GRAPH_CLIENT_SECRET'] = $plainValue
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $plainValue = $null
        $secureValue.Dispose()
    }
}
# Compose env_file format: raw. No interpolation, quoting or shell expansion.
Assert-PrivateMicrosoftAcl -LiteralPath $secretDirectory -IsDirectory $true
Assert-PrivateMicrosoftAcl -LiteralPath $secretFile -IsDirectory $false
[IO.File]::WriteAllLines($secretFile, @($values.GetEnumerator() | ForEach-Object { $_.Key + '=' + $_.Value }), [Text.UTF8Encoding]::new($false))
Assert-PrivateMicrosoftAcl -LiteralPath $secretFile -IsDirectory $false
$secretPresent = -not [string]::IsNullOrWhiteSpace($values['GRAPH_CLIENT_SECRET'])
$values.Clear()
Write-Output ('Arquivo protegido utilizado: ' + $secretFile)
if ($secretPresent) {
    Write-Output 'Client Secret presente: SIM'
} else {
    Write-Output 'Client Secret presente: NAO. Execute sem -InitializeOnly para inserir o valor na entrada oculta.'
}
Write-Output 'Nenhum valor secreto foi exibido. Flags nao foram habilitadas.'
