# Consulta e exclusão lógica no Planner

A atualização manual usa a conexão Microsoft autorizada, independentemente de
`PLANNER_ENABLED`. Esta última flag controla a criação automática de tarefas.
`MICROSOFT_GRAPH_APPROVED` e a autorização OAuth continuam obrigatórios.
Os endpoints GET de tarefas, detalhes, buckets e listagem do plano utilizam o
token delegado existente (`Tasks.ReadWrite` já consentido). Nenhuma nova
permissão é solicitada por esta alteração.

Mapeamento: Tarefas pendentes → ABERTO; Desenvolvendo → EM_ATENDIMENTO;
Finalizada → RESOLVIDO. Os IDs são os persistidos em PlannerConfiguration.

Um 404 isolado não oculta chamados. A aplicação exige: vínculo com o plano
configurado, consulta de buckets bem-sucedida, ausência na listagem completa
e paginada do plano e outro GET da tarefa retornando 404. Falhas em qualquer
etapa preservam o chamado e registram o estado de erro. Um 404 em detalhes,
autenticação, falta de permissão, timeout ou payload inválido não confirma exclusão.

A confirmação preenche `Ticket.planner_deleted_at`, mantém task ID, anexos e
histórico e registra PLANNER_DELETED com chave idempotente. Listagens normais,
dashboard, detalhes e anexos deixam de expor o registro; consulta de auditoria
é feita por operador autorizado diretamente no banco, usando o registro original.
A outbox nunca reprovisiona um chamado marcado como excluído. A confirmação
também preenche `archived_at`, marca motivo PLANNER_DELETED e cancela a outbox
com estado CANCELLED. Ao atualizar por HTMX, a interface redireciona para a
listagem e exibe a confirmação. Alterações normais recarregam os detalhes para
atualizar responsáveis, checklist, progresso e histórico em conjunto.

O arquivamento local autorizado usa `archive_test_tickets(ticket_ids=[...])`,
com seleção explícita de IDs; registra TEST_ARCHIVED, preserva o task ID e
os arquivos, cancela a outbox Planner e invalida notificações pendentes do
teste. Não chama a Microsoft. Novas solicitações permanecem independentes e
geram sua própria outbox PENDING.

Em produção, `PLANNER_SYNC_ENABLED=true` habilita somente a rotina periódica
`synchronize_linked_tasks` no Celery Beat (120 segundos). Requer worker e beat
ativos e aprovação Microsoft; não habilita criação, e-mail ou SharePoint.
Permanece false por padrão no ambiente isolado. A sincronização manual usa
POST autenticado com CSRF e limite por usuário e chamado, sem cache de snapshot.

Migrations aditivas: tickets.0003_ticket_planner_deleted_at,
tickets.0004_ticket_archival_and_submission e
planner_integration.0005_provisioning_cancelled. Incluir essas colunas e
eventos no backup PostgreSQL, junto com o volume privado dos anexos.
