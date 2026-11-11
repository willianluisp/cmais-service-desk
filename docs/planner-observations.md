# Observações do suporte — homologação experimental

> Atualização de 11/11/2026: a integração existente também aceita a origem HTTPS configurada, mediante todas as flags de aprovação. Consulte `conversation-regression-2026-11-11.md` e `production-release-review-2026-11-11.md` para o diagnóstico e a lista atual da entrega. Os resultados e passos abaixo registram a homologação original.

Implementado em 10/11/2026. Código preparado e testado, sem deploy. Não está ativo no contêiner existente até que alguém publique a nova imagem e habilite explicitamente a funcionalidade.

## Validação real com Microsoft

Localizada por título exato a tarefa `TESTE - Observações C+ Service Desk` no plano atualmente configurado. O identificador operacional foi omitido deste documento.

`GET https://graph.microsoft.com/beta/planner/tasks/{TASK_ID_DE_TESTE}/messages` retornou **HTTP 200** com uma mensagem, usando o OAuth delegado existente e Tasks.ReadWrite. Não foi necessário alterar escopos ou permissões. Nenhuma mensagem foi criada ou modificada.

O novo leitor foi executado em memória no contêiner isolado, sem instalar arquivos ou reconstruir/reiniciar serviços. Recuperou a mensagem com data válida, percorreu a continuação e encerrou com sucesso. O nome do autor não veio nessa resposta: o portal usa “Equipe de suporte” quando não há displayName.

A resposta real trouxe `deletedDateTime`/`editedDateTime` e `$skiptoken` em minúsculas. A implementação aceita o campo de exclusão observado e o nome documentado `deletedTime`. Na última página, observamos `value: []` com nextLink apontando para a própria página; somente esse caso exato, após uma página de continuação, é tratado como cursor terminal experimental. Páginas vazias com outro cursor continuam sendo percorridas. Ciclos não vazios ou entre links diferentes resultam em indisponibilidade, sem leitura parcial.

