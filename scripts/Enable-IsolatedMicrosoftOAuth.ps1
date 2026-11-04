# Only delegated authorization in isolated 8010. Never starts workers or sends tasks.
param([switch]$ValidateOnly, [switch]$EnablePlannerTest)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$privateDirectory = Join-Path $env:LOCALAPPDATA 'CmaisServiceDesk\isolated'
$privateFile = Join-Path $privateDirectory 'microsoft.env'
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$values = @{}
$applied = $false
foreach ($path in @($privateDirectory, $privateFile)) {
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 2) { throw 'ACL privada nao confirmada. Nenhuma ativacao executada.' }
    foreach ($rule in $rules) {
        if ($rule.IdentityReference.Value -notin @($currentSid, 'S-1-5-18') -or $rule.IsInherited -or
            $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl') {
            throw 'Permissoes privadas invalidas. Nenhuma ativacao executada.'
        }
    }
}
try {
    foreach ($line in [IO.File]::ReadAllLines($privateFile)) {
        $separator = $line.IndexOf('=')
        if ($separator -gt 0) { $values[$line.Substring(0, $separator)] = $line.Substring($separator + 1) }
    }
    if ([string]::IsNullOrWhiteSpace($values['GRAPH_CLIENT_SECRET']) -or
        $values['GRAPH_CLIENT_SECRET'].Length -lt 16 -or
        $values['GRAPH_CLIENT_SECRET'] -ne $values['GRAPH_CLIENT_SECRET'].Trim()) {
        throw 'Client Secret ausente ou invalido no arquivo protegido. OAuth nao habilitado.'
    }
    if ($values['GRAPH_TENANT_ID'] -ne '9063737b-9cf5-48b0-919f-d4b505baed97' -or
        $values['GRAPH_CLIENT_ID'] -ne '360a498a-77f9-4046-a0aa-d8c0bab7dfd1' -or
        $values['GRAPH_AUTH_STRATEGY'] -ne 'delegated') { throw 'Identificacao/estrategia Microsoft divergente. OAuth nao habilitado.' }
    try {
        $keyBytes = [Convert]::FromBase64String($values['GRAPH_TOKEN_ENCRYPTION_KEY'].Replace('-', '+').Replace('_', '/'))
        if ($keyBytes.Length -ne 32) { throw 'Invalid key' }
    } catch { throw 'Chave de criptografia invalida. OAuth nao habilitado.' }
    finally { if ($keyBytes) { [Array]::Clear($keyBytes, 0, $keyBytes.Length) } }
    $nonce = [byte[]]::new(32)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($nonce) } finally { $rng.Dispose() }
    $hmac = [Security.Cryptography.HMACSHA256]::new($nonce)
    try {
        $payload = @{
            nonce = [Convert]::ToBase64String($nonce)
            secret_mac = [Convert]::ToBase64String($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($values['GRAPH_CLIENT_SECRET'])))
            key_mac = [Convert]::ToBase64String($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($values['GRAPH_TOKEN_ENCRYPTION_KEY'])))
            enable_test = [bool]$EnablePlannerTest
        } | ConvertTo-Json -Compress
    } finally { $hmac.Dispose(); [Array]::Clear($nonce, 0, $nonce.Length) }
    $values.Clear()
    Push-Location -LiteralPath $projectRoot
    try {
        # Capture config only in memory; never output environment values.
        $configText = & docker compose -f compose.isolated.yaml config --no-env-resolution --format json
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao validar caminhos do Compose.' }
        $config = ($configText -join "`n") | ConvertFrom-Json
        $paths = @($config.services.web.env_file | ForEach-Object { [IO.Path]::GetFullPath($_.path.Replace('/', '\')) })
        if ($paths -notcontains [IO.Path]::GetFullPath($privateFile)) { throw 'Docker e configurador usam arquivos diferentes. Nenhuma ativacao executada.' }
        $configText = $null; $config = $null
        if ($ValidateOnly) { Write-Output 'Pre-requisitos locais e caminho do Docker conferidos. Nenhum container alterado.'; return }
        $probeCode = @'
import django,json,sys,hashlib,hmac,base64
django.setup()
from django.conf import settings
from django.apps import apps
from django.db import transaction,connection
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from apps.planner_integration.delegated_oauth import redirect_uri,_fernet
from apps.planner_integration.admin_panel import panel
data=json.load(sys.stdin); nonce=base64.b64decode(data['nonce'])
def matches(value,mac): return hmac.compare_digest(base64.b64encode(hmac.new(nonce,value.encode(),hashlib.sha256).digest()).decode(),mac)
assert connection.vendor=='postgresql' and connection.settings_dict['NAME']=='service_desk'
assert settings.PORTAL_BASE_URL=='http://localhost:8010'
assert settings.GRAPH_CLIENT_SECRET and matches(settings.GRAPH_CLIENT_SECRET,data['secret_mac'])
assert matches(settings.GRAPH_TOKEN_ENCRYPTION_KEY,data['key_mac']); _fernet()
assert redirect_uri()=='http://localhost:8010/integracoes/microsoft/callback/'
assert settings.GRAPH_AUTH_STRATEGY=='delegated'
assert settings.GRAPH_TENANT_ID=='9063737b-9cf5-48b0-919f-d4b505baed97'
assert settings.GRAPH_CLIENT_ID=='360a498a-77f9-4046-a0aa-d8c0bab7dfd1'
assert not any(getattr(settings,flag,False) for flag in ('PLANNER_ENABLED','EMAIL_ENABLED','PLANNER_ATTACHMENTS_ENABLED','GRAPH_ATTACHMENTS_STORAGE_APPROVED','GRAPH_ATTACHMENT_SCOPE_ENABLED','LDAP_ENABLED'))
tables={}
with transaction.atomic():
 connection.cursor().execute('SET TRANSACTION READ ONLY')
 for name in ('auth.User','accounts.LocalAccount','accounts.UserProfile','accounts.AccountAudit','tickets.Ticket','tickets.TicketEvent','tickets.Attachment','planner_integration.MicrosoftGraphConnection','planner_integration.PlannerConfiguration','planner_integration.PlannerTaskProvisioning','planner_integration.AttachmentPublication','planner_integration.PlannerTestAttempt','notifications.NotificationOutbox'):
  model=apps.get_model(name); rows=list(model.objects.order_by(model._meta.pk.name).values()); tables[name]=hashlib.sha256(json.dumps(rows,default=str,sort_keys=True).encode()).hexdigest()
 user=get_user_model().objects.filter(is_active=True,groups__name='ADMIN_PORTAL').distinct().order_by('pk').first()
 assert user is not None, 'Exige administrador local ativo no grupo ADMIN_PORTAL'
 request=RequestFactory().get('/integracoes/',HTTP_HOST='localhost'); request.user=user; request.session={}
 response=panel(request); assert response.status_code==200
 pending=apps.get_model('planner_integration.PlannerTaskProvisioning').objects.filter(state='PENDING').count()
 test_attempts=apps.get_model('planner_integration.PlannerTestAttempt').objects.count()
 if data.get('enable_test'):
  config=apps.get_model('planner_integration.PlannerConfiguration').objects.get(plan_id='OYsA-pTkhUm5MuVZj6PxK2UAHdk5')
  observed={row['id']:row['name'] for row in config.buckets}
  expected={'PLANNER_INTAKE_BUCKET_ID':'Tarefas pendentes','PLANNER_IN_PROGRESS_BUCKET_ID':'Desenvolvendo','PLANNER_COMPLETED_BUCKET_ID':'Finalizada'}
  assert all(observed.get(config.bucket_mapping.get(key))==name for key,name in expected.items())
  assert apps.get_model('planner_integration.MicrosoftGraphConnection').objects.filter(is_active=True,tenant_id=settings.GRAPH_TENANT_ID).exists()
print(json.dumps({'snapshot':tables,'pending':pending,'test_attempts':test_attempts,'oauth_enabled':settings.MICROSOFT_GRAPH_APPROVED and settings.GRAPH_DELEGATED_OAUTH_ENABLED,'test_enabled':settings.PLANNER_TEST_ENABLED,'container_secret_matches':True}))
'@
        # Load the current local protected file first, while all Microsoft flags are off.
        & docker compose -f compose.isolated.yaml up -d --no-deps --force-recreate web
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel recarregar o web isolado.' }
        $beforeText = $payload | & docker compose -f compose.isolated.yaml exec -T web python -c $probeCode
        if ($LASTEXITCODE -ne 0) { throw 'Configuracao recebida pelo Django nao confere. OAuth nao habilitado.' }
        $before = ($beforeText -join "`n") | ConvertFrom-Json
        if ($before.oauth_enabled -or $before.test_enabled) { throw 'Estado inicial divergente. OAuth nao habilitado.' }
        $applied = $true
        $composeFiles = @('-f', 'compose.isolated.yaml', '-f', 'compose.oauth.isolated.yaml')
        if ($EnablePlannerTest) { $composeFiles += @('-f', 'compose.planner-test.isolated.yaml') }
        & docker compose @composeFiles up -d --no-deps web
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao aplicar OAuth isolado.' }
        $afterText = $payload | & docker compose -f compose.isolated.yaml exec -T web python -c $probeCode
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao confirmar OAuth isolado.' }
        $after = ($afterText -join "`n") | ConvertFrom-Json
        if (-not $after.oauth_enabled -or [bool]$after.test_enabled -ne [bool]$EnablePlannerTest -or
            $after.pending -ne $before.pending -or $after.test_attempts -ne $before.test_attempts -or
            ($before.snapshot | ConvertTo-Json -Compress) -ne ($after.snapshot | ConvertTo-Json -Compress)) {
            throw 'Conferencia posterior divergente. Revertendo somente flags OAuth.'
        }
        Write-Output 'Client Secret recebido pelo Django: SIM (igual ao arquivo protegido).'
        Write-Output 'OAuth delegado habilitado. Botao Conectar conta Microsoft autorizada disponivel em http://localhost:8010/integracoes/.'
        if ($EnablePlannerTest) {
            Write-Output 'Teste controlado do Planner habilitado; nenhuma tarefa foi criada automaticamente.'
            Write-Output 'Fila existente preservada. Envio automatico, e-mail e anexos continuam desligados.'
        } else {
            Write-Output 'Fila existente preservada. Envio, teste real, e-mail e anexos continuam desligados.'
        }
    } catch {
        if ($applied) {
            & docker compose -f compose.isolated.yaml up -d --no-deps web
            if ($LASTEXITCODE -ne 0) { throw 'Falha de verificacao e reversao. Nao prossiga com a conexao; informe este erro sem credenciais.' }
        }
        throw 'Ativacao nao concluida. Nenhum segredo foi exibido; mantenha as integracoes bloqueadas e informe o erro.'
    } finally { $payload = $null; Pop-Location }
} finally { $values.Clear() }
