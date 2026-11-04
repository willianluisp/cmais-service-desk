# Homologação Microsoft — C+ Service Desk

Verificação de código/configuração e documentação oficial em 29/10/2026. Nenhuma autenticação Graph, criação de tarefa ou envio de e-mail real foi executado. O ambiente desta etapa é exclusivamente `compose.isolated.yaml`, porta 8010.

## Por que o Planner ainda não cria tarefas

Regra vigente: todo chamado confirmado é salvo com uma entrada única na outbox `PlannerTaskProvisioning`, sem aprovação da TI. O Celery processa automaticamente essa fila após a ativação autorizada. Plano definido: **Demandas Infra TI**, `OYsA-pTkhUm5MuVZj6PxK2UAHdk5`. Os buckets ainda devem ser consultados; nenhum ID é inferido pelo nome.

Depois de autorizar e concluir somente o OAuth delegado, mantendo `PLANNER_ENABLED=false`, a consulta somente leitura pode ser executada explicitamente:

```powershell
docker compose -f compose.isolated.yaml exec -T web python manage.py planner_buckets --execute
```

Sem `--execute`, o comando apenas informa a preparação e não acessa rede. A consulta exige `MICROSOFT_GRAPH_APPROVED` e autorização do provedor delegado. Não depende de um bucket já configurado nem da ativação da fila de escrita. Nomes ausentes ou duplicados exigem revisão, sem escolher IDs automaticamente. O comando informa os valores reais para configurar em armazenamento local protegido:

- `Tarefas pendentes` → `PLANNER_BUCKET_ENTRADA_ID`.
- `Desenvolvendo` → `PLANNER_BUCKET_EM_ANDAMENTO_ID`.
- `Finalizada` → `PLANNER_BUCKET_CONCLUIDO_ID`.

No estado atual todas as flags estão false. A fila preserva pendências sem marcar falha pela desativação deliberada. Falhas temporárias são reagendadas; quando um POST pode ter sido aceito, reconcilia-se pelo protocolo antes de qualquer novo envio. Ausência após timeout não prova falha, portanto não se repete o POST cegamente. IDs conhecidos são reutilizados para completar a descrição. Não existe garantia distribuída de exatamente uma criação sob queda abrupta antes do commit local; casos ambíguos ficam para reconciliação, conforme a limitação já documentada. O link para detalhes/anexos exige autenticação e TicketAccess; não expõe URL pública de arquivo. `localhost` é utilizável apenas na máquina do portal durante homologação; acesso da TI em outros computadores exigirá URL corporativa HTTPS.

O diagnóstico local indica ausência de `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `PLANNER_PLAN_ID` e `PLANNER_INTAKE_BUCKET_ID`. Os dois últimos settings vêm das variáveis `GRAPH_PLAN_ID` e `PLANNER_BUCKET_ENTRADA_ID`. `MICROSOFT_GRAPH_APPROVED=false`, `PLANNER_ENABLED=false` e `EMAIL_ENABLED=false` bloqueiam as chamadas antes da rede. Não é evidência de uma falha de autenticação delegada: nenhuma autenticação real foi tentada.

## OAuth delegado para o Planner

### Painel administrativo

Acesse `http://localhost:8010/integracoes/` com superusuário local ativo e senha inicial já trocada. O painel não faz chamadas Microsoft ao abrir. Mostra conexão armazenada e validade do acesso (não prova autorização remota), flags efetivas, totais da outbox, pendências e tentativas de teste. Técnicos, colaboradores e staff sem superusuário não acessam as operações. Todos os formulários usam POST, autenticação, autorização no backend e CSRF.

O botão Conectar reutiliza o OAuth delegado. Após autorização específica da conexão, Consultar buckets realiza somente leitura no plano Demandas Infra TI; permite escolher três IDs distintos retornados pela API e salvar o mapeamento no PostgreSQL. O mapeamento persistido é usado pela fila e sincronização para o plano correspondente, prevalecendo sobre variáveis dos buckets. Nenhum plano novo é criado e salvar configurações não habilita flags. A alteração de mapeamento é auditada.

