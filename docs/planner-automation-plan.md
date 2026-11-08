# Integração automática Planner — 2026-11-08

Objetivo: administrar conexão, plano, bucket e automação pelo portal, reutilizando OAuth delegado, outbox e projeções existentes.

Restrições: nenhuma execução de migrations, Docker, commit, push ou deploy; preservar portas 8000/8010 e todas as aprovações externas. Testes usam SQLite em memória com migrations desabilitadas e Graph simulado.

Decisões: configuração persistente selecionada pela administração; ativação explícita e auditada, subordinada à aprovação Microsoft Graph. Flags antigas continuam funcionando até a primeira escolha explícita pela interface. Portal fornece conteúdo inicial; Planner controla progresso, responsáveis, prazo, checklist e bucket; fechamento definitivo continua local. Troca de plano bloqueada quando há tarefas vinculadas ou criação incerta, evitando perder vínculos. Polling existente permanece; Planner não consta nos recursos de change notifications do Graph.

## Execução

- [x] Configuração persistente, seleção validada pelo Graph e ativação explícita. Testes de permissões, CSRF, seleção inválida e preservação de vínculos.
- [x] Teste de conexão somente leitura e sincronização solicitada de forma durável, com execução via Celery. Testes de indisponibilidade do Redis e mensagens sem segredos.
- [x] Reforçar retries, reconciliação e controle de concorrência/throttling; testes de falhas antes/depois do POST, renovação e projeção sem conceder acesso.
- [x] Simplificar administração e documentar Entra, operação pela interface e limites. Suíte isolada e verificações estáticas.

Não executar alterações operacionais. Migration será apenas escrita para revisão; aplicação depende de autorização posterior.

Revisão independente identificou consulta de buckets suscetível a troca concorrente do plano; correção validada por regressão. Recuperação de vínculo ambíguo também disponível na interface. Guia: `docs/planner-automatic-integration.md`.
