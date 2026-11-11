# Observações do suporte — diagnóstico técnico

> Histórico do diagnóstico inicial. A tarefa fictícia foi disponibilizada posteriormente, o GET real de mensagens retornou HTTP 200 e a implementação foi concluída no código. Consulte [a entrega e validação atualizadas](planner-observations.md). As pendências abaixo descrevem o estado anterior à implementação.

Data: 10/11/2026. Atualizado após autorização de uso experimental da API beta em homologação. Etapa 2 pendente de tarefa fictícia acessível para validar a leitura real de mensagens.

## Validação real após autorização

O usuário autorizou continuar sem confirmações intermediárias, usar beta experimentalmente em 8010 e executar GET em tarefa fictícia existente. A restrição de não fazer deploy permanece.

Resultados observados no contêiner isolado, usando o fluxo OAuth delegado existente:

| Verificação | Resultado real |
| --- | --- |
| Estratégia e conexão | Delegated, Graph aprovado, conexão ativa cadastrada com Tasks.ReadWrite |
| Tarefa registrada em PlannerTestAttempt | Um registro CREATED; GET da tarefa retornou HTTP 404 |
| Listagem de tarefas do plano selecionado | Sucesso pelo Graph; nenhuma tarefa com o título oficial `[TESTE C+ SERVICE DESK] <UUID>` |
| Busca de outros títulos de teste no plano | Nenhum título contendo teste, fictício ou homologa |
| Chamados locais com título teste e vínculo Planner | Dois; ambos retornaram HTTP 404 no GET da tarefa |
| GET beta de mensagens | Não executado: nenhuma tarefa fictícia acessível confirmada |

A autenticação e a leitura de tarefas do plano funcionam de verdade. HTTP 404 ao consultar os vínculos não comprova exclusão: também pode representar recurso inacessível. A conclusão é que os vínculos de teste encontrados não oferecem uma tarefa utilizável para a validação. Não há evidência de 403 do endpoint de mensagens ou de rejeição de Tasks.ReadWrite por esse endpoint.

O script temporário de validação usa somente GET no Graph, valida o plano e o título oficial antes de consultar mensagens e imprime apenas resultados sanitizados. Não cria tarefas, não envia mensagens e não imprime tokens, segredos ou conteúdo de chamados. Foi executado por stdin no contêiner já existente, sem copiar código para a imagem, reconstruir ou reiniciar serviços. A renovação de token, quando necessária, usa o provider existente; não houve mudança manual de credenciais ou permissões.

Não foi implementada interface, notificação, localStorage ou sincronização de mensagens, pois o usuário condicionou essa implementação ao funcionamento real da API. Não foram criados testes da funcionalidade inexistente. Os testes existentes de transporte Planner e OAuth delegado foram executados com mocks, sem chamadas reais à Microsoft:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_planner.py tests/test_graph_delegated_oauth.py -q
52 passed in 7.92s
```

Esses 52 testes não validam a API beta, conteúdo de mensagens, notificações ou comportamento móvel. Não há funcionalidade nova disponível para testar na interface de 8010 nesta entrega.

Próximo requisito externo: uma tarefa realmente fictícia, acessível à conta técnica no plano selecionado. Sua criação não foi realizada: a autorização atual para validar mensagens foi condicionada a uma tarefa existente. Depois disso, repetir o GET controlado de mensagens, avaliar o resultado sem presumir permissões, implementar e testar se a leitura funcionar. O uso beta em homologação já foi autorizado e não exige nova confirmação.

## Resultado

A arquitetura existente permite reaproveitar o OAuth delegado da conta técnica, sem conceder acesso ao Planner aos colaboradores. Entretanto, não foi possível confirmar compatibilidade das permissões atuais com a leitura do novo chat. A leitura das conversas antigas exige permissões ausentes na conexão registrada. Nenhuma funcionalidade de produto foi implementada.

Não confundir as duas fontes: comentários antigos e Task chat são recursos diferentes. Ler somente conversas antigas não atende ao objetivo de acompanhar novas mensagens no Planner moderno.

## Evidências locais

- `apps/planner_integration/client.py`: transporte Graph com timeout, bloqueio de redirects, limite de resposta e tratamento de 401/403/404/429, incluindo Retry-After. Há clientes de leitura e estratégias client credentials e delegated. Não existe consulta de mensagens.
- `apps/planner_integration/delegated_oauth.py`: solicita openid, profile, offline_access, User.Read e Tasks.ReadWrite; Sites.Selected é opcional para anexos. Tasks.Read e permissões de conversas de grupos não são solicitados.
- `apps/planner_integration/token_providers.py`: conta técnica compartilhada, tokens cifrados e renovação serializada. Não é necessário alterar o login dos colaboradores.
- `apps/tickets/views.py` e `permissions.py`: detalhes e anexos usam consulta de chamados autorizados. A futura rota deve reutilizar essa política, inclusive restrições de chamados sensíveis e regras administrativas existentes.
- O detalhe já utiliza HTMX para atualização de status. O projeto dispõe de cache Redis. A sincronização atual possui controle de concorrência e throttling; não deve ser alterada para implementar leitura de mensagens.

Consulta somente de leitura ao contêiner `cmais-service-desk-isolated-web-1` confirmou publicação em `127.0.0.1:8010`, estratégia delegated, Graph aprovado e OAuth delegado habilitado. A conexão marcada ativa registra os escopos `openid profile Tasks.ReadWrite User.Read email`. O prazo cadastrado do access token já havia expirado na data desta análise; isso não prova revogação, pois há refresh token no fluxo existente.

Na análise inicial não foram acessados ou impressos tokens, segredos ou conteúdo de chamados, nem executadas chamadas autenticadas ao Graph. A validação posterior está registrada acima. Os escopos acima são os metadados persistidos, não uma introspecção de token nem uma verificação de consentimentos no Entra.

## APIs oficiais

### Novo chat da tarefa

Endpoint documentado: `GET https://graph.microsoft.com/beta/planner/tasks/{task-id}/messages`.

