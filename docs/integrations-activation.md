# Ativação das integrações — C+ Service Desk

Não habilite flags nem consulte AD ou Microsoft 365 sem autorização do responsável.

## Active Directory — CMAIS.LOCAL

Implementado: login sem senha Django, limitação de tentativas, LDAPS com CA obrigatória, grupos autorizados, bloqueio de conta desativada e revalidação por `objectGUID`. O portal não associa usuários por nome ou e-mail.

```text
LDAP_ENABLED=true
LDAP_APPROVED=true
AUTH_LDAP_SERVER_URI=ldaps://SERVIDOR.cmais.local:636
AUTH_LDAP_USER_SEARCH_BASE=DC=cmais,DC=local
AUTH_LDAP_GROUP_SEARCH_BASE=DC=cmais,DC=local
LDAP_CA_CERT_PATH=/run/secrets/cmais-ad-ca.pem
AUTH_LDAP_BIND_DN=<DN da conta somente leitura>
AUTH_LDAP_BIND_PASSWORD=<valor do cofre>
LDAP_GROUP_COLABORADOR_DN=<DN completo>
LDAP_GROUP_TECNICO_TI_DN=<DN completo>
LDAP_GROUP_SUPERVISOR_TI_DN=<DN completo>
LDAP_GROUP_ADMIN_PORTAL_DN=<DN completo>
```

O administrador usa **Active Directory Users and Computers → Attribute Editor** para copiar os DNs dos grupos, cria conta de bind com somente leitura e exporta, em `certlm.msc`, apenas a cadeia pública da CA que assina `SERVIDOR.cmais.local`. Monte essa CA como arquivo somente leitura no container. Senha inválida, grupo não autorizado ou AD indisponível devem negar o login, sem fallback local.

Para uma imagem de homologação LDAPS, defina `INSTALL_LDAP=true` no `.env.isolated` privado e execute `docker compose -f compose.isolated.yaml up -d --build`; o padrão mantém LDAP fora da imagem.

## Entra ID e Graph

Implementado: client credentials com `/.default`, cache e renovação de token, tratamento seguro de 401/403/429/timeout. LDAP não fornece token Microsoft. No **Entra admin center → App registrations**, crie `C+ Help Desk`; em **Overview**, obtenha Directory tenant ID e Application client ID. Em **Certificates & secrets**, prefira certificado; se usar segredo, injete-o exclusivamente por cofre em `GRAPH_CLIENT_SECRET`.

Em **API permissions → Microsoft Graph → Application permissions**, o administrador adiciona e concede **Grant admin consent** para `Tasks.ReadWrite.All` (criar, descrever e consultar Planner) e `Mail.Send` (enviar por `/users/{id}/sendMail`).

```text
MICROSOFT_GRAPH_APPROVED=true
GRAPH_TENANT_ID=<tenant ID>
GRAPH_CLIENT_ID=<application client ID>
GRAPH_CLIENT_SECRET=<segredo/cert assertion do cofre>
```

## Planner e Outlook

Planner implementado: outbox persistente, protocolo, correlação, link autenticado, ID persistido antes do PATCH, reconciliação pós-timeout, paginação e projeção somente leitura de bucket, progresso, IDs de responsáveis, prazo e checklist. A repetição não cria cartão duplicado.

```text
GRAPH_PLAN_ID=<id do plano TI>
PLANNER_BUCKET_ENTRADA_ID=<id do bucket de entrada>
PLANNER_BUCKET_EM_ANDAMENTO_ID=<opcional>
PLANNER_BUCKET_CONCLUIDO_ID=<opcional>
PORTAL_BASE_URL=https://<portal-homologado>
PLANNER_ENABLED=true
EMAIL_ENABLED=true
NOTIFICATIONS_PROVIDER=graph
GRAPH_MAILBOX_ID=<UPN ou ID da mailbox de serviço>
```

Obtenha o plano pela URL do Planner ou por `GET /groups/{grupo-id}/planner/plans`; buckets por `GET /planner/plans/{plan-id}/buckets`. Use plano separado para a primeira escrita autorizada. Outlook possui outbox transacional, deduplicação, Celery, backoff e `Retry-After`; HTTP 202 confirma somente aceitação. Use mailbox dedicada e peça ao administrador Exchange limitação de escopo de `Mail.Send`.

## Associação e checklist

`UserProfile` guarda `object_guid` (AD), `entra_object_id` e `planner_user_id`. O vínculo exige IDs imutáveis oficiais e impede reutilização em outro usuário. Técnico não ganha acesso global: leitura de chamados/anexos exige `TicketAccess`.

**Posso fazer agora:** preparar `.env` privado com flags falsas; criar plano e mailbox de homologação; instalar `requirements-ldap.lock`; validar o Compose em `http://127.0.0.1:8010/`.

**Preciso do supervisor:** autorizar teste LDAPS, CA, conta bind e grupos; criar app Entra e consentir `Tasks.ReadWrite.All` e `Mail.Send`; aprovar primeira escrita/e-mail e a mailbox/escopo Exchange.

**Depende de infra:** licença e acesso ao plano Planner; DNS/CA LDAPS acessíveis do Docker; mailbox Exchange Online com política de escopo.

## Referências oficiais

- [Client credentials](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-daemon-acquire-token)
- [Criar tarefa Planner](https://learn.microsoft.com/en-us/graph/api/planner-post-tasks?view=graph-rest-1.0)
- [Enviar e-mail Graph](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
- [Permissões Microsoft Graph](https://learn.microsoft.com/en-us/graph/permissions-reference)