O teste controlado exige `MICROSOFT_GRAPH_APPROVED=true`, OAuth delegado autorizado, `PLANNER_TEST_ENABLED=true` e confirmação literal `CRIAR TAREFA DE TESTE`. Pode ser autorizado com `PLANNER_ENABLED=false`, preservando a fila normal até liberação separada. Todas essas flags permanecem false no Compose isolado desta entrega. A tentativa é persistida antes do POST remoto; o mesmo formulário não gera outra tentativa mesmo com reenvio concorrente. Resultado incerto recebe estado VERIFY, sem retentativa automática. A tarefa usa título TESTE e correlação, sem dados pessoais. Sua remoção posterior é manual no Planner. A criação de teste e mudanças de mapeamento têm auditoria local; não se armazenam respostas brutas de erro nem tokens no painel.

### Armazenamento local do ambiente isolado

As configurações Microsoft do Compose isolado são carregadas de `%LOCALAPPDATA%\CmaisServiceDesk\isolated\microsoft.env`, fora do repositório e do OneDrive. A pasta e o arquivo têm ACL NTFS sem herança, permitindo somente a conta Windows atual e SYSTEM. O arquivo contém valores em texto protegido por ACL, não um cofre criptografado; administradores da máquina e usuários com acesso ao daemon Docker podem acessar os segredos do processo. Não imprima `docker compose config` nem dumps de ambiente/inspect; use `config --quiet`.

Para inserir o **valor** do segredo (não o Secret ID), abra PowerShell na pasta `ServiceDeskCmais` e execute:

```powershell
.\scripts\Configure-IsolatedMicrosoft.ps1
docker compose -f compose.isolated.yaml up -d --no-deps web worker beat
```

O script solicita o segredo com `Read-Host -AsSecureString`, grava diretamente no arquivo protegido e não o imprime nem o inclui na linha de comando/histórico. Não execute sob transcrição ou depuração de variáveis. `-InitializeOnly` prepara os IDs e gera uma chave Fernet de 32 bytes aleatórios somente se ela ainda não existir; nunca substitui a chave existente. Preserve a chave em backup seguro, pois sua perda impede decifrar tokens já armazenados. O Compose usa `env_file` com `format: raw` para impedir interpolação de caracteres do segredo (requer Compose 2.30+). Todas as flags permanecem explicitamente false no Compose, inclusive após carregar o arquivo.

Configure `GRAPH_PLAN_ID` e `PLANNER_BUCKET_ENTRADA_ID` nesse mesmo arquivo local com os identificadores do plano e bucket de homologação, obtidos pelo responsável pelo Planner. Não use um plano de produção. A conta Microsoft autorizada deve ter acesso a esse plano. Nenhuma consulta real de IDs é executada por esse procedimento.

O portal mantém a sessão local Django. Um superusuário local explicitamente autorizado inicia a conexão Microsoft; somente o callback OAuth cria ou atualiza a conexão delegada ativa. O fluxo usa Authorization Code com `state` de uso único, expiração de 10 minutos e PKCE `S256`. Tokens de acesso e renovação são cifrados no banco com `GRAPH_TOKEN_ENCRYPTION_KEY`; jamais inclua essa chave, tokens ou segredos no Git.

Cadastre exatamente este Redirect URI da aplicação **Web** de homologação:

```
http://localhost:8010/integracoes/microsoft/callback/
```

O ambiente isolado usa `localhost` de forma consistente. Faça login e inicie o OAuth em `http://localhost:8010/`, pois a sessão com o `state` é vinculada ao host. O Compose define `ALLOWED_HOSTS=localhost`, origem CSRF `http://localhost:8010` e cookies exclusivos `cmais_isolated_sessionid`/`cmais_isolated_csrftoken`, sem domínio compartilhado. Em HTTP local, Secure permanece false; HttpOnly e SameSite=Lax permanecem ativos. Para produção, use HTTPS. A URI enviada pelo código deriva de `PORTAL_BASE_URL` e deve coincidir exatamente com o cadastro Entra.