Essa interpretação do cursor terminal é uma adaptação experimental ao comportamento observado, não uma garantia contratual da Microsoft. A documentação geral de paginação orienta continuar até não haver nextLink: [paginação Graph](https://learn.microsoft.com/graph/paging). O endpoint permanece beta: [List messages](https://learn.microsoft.com/en-us/graph/api/plannertask-list-messages?view=graph-rest-beta).

## Funcionamento

- Seção expansível **Observações do suporte** no detalhe do chamado. Exibe autor disponível, data/hora local do navegador e texto em ordem cronológica. Todo comentário recuperado pelo endpoint aparece, sem filtro PUBLICO. HTML é convertido em texto e inserido com textContent; conteúdo ativo não é executado.
- Bolinha vermelha com contador nos chamados da lista, nos recentes do dashboard e no resumo da seção. O colaborador tem somente leitura; as rotas aceitam apenas GET e nunca enviam comentários ao Graph.
- As rotas usam a política atual de chamados visíveis antes de consultar o cache ou Graph. Chamados restritos não publicados no Planner não consultam chat. O vínculo precisa pertencer ao plano selecionado; a tarefa remota também é verificada antes da leitura.
- Atualização a cada 120 segundos enquanto a aba estiver visível. O lote devolve somente IDs e atualidade; cada requisição atualiza no máximo uma tarefa. Durante o primeiro carregamento de vários chamados, novas requisições em intervalos de 5 segundos preenchem o cache gradualmente. O conteúdo é consultado ao abrir a seção e atualizado enquanto ela permanece aberta.
- Usa fetch JSON integrado à página existente; o listener `htmx:afterSwap` atualiza os indicadores quando houver swaps, sem substituir os fluxos HTMX atuais. Não há Celery worker novo obrigatório.
- Cache compartilhado Django/Redis válido por 120 segundos e retido por até uma hora para falhas temporárias. Chave inclui conta, tenant, escopos, plano e tarefa. Trava evita consultas simultâneas da mesma tarefa. Falta de cache impede consultas remotas sem controle.
- Em 429, cooldown compartilhado respeita Retry-After; demais erros usam espera de pelo menos 120 segundos quando não há intervalo informado. Erros não impedem a abertura do chamado; a seção informa indisponibilidade e pode preservar a última consulta válida.
- Limites defensivos: 20 chamados por lote; 25 páginas, 2.000 mensagens, aproximadamente 12 segundos e o limite existente de 64 KiB por resposta Graph. Links de continuação devem ter origem HTTPS exata, mesmo caminho e somente skiptoken. Coleções incompletas por falha/limite não são exibidas como sincronização bem-sucedida nem marcadas como lidas.

## Controle de leitura

O valor salvo é exclusivamente o ID da última mensagem visualizada. Chave: `cmais:observations:v1:<usuario>:<chamado>`. O conteúdo, contagem e horário não são gravados em localStorage.

Sem marcador, as mensagens disponíveis são consideradas não visualizadas. Abrir listagem, dashboard ou detalhe com a seção fechada não marca leitura. A seção deve estar aberta, a aba visível e o início do conteúdo na viewport para registrar a última mensagem exibida. Uma resposta com erro não avança o marcador. Outra mensagem após esse ID faz reaparecer a notificação.

Se o ID salvo desaparecer por exclusão/retenção, aparece a bolinha sem contagem até a seção ser aberta; isso evita classificar todo o histórico antigo como novo. Se localStorage estiver bloqueado, usa memória durante a página e avisa que a leitura não persistirá. Abas do mesmo usuário acompanham o evento storage; navegadores/dispositivos não compartilham leitura.

## Arquivos

- `apps/planner_integration/observations.py`: ativação, transporte paginado, normalização, cache e erros.
- `apps/tickets/observation_views.py` e `urls.py`: leitura individual e resumos autorizados.
- `config/settings/base.py`: flag desligada por padrão e contexto de templates.
- `templates/tickets/_observations.html` e `_observation_badge.html`: seção e indicador reutilizável.
- `templates/base.html`, `tickets/detail.html`, `tickets/list.html`, `portal/dashboard.html`: integração com o redesign existente.
- `static/js/observations.js` e `static/css/observations.css`: leitura, atualização automática e apresentação responsiva.
- `compose.observations.isolated.yaml`: override opcional que habilita somente a flag no web isolado.
- `tests/test_planner_observations.py`, `tests/observations-state.test.cjs`, `tests/test_observations_browser.py` e `scripts/validate-observations-ui.mjs`: testes do backend, estado e navegador.

## Testes e evidências

- **Real:** OAuth delegado, localização da tarefa pelo Graph, GET HTTP 200, recuperação paginada e normalização de uma mensagem. Sem impressão de conteúdo, segredos ou tokens.
- **Mocks:** 28 testes de backend para ordem, paginação, HTML, exclusão, vazio, falhas, cache/lock, 429, plano divergente, limites e autorização.
- **JavaScript:** cinco testes Node para primeira leitura, persistência, separação usuário/chamado, novos IDs, ID removido, storage bloqueado e quota esgotada com leitura ainda permitida.
- **Navegador real, API simulada:** um teste Edge headless em servidor/banco pytest descartáveis. Cobre lista, dashboard, detalhe, leitura persistente, nova mensagem, viewport de 390 px, texto seguro, vazio, HTTP 503 e storage bloqueado. Capturas sintéticas em `.tmp/observations-ui/`. Esse teste não comprova implantação na porta 8010.
- Ruff aprovado; verificações de sintaxe JS e `git diff --check` aprovadas; `makemigrations --check --dry-run --settings=config.settings.test` informou `No changes detected`.
- A primeira suíte geral encontrou uma falha preexistente em `test_isolated_services_share_localhost_and_disabled_integrations`: o teste exige OAuth desativado, mas `compose.isolated.yaml` já tem os dois flags OAuth/Graph em true no HEAD. O arquivo foi preservado sem alterações. A execução final com esse único teste excluído terminou com **574 passed, 5 skipped, 1 deselected em 86,01 s**. O navegador foi executado explicitamente à parte, portanto seu skip na suíte padrão não representa falta de validação. Três outros skips exigem PostgreSQL descartável e um é o navegador de formulários, fora desta funcionalidade.

Para repetir:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_planner_observations.py -q
node --test tests/observations-state.test.cjs
$env:RUN_OBSERVATIONS_BROWSER='1'
.\.venv\Scripts\python.exe -m pytest tests/test_observations_browser.py -q
```

O teste de navegador usa Edge já instalado e acesso apenas ao servidor pytest local, com requisições externas bloqueadas. Não usa credenciais Microsoft ou dados da homologação.

## Como testar posteriormente na porta 8010

Não foi feito deploy nesta tarefa. Os comandos abaixo são instruções para uma publicação futura e consciente somente em homologação:

```powershell
docker compose --env-file .env.isolated -f compose.isolated.yaml -f compose.oauth.isolated.yaml -f compose.observations.isolated.yaml build web
docker compose --env-file .env.isolated -f compose.isolated.yaml -f compose.oauth.isolated.yaml -f compose.observations.isolated.yaml up -d --no-deps web
```

Não executar `down -v`. Nenhum comando de migrations é necessário. O override habilita PLANNER_OBSERVATIONS_ENABLED apenas no web; a implementação também exige PORTAL_BASE_URL exatamente no localhost/127.0.0.1:8010 e OAuth delegado aprovado. O compose padrão/porta 8000 não foi alterado.

1. Acessar `http://localhost:8010` como colaborador e usar um chamado fictício já vinculado a uma tarefa existente do plano selecionado. A tarefa de teste localizada nesta análise não foi automaticamente vinculada a nenhum chamado do portal.
2. Como técnico, adicionar uma observação no Planner da tarefa vinculada. Aguardar a sincronização (normalmente até 120 segundos, mais preenchimento inicial do cache em listas).
3. Conferir bolinha/contador em Meus chamados, recentes do dashboard e detalhe, com a seção fechada.
4. Abrir Observações do suporte e trazê-la para a tela. Conferir conteúdo, ordem, data e desaparecimento da notificação. Recarregar para conferir persistência.
5. Fechar a seção, acrescentar outra mensagem no Planner e aguardar a próxima sincronização; a bolinha deve reaparecer.
6. Verificar em viewport móvel e com outro usuário, que não deve conseguir consultar as observações do chamado alheio.

## Limitações

Somente Task chat desse endpoint; comentários legados de conversas do Outlook exigem permissões adicionais e não foram integrados. Nenhuma permissão foi alterada. Não há identificação do autor por ID quando displayName não vem da API. O texto mantém o conteúdo textual, mas não reproduz imagens embutidas e formatação rica. Limites defensivos e instabilidades da API beta podem gerar indisponibilidade temporária. A integração continua dependente de consentimento/token válido e acesso da conta técnica ao plano/tarefa.

Não há novos models, tabelas ou migrations. Não foram alterados os fluxos de criação de tarefa, checklist, responsáveis, prazos, status ou login. Nenhum commit, push, deploy ou operação de volumes.
