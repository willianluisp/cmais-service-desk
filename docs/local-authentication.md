# C+ Service Desk — autenticação local e homologação

O modo padrão é `LOCAL_AUTH_ENABLED=true`. Esse modo desativa o backend AD mesmo que suas flags estejam presentes. Os perfis AD e os vínculos com chamados existentes são preservados. Não há cadastro público.

## Primeiro administrador real

Em `ServiceDeskCmais`, use somente o Compose isolado:

```powershell
docker compose -f compose.isolated.yaml up -d --build
docker compose -f compose.isolated.yaml exec web python manage.py createsuperuser
```

Informe uma identidade administrativa real e uma senha forte no prompt interativo. Nenhuma conta administrativa foi criada automaticamente. Entre em http://localhost:8010/login/; no primeiro acesso, troque a senha em `/conta/senha/`. Depois acesse `/admin/` para cadastrar, desativar ou gerenciar contas. A administração de usuários é restrita a superusuários ativos. Exclusão de colaboradores pela interface foi bloqueada para preservar histórico; desative a conta. Alterações administrativas são auditadas sem valores de senha.

## Importação de colaboradores

CSV UTF-8 com colunas `full_name,email` e `username` opcional. Forneça nomes completos reais; o sistema nunca deriva nomes de e-mails. O primeiro e último nome normalizados formam `nome.sobrenome`. Em colisões, o arquivo inteiro fica pendente: resolva o `username` explicitamente no mesmo formato. E-mails repetidos, nomes ausentes e identidades existentes divergentes são rejeitados. Uma importação repetida não altera a senha nem duplica contas existentes.

Copie o arquivo real para um diretório privado no container e faça primeiro a prévia:

```powershell
docker compose -f compose.isolated.yaml exec -T web python manage.py import_employees /tmp/colaboradores.csv --actor SEU_ADMIN
docker compose -f compose.isolated.yaml exec -T web python manage.py import_employees /tmp/colaboradores.csv --actor SEU_ADMIN --apply --credentials-output /tmp/credenciais-individuais.json
```

A saída deve ser um arquivo novo fora de `/app`, criado com modo 0600 no Linux. Senhas aleatórias individuais são armazenadas apenas em hash no Django; o arquivo de entrega contém a senha temporária para distribuição individual por canal seguro. Transfira-o para cofre corporativo, controle acesso e descarte-o pelo procedimento da empresa após entrega. Nunca anexe esse arquivo ao Git, chat ou chamado. No Windows, o responsável deve aplicar ACL privada ao destino de transferência. Não usar senha compartilhada em produção.

A troca obrigatória bloqueia dashboard, chamados, anexos, admin e APIs até concluir o primeiro acesso. A troca usa a senha antiga; a recuperação usa token Django temporário e de uso único. O reset administrativo de senha também exige nova troca. Há CSRF, proteção de sessão, limite por usuário/IP no login e limite por IP na recuperação.

## Recuperação e Microsoft

`/conta/recuperar/` responde de forma genérica, exista ou não a conta. O link usa `PORTAL_BASE_URL`, não o Host fornecido pelo cliente. A mensagem entra na outbox persistente; links de recuperação nunca são enviados ao console. O envio depende de Outlook aprovado/configurado. Enquanto isso, um administrador pode redefinir uma senha individual pelo admin e entregá-la pelo canal seguro.

```powershell
docker compose -f compose.isolated.yaml exec -T web python manage.py check_integrations
```

O comando acima só lista campos ausentes e flags, sem mostrar segredos nem acessar rede corporativa. Para homologação, obter Tenant ID, Client ID e **valor do client secret** no cofre da aplicação Entra; o cliente atual implementa segredo, não client assertion de certificado. Configurar `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`. Permissões Graph de aplicação: `Tasks.ReadWrite.All` para criação/descrição/leitura Planner e `Mail.Send` para Outlook, ambas com consentimento administrativo.

Obter plano de homologação (`GRAPH_PLAN_ID`) e buckets (`PLANNER_BUCKET_ENTRADA_ID`, opcionais andamento/concluído). Aprovar mailbox dedicada (`GRAPH_MAILBOX_ID`) e restringir o alcance da aplicação no Exchange. Somente após autorização habilitar `MICROSOFT_GRAPH_APPROVED`, `PLANNER_ENABLED`, `EMAIL_ENABLED` e `NOTIFICATIONS_PROVIDER=graph`. Nenhuma chamada Microsoft real foi feita nesta etapa.

O Compose isolado possui web, worker e beat, que processam as outboxes e consultam tarefas vinculadas. As flags bloqueiam rede externa. Após timeout de criação, uma reconciliação sem resultado não repete automaticamente o POST; precisa aguardar visibilidade ou análise administrativa. Descrição usa ETag de detalhes, não da tarefa, e aceita 204 vazio.

A outbox deduplica por evento/destinatário, mas Graph `sendMail` não fornece garantia de exatamente uma entrega após timeout/crash: um aceite remoto seguido de falha local pode gerar reenvio. HTTP 202 confirma aceitação, não entrega. `TicketAccess` segue exigido para técnicos; o cadastro não concede acesso global nem associação automática por e-mail.

Limite pendente para homologação: uma queda abrupta do worker entre o aceite de criação Planner e o commit local continua exigindo conferência administrativa por protocolo. Os testes cobrem timeout tratado e retentativa de detalhes, não uma garantia distribuída de exatamente uma criação em qualquer crash. Não homologar esse cenário como resolvido sem ensaio controlado e revisão da estratégia de lease/reconciliação.

## Primeiro teste real autorizado

1. Criar o administrador real, importar o CSV em prévia, resolver conflitos e aplicar.
2. Entrar com um colaborador autorizado, trocar a senha e abrir um chamado com print.
3. Com app/plano/mailbox homologados e flags autorizadas, confirmar tarefa única e descrição/link protegido no Planner.
4. Alterar progresso, bucket e checklist no Planner; usar Atualizar status e confirmar histórico.
5. Conceder TicketAccess a um técnico e verificar o anexo; um usuário sem concessão deve receber 404.
6. Enviar apenas ao destinatário de homologação autorizado e confirmar aceite e recebimento, inclusive da recuperação de senha.

Testes automatizados usam contas no banco descartável e mocks. A raiz Git foi regularizada dentro de ServiceDeskCmais; confirme com `git rev-parse --show-toplevel` antes de preparar o índice.