Para a futura URL HTTPS de homologação, registre a URL pública equivalente com o mesmo caminho; não substitua uma pela outra. Em **API permissions**, adicione `Tasks.ReadWrite` e `User.Read` como permissões **Delegated** e conceda consentimento administrativo se a política do tenant o exigir. `User.Read` é usado somente para confirmar o identificador imutável e o UPN da conta que autorizou o Planner. O fluxo também solicita `openid`, `profile` e `offline_access` para identidade e renovação do acesso.

O caminho fica deliberadamente inativo enquanto `MICROSOFT_GRAPH_APPROVED=false` ou `GRAPH_DELEGATED_OAUTH_ENABLED=false`. Para uma homologação aprovada, use `GRAPH_AUTH_STRATEGY=delegated`, mantenha `PLANNER_ENABLED=false` até revisar a conta vinculada e injete uma chave Fernet exclusiva pelo cofre. Gere-a uma única vez em ambiente administrativo com `Fernet.generate_key()` e preserve-a para que conexões existentes continuem decifráveis.

Também não há usuários locais nem chamados pendentes de envio no banco isolado nesta verificação. A criação do primeiro administrador real e a aprovação da lista de colaboradores são etapas separadas da permissão Graph.

## Operações e permissões documentadas

| Operação usada | Endpoint Graph v1.0 | Permissão de aplicação |
| --- | --- | --- |
| Criar tarefa | `POST /planner/tasks` | `Tasks.ReadWrite.All` |
| Consultar tarefa | `GET /planner/tasks/{id}` | `Tasks.Read.All` ou `Tasks.ReadWrite.All` |
| Consultar detalhes/checklist | `GET /planner/tasks/{id}/details` | `Tasks.Read.All` ou `Tasks.ReadWrite.All` |
| Listar para reconciliar | `GET /planner/plans/{id}/tasks` | `Tasks.Read.All` ou `Tasks.ReadWrite.All` |
| Atualizar descrição inicial | `PATCH /planner/tasks/{id}/details` | `Tasks.ReadWrite.All` |
| Enviar e-mail | `POST /users/{mailbox}/sendMail` | `Mail.Send` ou autorização Exchange RBAC equivalente |

Todas essas operações documentam autenticação de aplicação. O fluxo atual OAuth client credentials com `https://graph.microsoft.com/.default` é adequado; não é necessário adicionar login delegado para essas operações. O PATCH usa ETag dos detalhes e aceita 204 sem corpo. O portal não oferece edição operacional de status/checklist/atribuições.

**Limite de produto:** as APIs Planner Graph v1.0 acessam planos básicos; planos Premium não são suportados por estes endpoints. Crie um plano básico chamado, por exemplo, C+ Service Desk — Homologação, separado dos planos de produção. Consentimento documentado não comprova licença ou acesso ao plano específico.

## O que configurar no Entra e no Planner

1. Entra admin center → App registrations → criar ou selecionar uma aplicação de serviço exclusiva para homologação. Em Overview, copiar Directory (tenant) ID e Application (client) ID para `GRAPH_TENANT_ID` e `GRAPH_CLIENT_ID` no `.env.isolated` protegido/cofre. Não alterar credenciais PostgreSQL nem variáveis do ambiente 8000.
2. Certificates & secrets → credencial aprovada. O código atual usa **client secret**: armazenar seu **valor**, não o Secret ID, em `GRAPH_CLIENT_SECRET`, por canal seguro. Não colar segredo no chat ou Git; implementar rotação. Client assertion por certificado não está implementado.
3. API permissions → Microsoft Graph → **Application permissions → Tasks.ReadWrite.All** → consentimento administrativo. A leitura já está coberta; não adicionar `Group.ReadWrite.All` ou `User.Read.All` por conveniência. Essa permissão tem alcance amplo no tenant: o Plan ID no aplicativo define o alvo, mas não constitui uma restrição de segurança no Entra.
4. O dono do grupo Microsoft 365 deve criar o plano **básico** de homologação e buckets Entrada, Em andamento e Concluído. Obter o Plan ID pela URL ou consulta administrativa autorizada; listar buckets por `GET /planner/plans/{id}/buckets`. Consultar com Graph Explorer pode ajudar a obter IDs, mas usa contexto delegado e não comprova acesso da aplicação de serviço.
5. Preencher `GRAPH_PLAN_ID`, `PLANNER_BUCKET_ENTRADA_ID` e, se aplicável, `PLANNER_BUCKET_EM_ANDAMENTO_ID` e `PLANNER_BUCKET_CONCLUIDO_ID` exclusivamente com IDs de homologação. Aprovar o teste antes de habilitar `MICROSOFT_GRAPH_APPROVED=true` e `PLANNER_ENABLED=true`.

