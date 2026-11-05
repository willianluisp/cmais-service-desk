# Arquivamento e exclusão de chamados

Plano: reutilizar archived_at/archive_reason, adicionar área administrativa de
arquivados com restauração, confirmação individual de exclusão e auditoria
independente. Reautenticar pelo backend atual, exigir número exato e confirmação
de irreversibilidade, limitar tentativas e vincular a confirmação à sessão.

Filas de provisionamento, publicação de anexos e notificações devem bloquear o
chamado antes de executar trabalho externo, revalidando existência e arquivamento.
Arquivamento cancela trabalho pendente; exclusão remove dependências locais.
Arquivos privados usam fila durável de remoção após commit, com repetição em caso
de erro. Tarefas e arquivos Microsoft existentes não serão removidos; seus
identificadores serão preservados na auditoria para revisão autorizada.

Restauração não repete notificações antigas nem recria tarefas removidas no
Planner. Exclusão permanente nunca está disponível na lista principal e não
existe endpoint de exclusão em massa. Testes usam SQLite em memória e arquivos
temporários, sem operações externas, commit ou push.

## Implantação e operação

Aplicar `tickets.0005_ticketdeletionaudit_privatefiledeletion` em homologação e
reiniciar web, workers e beat com a mesma versão antes de liberar as ações.
Não misturar workers antigos, que não possuem os bloqueios do ciclo de exclusão.
As migrações criam apenas tabelas de auditoria e limpeza, sem editar chamados.

A reautenticação utiliza os backends configurados, possui limite de cinco
tentativas por administrador em cinco minutos e falha de forma fechada se o
cache não estiver disponível. A confirmação dura dez minutos, é vinculada à
sessão/chamado/versão e não pode ser reutilizada para outro chamado.

A limpeza é tentada após o commit e repetida pelo beat a cada cinco minutos.
Monitorar `PrivateFileDeletion` com `completed_at` vazio e `last_error_code`
preenchido; corrigir permissões/disponibilidade do volume quando necessário.
O beat e os workers devem estar ativos para repetir a limpeza. Até a remoção
física, o arquivo fica inacessível pelas rotas da aplicação.

O registro `TicketDeletionAudit` preserva UUID, número, ator, instante e IDs
externos. Não conserva conteúdo do chamado, destinatários ou credenciais.
Uma chamada externa já aceita antes do arquivamento não pode ser desfeita:
o arquivamento aguarda o trabalho concorrente concluir, cancela novas operações
e nunca tenta apagar a tarefa Microsoft resultante.
