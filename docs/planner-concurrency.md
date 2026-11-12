# Proteção entre provisionamento e arquivamento

A correção sucede a versão `3c939d4`. O problema foi reproduzido com PostgreSQL e Graph simulado: a confirmação de arquivamento podia anteceder POST/PATCH de tarefas e checklists.

## Protocolo

- Um advisory lock **de sessão** PostgreSQL, com chave estável derivada do UUID do chamado, serializa as operações Graph com arquivamento, exclusão lógica/permanente e restauração.
- O worker tenta obter o lock sem espera e pula o chamado ocupado. A manutenção espera até 2 segundos; se continuar ocupado, informa que há operação em andamento, sem confirmar o arquivamento/exclusão.
- O lock permanece durante o fluxo completo do chamado, incluindo descrição, checklist, retries ETag e anexos legados. Os `transaction.atomic` e `select_for_update` continuam curtos e não abrangem o HTTP desses fluxos.
- Um `finally` libera o lock em retornos, exceções e falhas; se o desbloqueio falhar, a conexão é fechada. O PostgreSQL libera locks quando a sessão termina. Uma sessão substituída não autoriza novas escritas com o lock antigo.
- A limpeza administrativa de chamados de teste, a vinculação de tarefa recuperada, a aceitação de checklist remoto e o arquivamento automático por exclusão no Planner também respeitam o protocolo. Contenção na sincronização retorna o erro existente de integração, com HTTP 409.

## Resultado remoto incerto

Antes de uma escrita, um marcador é persistido em autocommit. Intenções de criação/reconciliação, IDs dos itens e ETags continuam persistidos como antes. A descrição tem marcador separado, para uma escrita de checklist não apagar a incerteza de outra operação.

Timeout, interrupção ou erro inesperado liberam o mutex, mas preservam a incerteza. Arquivamento e exclusão ficam impedidos até a recuperação/conferência. Um 403/412 posterior não apaga a incerteza de uma tentativa anterior. Não é possível cancelar no PostgreSQL uma requisição que já chegou à Microsoft.

Um POST ambíguo continua em reconciliação, sem novo POST automático. Encontrar e validar a tarefa existente resolve esse marcador. Descrições são recuperadas pela fila existente. Checklists usam os IDs/ETags e, quando necessário, a ação administrativa de aceitar a lista remota. Anexos incertos continuam elegíveis para recuperação, mesmo após o limite normal de tentativas; o backoff é limitado a uma hora.

O arquivamento só é confirmado após a operação terminar e seus resultados serem conhecidos. Os estados `CANCELLED` não são reativados por workers nem pela vinculação administrativa. A restauração explícita autorizada continua existindo.

## Migration e requisitos de homologação

`planner_integration/0009_attachmentpublication_graph_write_inflight_and_more.py` adiciona três campos booleanos, com default falso: marcador de escrita de anexos, marcador de tarefa/checklist e marcador de descrição. Não altera modelos de formulário, snapshots ou conteúdo remoto.

Os advisory locks exigem PostgreSQL direto ou pooling com **afinidade de sessão**. PgBouncer em modo transaction não é compatível com este protocolo. O fallback SQLite protege somente threads no mesmo processo e serve para desenvolvimento/testes; não substitui a validação PostgreSQL.

Na atualização, não misturar workers antigos e novos: os antigos não conhecem o mutex. Encerrar/drenar operações antigas e conferir envios incertos faz parte da homologação e da preparação futura de produção. Esta entrega não reiniciou serviços nem aplicou migrations em produção.

## Validação

`tests/test_planner_concurrency.py` utiliza PostgreSQL, sessões separadas, eventos e Graph simulado para verificar exclusão mútua em POST, descrição, leitura/PATCH de checklist, conflito, anexos, espera limitada, exclusão permanente, isolamento por chamado, falha de sessão/desbloqueio, interrupção e recuperação. As chamadas simuladas verificam que não há transação Django aberta.

O teste original `test_inflight_planner_work_finishes_before_archive` permanece e deve passar. O teste antigo que arquivava dentro do próprio POST simulado agora exige rejeição até o término do provisionamento, seguida de arquivamento/restauração sem duplicar a tarefa.

As melhorias de checklist e remoção da indicação visual “Obrigatório” permanecem protegidas pelas suítes existentes. Os testes de integração usam dados fictícios e bancos descartáveis; uma homologação autenticada em plano Microsoft exclusivo ainda é necessária.

Resultados desta entrega: suíte PostgreSQL completa com 700 aprovados e 5 testes opt-in pulados; SQLite com 670 aprovados e 35 pulados (PostgreSQL/opt-in). A regressão adicional de leitura local após upload incerto foi executada separadamente. Ruff, Django checks e consistência das migrations aprovados. O teste original de concorrência passou no PostgreSQL. Revisão independente sem pendências acionáveis após as correções.

## Arquivos da entrega

- Criados: `apps/planner_integration/ticket_locks.py`, migration `0009_attachmentpublication_graph_write_inflight_and_more.py`, `tests/test_planner_concurrency.py`, este documento e `docs/superpowers/plans/2026-11-12-ticket-graph-lock.md`.
- Modificados em `apps/planner_integration/`: `services.py`, `models.py`, `checklists.py`, `attachments.py` e `admin_panel.py`.
- Modificados em `apps/tickets/`: `lifecycle.py`, `lifecycle_views.py` e `services.py`.
- Modificados: `tests/test_companies_planner_titles.py`, `tests/test_planner_attachments.py` e `docs/planner-checklists.md`.
