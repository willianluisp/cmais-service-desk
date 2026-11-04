# Conexão delegada Microsoft sem envio de chamados

Nesta etapa, somente a conexão OAuth do servidor web é autorizada. O ambiente
base `compose.isolated.yaml` permanece com todas as flags desligadas. O arquivo
opcional `compose.oauth.isolated.yaml` habilita exclusivamente no web:

- `MICROSOFT_GRAPH_APPROVED=true`: libera a autorização Microsoft do portal.
- `GRAPH_DELEGATED_OAUTH_ENABLED=true`: libera Authorization Code com PKCE S256.

Envio automático (`PLANNER_ENABLED`), teste real (`PLANNER_TEST_ENABLED`), e-mail,
anexos e escopos SharePoint permanecem explicitamente falsos. Worker e beat
continuam com a configuração base desativada. Não iniciar, recriar ou processar
filas nesta etapa. O plano existente continua sendo Demandas Infra TI.

## Pré-requisitos locais

O arquivo `%LOCALAPPDATA%\CmaisServiceDesk\isolated\microsoft.env` deve possuir
Client Secret não vazio e chave de criptografia válida. Uma mensagem de sucesso
com `-InitializeOnly` não confirma a presença do segredo: essa opção não pede
credencial e preserva um campo que pode estar vazio. Para inserir o VALOR do
segredo, executar sem esse parâmetro:

```powershell
.\scripts\Configure-IsolatedMicrosoft.ps1
```

Nunca colocar o valor na linha de comando, em arquivos versionados ou no chat.
A comparação do valor protegido com o container deve produzir somente um
resultado booleano. Nenhum segredo ou hash reutilizável deve ser exibido.

Configuração esperada:

- Tenant ID: `9063737b-9cf5-48b0-919f-d4b505baed97`.
- Client ID: `360a498a-77f9-4046-a0aa-d8c0bab7dfd1`.
- Estratégia: `delegated`.
- Redirect URI Web: `http://localhost:8010/integracoes/microsoft/callback/`.

Esse endereço deve coincidir com o cadastro no Entra. A conferência local compara
com o endereço previamente informado como aceito; não consulta o registro remoto
da aplicação. A validade/expiração do segredo e o consentimento efetivo somente
podem ser confirmados durante a autorização Microsoft.

## Ativação após conferência dos pré-requisitos

O caminho recomendado é executar no mesmo PowerShell que gravou a credencial:

```powershell
.\scripts\Enable-IsolatedMicrosoftOAuth.ps1
```

O comando valida ACLs, presença do segredo, IDs, estratégia, chave e o caminho
resolvido pelo Compose. Recarrega somente o web com OAuth desligado e compara
a credencial e a chave recebidas pelo Django usando HMAC com nonce aleatório,
sem exibir valores ou hashes. Em seguida aplica o override exclusivo de OAuth
e confere novamente o container e os hashes dos dados do portal. Os dois
PENDING precisam permanecer intactos. Se a verificação posterior falhar,
reverte a configuração do web para OAuth desligado. Não inicia worker/beat,
não processa filas e não faz chamadas Microsoft.

`-ValidateOnly` verifica os pré-requisitos locais e os caminhos sem recriar
containers. Os testes `tests/windows/test_enable_isolated_oauth.ps1` usam somente
dados fictícios e Docker simulado. O probe Python também foi validado com
credenciais fictícias, em transações somente leitura, sem alterar as flags
persistentes do servidor. Quando duas sessões enxergarem datas diferentes no
mesmo caminho protegido, executar a recarga no terminal que vê o arquivo
atualizado; não copiar o segredo para o projeto ou enviá-lo na conversa.

Para operação manual equivalente, somente depois da validação local e da autorização:

```powershell
docker compose -f compose.isolated.yaml -f compose.oauth.isolated.yaml up -d --no-deps web
```

Isso recarrega o arquivo protegido e recria somente o web em 8010. Não executa
migrations, não altera o banco/volumes e não inicia worker/beat. Para voltar à
configuração totalmente desativada:

```powershell
docker compose -f compose.isolated.yaml up -d --no-deps web
```

## Autorização pelo navegador

Acessar `http://localhost:8010/integracoes/` com um ADMIN_PORTAL e clicar em
Conectar conta Microsoft autorizada. O login local é preservado. A autorização
solicita `openid profile offline_access User.Read Tasks.ReadWrite`, sem Mail.Send,
Sites.Selected ou permissões de aplicação nesta etapa.

`Tasks.ReadWrite` é delegada para o Planner e `User.Read` é delegada para
identificar a conta conectada por `/me`. `offline_access` permite solicitar
refresh token. Consentimento administrativo pode ser exigido pela política do
tenant mesmo quando a permissão permite consentimento do próprio usuário.
Se aparecer Aprovação necessária, o administrador do Entra deve revisar a
solicitação do aplicativo, sem ampliar as permissões indiscriminadamente.

O callback troca o código por tokens, consulta a identidade Microsoft e armazena
os tokens criptografados. Essa ação é iniciada pelo usuário no navegador; a
validação local não faz login, não segue o redirecionamento e não chama a
Microsoft. Obter consentimento Tasks.ReadWrite não equivale a habilitar envio:
as flags de criação, filas e e-mail continuam bloqueadas depois da conexão.

Não clicar em testes reais nem ativar envio. Os chamados PENDING permanecem
salvos aguardando uma etapa futura explicitamente autorizada.

Fontes: [Authorization Code/PKCE e offline_access](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow),
[Tasks.ReadWrite no Planner](https://learn.microsoft.com/en-us/graph/api/planner-post-tasks?view=graph-rest-1.0),
[User.Read para /me](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0).