A documentação lista apenas Tasks.Read delegado para conta corporativa/escolar, sem permissões superiores declaradas. Application e contas pessoais não são suportadas nesse método. Não foi encontrada uma versão v1.0 documentada desse endpoint. A Microsoft informa que APIs beta podem mudar e não têm suporte para uso em produção.

Resposta: coleção `value` de plannerTaskChatMessage com `id`, `content`, `createdDateTime`, `createdBy`, `messageType`, `editedTime` e `deletedTime`. O nome do autor não é garantido: o exemplo oficial traz apenas o ID. Não expor esse ID ao colaborador. O método suporta paginação por `$skipToken`, sem outros parâmetros OData; ordenar localmente após recuperar as páginas, sem inventar `$orderby`.

Fonte: [List messages](https://learn.microsoft.com/en-us/graph/api/plannertask-list-messages?view=graph-rest-beta) e [plannerTaskChatMessage](https://learn.microsoft.com/en-us/graph/api/resources/plannertaskchatmessage?view=graph-rest-beta).

### Comentários antigos

Consultar a tarefa em `GET /v1.0/planner/tasks/{task-id}` para obter `conversationThreadId`; resolver também o grupo do plano e consultar `GET /v1.0/groups/{group-id}/threads/{thread-id}/posts`.

O método de posts documenta Group-Conversation.Read.All como menor permissão, delegada ou application; alternativas superiores incluem Group-Conversation.ReadWrite.All, Group.Read.All e Group.ReadWrite.All. Nenhuma consta na conexão registrada. A resposta possui `value`, `id`, `createdDateTime`, `body` e remetente em `from`/`sender`, com nome quando disponível.

Fontes: [plannerTask v1.0](https://learn.microsoft.com/en-us/graph/api/resources/plannertask?view=graph-rest-1.0) e [List posts](https://learn.microsoft.com/en-us/graph/api/conversationthread-list-posts?view=graph-rest-1.0).

No Planner moderno, novas mensagens usam Task chat, enquanto comentários antigos permanecem acessíveis em uma conversa do Outlook. Task chat está disponível em planos básicos; não presumir que conversas de planos Premium usam esse endpoint.

Fonte: [Comentários e Task chat no Planner](https://support.microsoft.com/en-us/planner/comment-on-tasks-in-microsoft-planner).

## Impedimentos e próximo passo

1. Tasks.ReadWrite permite leitura de tarefas em geral, mas a página específica de mensagens beta não o declara como permissão superior. Portanto, a ausência de Tasks.Read é uma lacuna de compatibilidade a validar, e não prova de que o servidor necessariamente rejeitará Tasks.ReadWrite.
2. Para eliminar essa dúvida, fazer um GET controlado usando a conta técnica e uma tarefa conhecida, sem enviar mensagens. Esse teste dependerá de token válido e poderá envolver a renovação normal da conexão. Registrar somente status e formato validado, sem conteúdo ou identificadores nos logs. Um 403 ou 404 isolado não comprova a causa: verificar também acesso ao plano/tarefa e disponibilidade do chat.
3. Se Tasks.Read for efetivamente necessário, será preciso autorizar inclusão do escopo e novo consentimento da conta técnica. Não substituir Tasks.ReadWrite, pois a criação de tarefas existente depende dele. Isso não foi executado.
4. A inclusão de comentários antigos exige permissão adicional de conversas de grupos e consentimento correspondente. Isso também não foi executado.
5. O uso experimental do endpoint beta em homologação já foi autorizado. Não apresentar esse caminho como API estável com suporte para produção.

## Estratégia proposta após resolver os impedimentos

- Serviço somente GET, separado de criação/status/checklist. Verificar autorização do chamado antes de acessar cache ou Graph. Task ID deve vir do vínculo persistido, nunca de entrada livre do navegador. Validar o plano esperado.
- Cache compartilhado por tarefa e conexão por aproximadamente 120 segundos, com exclusão mútua, retenção temporária da última resposta válida e sinalização de indisponibilidade. Respeitar Retry-After, aplicar espera crescente em falhas e não consultar o Graph individualmente a cada renderização de card.
- Percorrer paginação com limites de tempo/páginas/tamanho. Validar origem e caminho dos links de continuação antes de transmitir Authorization. Resposta parcial nunca deve atualizar o marcador de leitura ou simular uma lista completa.
- Normalizar e ordenar por data de criação e ID para desempate. Exibir todo comentário recuperado, sem prefixos ou filtros por palavras. Converter HTML em texto seguro, preservando quebras quando possível; não aplicar `safe` a conteúdo remoto. Tratar mensagens excluídas como marcador sem conteúdo removido.
- Seção expansível “Observações do suporte”; HTMX consulta ao abrir e a cada 120 segundos enquanto visível. Listagem e dashboard consultam resumos autorizados em lote e mostram bolinha com contador acessível. Pausar consultas com aba oculta.
- localStorage guarda exclusivamente o ID da última mensagem visualizada, em chave com versão, usuário autenticado e chamado. Nunca gravar conteúdo nem marcar leitura ao carregar listagens. Marcar apenas a última mensagem efetivamente exibida quando a seção está aberta e visível; preservar durante swaps HTMX e coordenar abas com evento storage.
- Sem marcador, apresentar mensagens como não visualizadas. Se o ID salvo desaparecer por exclusão/retenção, não há como reconstruir exatamente a fronteira de leitura usando apenas esse ID. Tratar como leitura indeterminada, sem contador enganoso, até o usuário abrir a seção. Se localStorage falhar, usar estado em memória e informar que a leitura não persistirá.
- Nenhuma tabela, model ou migration nova. Não reutilizar comentários locais como se fossem mensagens do Planner.

## Validação planejada para a etapa 2

Mocks de transporte e OAuth: coleção vazia, conteúdo, autor ausente, ordenação, paginação, links maliciosos, respostas parciais, 401/403/404/429, Retry-After e falhas transitórias. Testes Django para isolamento por usuário, chamados restritos, respostas sem cache público e escape de HTML. Testes de navegador para persistência, marcação apenas após visualização, reaparecimento após nova mensagem, múltiplas abas, localStorage indisponível, HTMX e viewport móvel.

Esses testes da nova funcionalidade ainda não foram criados nem executados: a funcionalidade não foi implementada. Foram realizadas inspeção estática, consulta da documentação oficial, consultas reais de tarefas descritas acima e execução dos 52 testes existentes de Planner/OAuth com mocks.

Para validar futuramente na porta 8010: usar somente o projeto Compose isolado existente; após implantação explicitamente autorizada nesse ambiente, abrir um chamado do próprio usuário, escrever uma mensagem pelo Planner como técnico, aguardar o intervalo de sincronização, conferir indicadores nas três telas, abrir a seção, recarregar e repetir com nova mensagem. Verificar também que outro usuário não consegue consultar a rota. Nenhum desses passos funcionais está disponível nesta entrega de diagnóstico.

## Alterações desta etapa

Somente este documento no conjunto de arquivos versionáveis e um script temporário ignorado em `.tmp/probe_planner_messages.py`. Nenhuma alteração de permissões, configuração de credenciais, autenticação dos colaboradores, schema do banco, volumes, containers, porta 8000 ou interface. O fluxo OAuth existente pode renovar e persistir tokens normalmente. Nenhum commit, push ou deploy.
