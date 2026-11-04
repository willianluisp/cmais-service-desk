# Acompanhamento e notificações do colaborador

## Estados apresentados

O Planner continua sendo a única origem das alterações operacionais. A abertura
local registra Aberto e uma intenção persistente de criação automática. A
sincronização compara a tarefa vinculada, grava alterações e mantém o histórico
no PostgreSQL. O portal exibe três estados sem reescrever códigos ou eventos antigos:

| Portal | Estados internos preservados |
| --- | --- |
| Aberto | ABERTO |
| Em andamento | EM_ATENDIMENTO, AGUARDANDO_SOLICITANTE |
| Finalizado | RESOLVIDO, FECHADO |

Os buckets configurados continuam mapeados para ABERTO (Tarefas pendentes),
EM_ATENDIMENTO (Desenvolvendo) e RESOLVIDO (Finalizada). Percentual 100 também
indica conclusão. Registros FECHADO antigos preservam a política existente de
não reabertura automática. Não há comando local para a TI mudar o status.

Dashboard, filtros e listagem agrupam os códigos legados. Exibem a data da
última alteração local identificada, distinta da última consulta ao Planner.
Uma consulta sem mudança atualiza somente a data de sincronização; não inventa
uma alteração remota. O botão HTMX atualiza o estado apresentado e as datas.
As consultas, indicadores e anexos permanecem restritos ao solicitante.

## Outbox reutilizada

Não foi criado outro provedor nem outra fila. `NotificationOutbox`, Celery e o
cliente `POST /users/{GRAPH_MAILBOX_ID}/sendMail` existentes foram aproveitados.

- CREATED: confirmação Recebido, com estado Aberto.
- PLANNER_CHANGED: Em andamento ou Finalizado, somente quando o estado visível
  muda. Mudança apenas de responsável, prazo, bucket equivalente ou percentual
  preserva histórico, mas não duplica o aviso de status.
- PLANNER_LINKED não gera segunda confirmação de recebimento.

O destinatário é o e-mail cadastrado do solicitante no momento do evento.
`NOTIFICATIONS_TI_RECIPIENTS` deixa de ser utilizado para esses avisos.
Cadastro sem e-mail válido não gera destinatário fictício. Mensagens não incluem
título/descrição do chamado, anexos, nomes de técnicos, tokens ou histórico
privado: apenas protocolo, etapa, data e link autenticado do portal.

A chave única por evento/destinatário impede reenfileiramento duplicado. Cada
evento e sua notificação são persistidos na transação existente. A fila usa
locks por registro e tentativas limitadas (cinco por padrão), backoff e
Retry-After. Enquanto EMAIL_ENABLED ou MICROSOFT_GRAPH_APPROVED estiver false,
o worker retorna sem consumir pendências ou imprimir e-mails no console.

`202 Accepted` indica aceitação pelo Graph, não entrega ao destinatário. O Graph
sendMail não garante deduplicação por Message-ID/cabeçalho personalizado. Em
timeout/erro de rede de aceitação incerta, a mensagem recebe FAILED com código
MAIL_ACCEPTANCE_UNKNOWN e não é reenviada automaticamente: revisar o rastreamento
Exchange antes de autorizar uma nova tentativa. Falhas explícitas recuperáveis,
como 429, usam a fila normal. Se o endereço cadastrado mudou após o evento,
RECIPIENT_CHANGED impede envio para o endereço antigo. Não existe garantia
distribuída de exactly-once sob queda do processo após a aceitação remota e
antes do commit local.

Mensagens antigas e histórico não são apagados/recriados. Linhas FAILED antigas
exigem revisão antes de eventual reenvio; não há replay automático nem alteração
de credenciais. A recuperação de senha continua usando sua outbox independente
de eventos e as mesmas proteções anteriores de tokens.

## Ativação futura — somente após autorização

1. Definir a caixa corporativa remetente no Exchange Online e configurar
   GRAPH_MAILBOX_ID no armazenamento protegido; validar sua existência e política.
2. O Mail API usa **client credentials**, separado do OAuth delegado do Planner.
   O escopo Tasks.ReadWrite não permite envio de e-mails. Manter tenant, client ID
   e segredo exclusivamente no armazenamento protegido já existente.
3. Autorizar Mail.Send **de aplicação**, com consentimento administrativo, ou
   configurar o papel **Application Mail.Send** via Exchange Application RBAC
   limitado à caixa remetente. O administrador Exchange deve escolher o modelo
   e testar explicitamente acesso permitido à remetente e negado às demais.
4. Atenção: grants RBAC e grants irrestritos no Entra são aditivos. Adicionar
   RBAC não limita um Mail.Send amplo já consentido. Se escolher RBAC restrito,
   revisar/remover grants amplos correspondentes; não conceder permissões de
   administração Exchange ao Service Desk.
5. Revisar o e-mail de cada colaborador, URL HTTPS futura do portal e política
   de retenção/privacidade das mensagens. O usuário colaborador.teste precisa
   de e-mail de teste autorizado antes da homologação real de notificações.
6. Revisar a fila existente e autorizar um destinatário de homologação. Somente
   então configurar NOTIFICATIONS_PROVIDER=graph e liberar EMAIL_ENABLED e
   MICROSOFT_GRAPH_APPROVED no ambiente autorizado. A liberação do envio é
   separada da ativação do Planner; o Compose isolado mantém ambas false.

Referências oficiais: [sendMail e permissões](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0),
[Exchange Application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).
Nenhum e-mail, consulta de autenticação ou escrita Microsoft foi realizado no desenvolvimento.