O link atual do portal é local (`http://localhost:8010`). Ele serve para o teste na mesma estação. Para links do Planner utilizados em outras estações será necessária URL interna HTTPS acessível e `PORTAL_BASE_URL` correspondente, sem tornar anexos públicos.

## Outlook: remetente, destinatário e restrição

Escolher uma mailbox Exchange Online de serviço aprovada (de usuário ou compartilhada, conforme licenciamento/política da empresa), informar seu UPN ou ID em `GRAPH_MAILBOX_ID` e definir **um destinatário de homologação autorizado**. Habilitar posteriormente `NOTIFICATIONS_PROVIDER=graph`, `EMAIL_ENABLED=true` e a aprovação Graph. Não modificar mailbox ou políticas Exchange por esta rotina.

O administrador Exchange deve definir o alcance à caixa autorizada. Para **Application RBAC**, configurar a role `Application Mail.Send` com um resource scope limitado à mailbox; validar uma caixa permitida e outra negada com `Test-ServicePrincipalAuthorization`. **Não manter uma concessão Entra Mail.Send sem escopo e presumir que RBAC a restringe:** as permissões são aditivas. Se a organização optar pelo caminho de permissão Entra `Mail.Send`, será necessária a política de acesso compatível que realmente a restrinja; a recomendação atual da Microsoft é RBAC para aplicações. A escolha e os testes são de responsabilidade do administrador Exchange, com a documentação oficial.

## Primeiro teste real — somente após aprovação

1. Confirmar aprovação do administrador/colaborador de teste, plano básico, buckets, app e mailbox/destinatário. Registrar os IDs fora do Git.
2. Antes de habilitar flags, revisar filas locais e interromper **somente worker e beat isolados** durante a configuração. Não executar esses passos agora: qualquer pendência antiga pode ser processada ao ativar a integração. Não excluir pendências para facilitar o teste.
3. Preencher segredos pelo mecanismo privado e executar `docker compose -f compose.isolated.yaml exec -T web python manage.py check_integrations`. Ele só verifica presença, sem mostrar valores ou abrir rede.
4. Sob autorização de conectividade/autenticação, obter token pelo backend e consultar tarefa/plano/bucket de homologação. Registrar sucesso ou código sanitizado; nunca imprimir access token. Diferenciar 401 (credencial/token), 403 (consentimento/acesso), 404 (ID/visibilidade), 429 (limite) e timeout.
5. Fazer login local e abrir **um** chamado de homologação com título identificável e sem dados pessoais sensíveis. Confirmar PostgreSQL, evento CREATED e intenção Planner persistente. Conferir que apenas esse envio está elegível antes de liberar o worker.
6. Autorizar/reiniciar worker e beat isolados; confirmar um cartão no plano básico correto, protocolo, descrição, correlação e link autenticado. Alterar o cartão no Planner e usar Atualizar status. Uma segunda atualização sem mudanças não deve gerar evento novo.
7. Para e-mail, aprovar o destinatário real e revisar a lista configurada em `NOTIFICATIONS_TI_RECIPIENTS`; o e-mail do solicitante também recebe notificações. Habilitar somente após essa conferência. Confirmar outbox, HTTP 202 e recebimento. HTTP 202 não confirma entrega final.
8. Registrar resultados de cada passo e manter flags desligadas quando o teste não estiver autorizado. Nenhuma etapa acima foi executada contra Microsoft nesta rodada.

