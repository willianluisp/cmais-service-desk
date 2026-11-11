# Observações do suporte — Implementation Plan

**Goal:** exibir mensagens reais do Planner e leitura por navegador, sem escrita no Planner ou novas tabelas.
**Architecture:** serviço GET paginado, cache Redis compartilhado, rotas autorizadas Django e cliente JS com localStorage. Ativação explícita somente em PORTAL_BASE_URL localhost:8010. Usar fetch JSON para resumos em lote e conteúdo: evita uma requisição HTMX por chamado e mantém leitura controlada durante atualizações.
**Tech Stack:** Django, Graph beta, cache Django, JavaScript, pytest, Playwright.
**Spec:** pedido do usuário e `docs/planner-observations-diagnosis.md`; API beta autorizada, GET real HTTP 200 em tarefa fictícia confirmada.

## Restrições

Sem commit, push, deploy, migrations, novas dependências de produção ou alteração do ambiente 8000/volumes. Trabalhar no checkout atual e não criar worktree adicional: execução contínua solicitada pelo usuário. Não enviar mensagens nem alterar permissões. Não usar filtros PUBLICO.

## Tarefas

- [ ] Backend: testes falhando em `tests/test_planner_observations.py`, implementar `apps/planner_integration/observations.py`, `apps/tickets/observation_views.py` e rotas. API `read_observations(ticket)` retorna coleção normalizada, atualidade e disponibilidade. GET individual retorna conteúdo; GET lote retorna somente IDs ordenados, limitado a 20 chamados autorizados e alimentado por cache/fila sem disparar 20 consultas Graph sequenciais. Cache com TTL 120s, retenção 1h, trava, cooldown global 429 e fallback sem erro nos chamados. Páginas limitadas, tempo total limitado, links validados estritamente e deduplicação; jamais retornar coleção parcial como completa.
- [ ] Interface: seção expansível no detalhe e indicador reutilizável na lista/dashboard; CSS separado seguindo tokens atuais. JS consulta em lote a cada 120s com aba visível; atualizar conteúdo apenas quando necessário, preservar estado aberto e só registrar última mensagem quando seção visível. localStorage separa usuário/chamado, somente ID. ID removido resulta em aviso indeterminado, sem declarar antigas como novas. Falha de storage usa memória.
- [ ] Testes: backend mocks (páginas, ordem, 429, cache, autorização, HTML, sem comentários, feature desativada). Node para lógica de leitura e Playwright em banco pytest descartável, incluindo mobile, erro/storage e novos comentários. Primeiro executar testes e observar falhas; depois implementar e executar suite relevante, Ruff e diff check.
- [ ] Documentar evidências reais vs mocks, funcionamento, limitações e passos futuros para habilitar/testar em 8010 sem executar deploy.

## Foco da revisão

Não misturar cache entre planos/conexões; não enviar Authorization para nextLink não confiável; não marcar respostas parciais/antigas como lidas; não deixar primeiro acesso marcar listagem como lida; não permitir chamadas remotas se feature desligada ou acesso negado. Não confundir testes em mock com execução real da interface implantada.

## Registro de execução

Concluídos backend, interface, testes e documentação. TDD: módulo backend ausente → testes falhando → 28 testes passando; módulo JS ausente → testes falhando → cinco testes passando. Leitor paginado executado em memória no contêiner isolado contra a tarefa fictícia real: uma mensagem recuperada, sem deploy. O beta apresentou cursor terminal vazio apontando para si mesmo; regra específica documentada, reproduzida em teste antes da correção e validada novamente com o Graph real.

Ruling: executar no checkout atual sem worktree adicional, sem commit e sem deploy, conforme execução contínua solicitada e restrições do usuário. Nenhum comando de alteração de infraestrutura.

Verificação: 574 testes Python aprovados, cinco skips e uma exclusão de teste Compose preexistente incompatível com o HEAD. Cinco testes Node aprovados e teste Edge desktop/mobile executado separadamente. Ruff, sintaxe JS, diff check e ausência de novas migrations confirmados.

Revisão independente solicitada pela skill requesting-code-review encontrou falha de fallback quando localStorage permite getItem mas rejeita setItem por quota. Reproduzida com teste falhando, corrigida com marcador pendente em memória por chamado e revalidada. Nenhum outro problema P1/P2 identificado na revisão.
