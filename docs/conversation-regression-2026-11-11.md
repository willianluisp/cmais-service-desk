# Regressão da conversa — 11/11/2026

## Evidência e causa

O diagnóstico somente leitura executado pelo operador em `/opt/cmais-service-desk`
no Debian confirmou o checkout `fcb1b23`, com alteração local em
`config/settings/base.py`. Na imagem web ativa:

- `apps.planner_integration.observations` não existe;
- o context processor de observações não está registrado;
- os templates de detalhe e base não referenciam observações;
- `PLANNER_OBSERVATIONS_ENABLED=false`;
- Graph está aprovado, com OAuth delegado habilitado;
- todos os serviços Docker estão saudáveis;
- `TicketComment` tem zero registros, inclusive internos.

O commit `8eea513` registrou o context processor, mas não incluiu os arquivos da
funcionalidade. O commit `9accd3e` removeu o registro por ausência do módulo.
No checkout de trabalho os módulos, templates e assets já existem, mas vários
continuam sem rastreamento Git. Publicar apenas as alterações rastreadas não leva
a funcionalidade completa ao servidor. A saúde do processo e uma tarefa `LINKED`
não verificam a presença ou a leitura da conversa.

Também foi reproduzida uma segunda barreira no leitor existente: `enabled()`
aceitava apenas `http://localhost:8010`, desabilitando o domínio HTTPS real mesmo
com todas as flags autorizadas.

## Correção local

Restaurado o context processor e permitido o leitor existente em origens HTTPS,
mantendo todas as aprovações explícitas e o OAuth delegado. O HTTP continua
limitado à homologação local 8010. URLs com credenciais, query ou fragmento não
habilitam o leitor. As flags permanecem desabilitadas por padrão.

Não foi criado um chat, endpoint de envio, modelo, migração ou nova persistência.
As observações existentes continuam sendo lidas do chat da tarefa no Planner,
com cache Django/Redis; `TicketComment` continua com sua exibição local e seu
filtro `is_internal=False`. Nenhuma mensagem foi apagada, copiada ou editada.
O histórico Git disponível não contém um endpoint Django de envio de comentários;
o botão `sendComment` encontrado no protótipo altera somente um array em memória.
Isso não prova qual interface ou versão foi utilizada anteriormente no servidor.

As melhorias de nomes dos responsáveis e do botão Atualizar status foram
preservadas. A sincronização e a criação de tarefas não foram modificadas.

## Arquivos necessários numa publicação futura

Este diagnóstico não autoriza nem executa uma publicação. Quando ela for
autorizada separadamente, a versão precisa conter todo o fluxo existente:

- `apps/planner_integration/observations.py`;
- `apps/tickets/observation_views.py` e suas rotas em `apps/tickets/urls.py`;
- registro em `config/settings/base.py`;
- `templates/tickets/_observations.html` e `_observation_badge.html`;
- referências nos templates `base.html`, `tickets/detail.html`, `tickets/list.html`
  e `portal/dashboard.html`;
- `static/js/observations.js` e `static/css/observations.css`;
- demais arquivos das melhorias anteriores, incluindo `assignees.py`.

Não basta recolocar o context processor numa imagem sem o módulo: isso impediria
a renderização dos templates. A configuração efetiva do web também precisaria
habilitar `PLANNER_OBSERVATIONS_ENABLED`, preservar as aprovações já existentes e
usar a origem HTTPS correta. Não se alterou `.env`, Compose ou qualquer serviço.

O endpoint Microsoft usado pelo leitor continua em beta; a Microsoft não oferece
suporte de produção para APIs beta. Essa limitação já pertence à integração
existente e não foi substituída por outra arquitetura:
https://learn.microsoft.com/en-us/graph/api/plannertask-list-messages?view=graph-rest-beta

## Regressão e validação

`tests/test_conversation_regression.py` reproduziu a ausência de contexto e,
após restaurá-lo, isolou a restrição indevida ao localhost. Cobre a página real,
assets, leitura JSON, retenção dos comentários locais, filtro de internos, acesso
por chamado, origem HTTPS e flags desativadas. O Graph é simulado e o banco é
descartável. Testes de navegador existentes cobrem leitura, atualização, falhas,
storage, responsividade e a ação de status.

Nenhum comando executado pelo agente alterou o Debian. O operador executou apenas
diagnóstico, com a consulta de contagens dentro de transação PostgreSQL somente
leitura. O token da homologação local estava expirado; ele não foi renovado nem
utilizado para afirmar que a API Microsoft funciona atualmente em produção.