O retry local não equivale a garantia distribuída de exatamente uma operação: aceite remoto seguido de crash local exige reconciliação. Essa limitação permanece documentada em `local-authentication.md`.

## Evidência automatizada

Suíte completa com mocks, incluindo autenticação, importação, permissões, Planner, detalhes/ETag, recuperação, Graph Mail e preparação do CSV: **136 testes aprovados**. Ruff aprovado, Django check aprovado e nenhuma migration nova/pendente de código. A exportação real não é usada como fixture nem incluída na imagem Docker.

## Fontes oficiais

- [Criar tarefa e Tasks.ReadWrite.All](https://learn.microsoft.com/en-us/graph/api/planner-post-tasks?view=graph-rest-1.0)
- [Consultar tarefa](https://learn.microsoft.com/en-us/graph/api/plannertask-get?view=graph-rest-1.0)
- [Consultar detalhes](https://learn.microsoft.com/en-us/graph/api/plannertaskdetails-get?view=graph-rest-1.0)
- [Listar tarefas de um plano](https://learn.microsoft.com/en-us/graph/api/plannerplan-list-tasks?view=graph-rest-1.0)
- [Atualizar detalhes](https://learn.microsoft.com/en-us/graph/api/plannertaskdetails-update?view=graph-rest-1.0)
- [Planos básicos e Premium](https://learn.microsoft.com/en-us/graph/api/resources/planner-overview?view=graph-rest-1.0)
- [sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
- [Exchange Application RBAC e permissões aditivas](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac)

## Configurador local no Windows PowerShell 5.1

Em 03/11/2026, `scripts/Configure-IsolatedMicrosoft.ps1` foi corrigido para
Windows PowerShell 5.1. Execute na raiz do ServiceDeskCmais:

```powershell
.\scripts\Configure-IsolatedMicrosoft.ps1
```

Informe o valor do segredo somente na entrada oculta. O destino permanece
`%LOCALAPPDATA%\CmaisServiceDesk\isolated\microsoft.env`, fora do OneDrive e
ignorado pelo Git. Não cole credenciais na linha de comando ou no chat.

O script aplica uma DACL exclusiva ao usuário atual e ao SYSTEM, verifica
`Get-Acl` e interrompe em qualquer falha. A pasta e o arquivo existente são
protegidos antes da leitura e antes de solicitar a credencial. Não habilita
flags, não reinicia containers e não chama a Microsoft.

`Set-Acl` é usado para gravar o descritor de acesso. Caso o provedor exija
indevidamente `SeSecurityPrivilege`, somente esse erro admite persistência
direta da DACL. Em .NET Framework, usa os métodos de instância
[DirectoryInfo.SetAccessControl](https://learn.microsoft.com/en-us/dotnet/api/system.io.directoryinfo.setaccesscontrol?view=netframework-4.8.1)
e [FileInfo.SetAccessControl](https://learn.microsoft.com/en-us/dotnet/api/system.io.fileinfo.setaccesscontrol?view=netframework-4.8.1).
A API `FileSystemAclExtensions` fica restrita ao ramo PowerShell 7/.NET moderno.
Não altera proprietário ou auditoria, não solicita privilégios adicionais e
sempre confere as permissões após a gravação. Falhas comuns de acesso não são
ignoradas. Links/junctions e armazenamento no projeto ou OneDrive são recusados.

Validação com dados fictícios em pastas temporárias, sem acessar o arquivo real:

```powershell
powershell.exe -NoProfile -File .\tests\windows\test_configure_isolated_microsoft.ps1
```

O teste cobre sintaxe, execução repetida, ACLs, entrada oculta, saída sem
credenciais, preservação da chave e flags, inicialização sem arquivo, falhas de
ACL e entrada inválida. Também foi executado no PowerShell 7.
