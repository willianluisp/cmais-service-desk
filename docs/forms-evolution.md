# Evolução dos formulários C+ — implantação e operação

## Estado da entrega

Implementação no código. Nenhuma migration ou provisionamento foi executado no banco
existente; nenhum setor oficial foi presumido; nenhum formulário foi publicado.
Flags Microsoft, AD/Entra, integrações, containers e volumes existentes não foram alterados.
Os testes usam somente bancos e dados fictícios descartáveis.

## Campos globais e setores

**Em qual setor você trabalha?** e **Onde o atendimento deverá ser realizado?** aparecem
primeiro e são obrigatórios em toda abertura, incluindo suporte padrão e formulários
publicados antes desta versão. O servidor insere e valida essas perguntas; não dependem
do JSON editável pelo administrador. O construtor as mostra como campos fixos.

A lista oficial começa vazia. Em **Administração → Gerenciar setores**, cadastrar os
nomes definidos pela empresa, editar, ativar/desativar e escolher a ordem numérica.
Setores inativos não aceitam novos envios; setor usado pelo contexto de um chamado
não pode ser excluído. Ausência de setores ativos impede novos envios e mostra uma
mensagem para solicitar o cadastro, sem criar nomes fictícios.

O chamado guarda o ID e uma cópia do nome do setor, além da localização, em
`TicketIntakeContext`. O evento de abertura também registra esse contexto. Renomear
um setor não modifica as solicitações anteriores. Chamados antigos sem contexto
permanecem intactos e continuam acessíveis pelas regras existentes.

Perguntas antigas equivalentes são unificadas na apresentação e recebem o valor global
no snapshot da nova resposta quando seu ID ainda pertence à publicação anterior.
O reconhecimento usa rótulos explícitos, normalizados sem acentos/pontuação, como
"Setor", "Setor do colaborador", "Departamento", "Localização do atendimento" e as
perguntas oficiais. Não confunde **Setor do colaborador desligado** com o solicitante.
Nenhum snapshot antigo é reescrito. Ao salvar pelo editor, os equivalentes já unificados
deixam a lista de perguntas editáveis; as perguntas globais continuam fixas.

## Editor e ordenação

Todos os rascunhos/publicados podem ser editados: nome, descrição, ícone, perguntas,
tipos, obrigatoriedade, ajuda, placeholders, opções, padrões, grupos e publicação.
Campos podem ser adicionados, removidos, duplicados com novo UUID, arrastados ou movidos
por setas. Há prévia do rascunho sem gravar, aviso ao sair sem salvar e revisão contra
edições concorrentes. Arquivados oferecem **Retomar edição como rascunho**. A lixeira,
restauração e exclusão definitiva protegida continuam disponíveis.

Os tipos novos são **Inteiro positivo**, **Setor oficial** e **Data e hora**. Inteiros
admitem 1 a 2147483647; número decimal existente mantém sua validação anterior. Data e
hora usam o fuso configurado America/Sao_Paulo e widget datetime-local.

Em **Gerenciar formulários → Ordenar cards**, arrastar ou usar setas e clicar
**Salvar ordem dos cards**. A ordem fica no PostgreSQL, é aplicada imediatamente sem
republicar e permanece após reinícios. Alteração concorrente ou lista obsoleta é rejeitada.
Rascunhos/arquivados reservam sua posição, mas só publicações disponíveis são mostradas.
A ordem numérica dos metadados serve como posição inicial para itens novos; após salvar,
a organização visual tem precedência. Grupos filtram o conjunto visível sem mudar sua ordem.

O campo de disponibilidade já permite selecionar vários grupos. Para formulários restritos,
uma participação em qualquer grupo selecionado é suficiente; múltiplas participações não
duplicam o card. Sem grupos selecionados, formulários comuns mantêm a opção pública aos
colaboradores autenticados, compatível com as configurações anteriores. ADMIN_PORTAL e
superusuários também acessam publicações comuns de outros grupos. Gerentes/supervisoras
não recebem administração por seus títulos ou grupos de gestão. Essa exceção administrativa
não se aplica aos formulários ou chamados sensíveis, nem concede aprovação de desligamentos.

O suporte padrão ocupa a chave única `standard`. Antes da primeira publicação do preset
de suporte, o formulário legado continua disponível na transição, com os dois globais.
Publicar **Suporte de TI** adapta o mesmo card e a mesma URL; não há card duplicado.
A partir da publicação, suas restrições, despublicação, arquivamento e lixeira são respeitados
também na URL legada. Um usuário fora da audiência não recebe um suporte genérico alternativo.

## Desligamento e solicitações sensíveis

O preset de desligamento nasce sensível, em rascunho, sem grupos presumidos. Publicar
exige selecionar grupos existentes explicitamente autorizados para solicitar/consultar
e grupos responsáveis pela aprovação. Não há associação automática a RH/DP ou ADMIN_PORTAL.
Uma vez habilitada, a classificação sensível não pode ser removida; cópias a preservam.

O chamado recebe os vínculos de grupos daquela publicação. Somente membros atuais dos
grupos de acesso ou de aprovação consultam lista, detalhes e anexos. Isso inclui o
solicitante: perder o grupo revoga a consulta, preservando os dados. ADMIN_PORTAL,
superusuário ou toda a equipe de TI não recebem leitura automática de chamados sensíveis.
A administração dos formulários continua autorizada aos papéis administrativos existentes.
Arquivamento e exclusão de chamados repetem essa política além da autorização administrativa.

O responsável pela solicitação é a identidade autenticada do portal. A aprovação aparece
nos detalhes para membros do grupo aprovador e exige confirmação por outra pessoa
autenticada. Guarda aprovador, nome histórico, data e referência; declaração do solicitante
ou texto preenchido em uma pergunta não concede aprovação. O registro é idempotente,
com evento e auditoria, e fica preservado até uma exclusão explícita autorizada do chamado.

Não há bloqueio de contas, revogação, compra ou instalação automática. Aprovar não dispara
ações externas. Chamados sensíveis não entram nas filas de Planner/e-mail, e consumidores
também bloqueiam sincronização, publicação de anexos e notificações de registros sensíveis.
Detalhes do desligamento permanecem no portal, sem publicação em Microsoft Graph.
Os demais chamados conservam o fluxo e as permissões existentes.

## Migrations novas — pendentes de autorização

| Migration | Alterações |
| --- | --- |
| `sectors.0001_initial` | Setores oficiais, unicidade do nome e contexto histórico por chamado. Sem seed. |
| `custom_forms.0003_forms_evolution` | Chave única de provisionamento, classificação sensível, grupos aprovadores e ordem dos cards com revisão. |
| `tickets.0006_sensitive_tickets` | Classificação e grupos restritos/aprovadores por chamado; registro de aprovação autenticada. |

São alterações de schema. Não há migration de dados ou preenchimento retroativo do setor,
publicação, modificação de respostas, substituição de schemas ou criação de setores/grupos.
Se ainda pendentes, as migrations das entregas anteriores também aparecerão em `migrate --plan`.
Não aplicamos nenhuma delas ao ambiente existente nesta tarefa.

## Atualizar somente o ambiente isolado 8010, depois da autorização

1. Fazer o backup normal do PostgreSQL e dos anexos conforme [backup](private-attachments.md).
2. Usar o projeto isolado e **o mesmo conjunto de overrides já autorizado e em uso**,
   preservando credenciais e liberações atuais. Não acrescentar overrides de Microsoft
   que ainda não tenham aprovação. Os exemplos usam apenas o Compose base isolado.
3. Construir, revisar e, somente após autorização, aplicar as migrations com um web
   temporário. Atualizar apenas o web de 8010, mantendo db/redis e os volumes.

```powershell
$isolatedComposeArgs = @(
    '--project-name', 'cmais-service-desk-isolated',
    '--env-file', '.env.isolated',
    '-f', 'compose.isolated.yaml'
)
# Se a implantação já usa overrides, acrescentar os mesmos -f ao array acima.
docker compose @isolatedComposeArgs build web
docker compose @isolatedComposeArgs run --rm --no-deps web python manage.py migrate --plan

# Executar as duas linhas seguintes somente depois da autorização para implantação.
docker compose @isolatedComposeArgs run --rm --no-deps web python manage.py migrate --noinput
docker compose @isolatedComposeArgs up -d --no-deps web
```

O `run` usa a imagem atualizada sem publicar uma nova porta. Não usar o projeto da
porta 8000, `compose.yaml`, `down -v`, prune ou comandos que removam volumes.
Os comandos acima não foram executados no ambiente existente.

Depois da atualização, cadastrar a lista oficial de setores na interface antes de
liberar novas aberturas. Chamados antigos não dependem desse cadastro para consulta.

## Provisionamento inicial — somente após sua aprovação

Com migrations e imagem atualizadas, usar o login real do administrador responsável
no lugar de `LOGIN_ADMIN` (o comando não pede nem recebe senha):

```powershell
# Leitura: revisar o que falta, sem gravar.
docker compose @isolatedComposeArgs run --rm --no-deps web python manage.py provision_cmais_forms --actor LOGIN_ADMIN --dry-run

# Gravação: executar somente depois de aprovar o provisionamento inicial.
docker compose @isolatedComposeArgs run --rm --no-deps web python manage.py provision_cmais_forms --actor LOGIN_ADMIN
```

Cria como **rascunho**, com campos editáveis:

1. Suporte de TI (adapta o card padrão quando publicado).
2. Acessos e Permissões.
3. Impressoras e Scanners.
4. E-mail e Microsoft 365.
5. Solicitação de Equipamentos.
6. Instalação de Programas.
7. Desligamento de Colaborador (sensível, sem grupos definidos).

Chaves `provision_key` e UUIDs das perguntas são estáveis. Repetir o comando preserva
integralmente qualquer preset existente, inclusive alterações, publicação, arquivamento
ou lixeira. Não cria setores, grupos ou cards adicionais de suporte. A transação impede
entregas parciais e audita somente os registros novos. Não existe execução automática
no startup nem migration de dados que sobrescreva personalizações.

Em **Gerenciar formulários**, abrir cada rascunho, revisar perguntas e prévia, escolher
disponibilidade e publicar. Para desligamento, primeiro configurar ambos os conjuntos
de grupos autorizados; sem isso a publicação é bloqueada. Depois, usar **Ordenar cards**.

## Arquivos desta evolução

- `apps/sectors/` e `templates/sectors/`: modelos, migration, CRUD, auditoria e helpers globais.
- `apps/custom_forms/models.py`, `schema.py`, `forms.py`, `services.py`, `views.py`, `urls.py`:
  edição, tipos novos, snapshots, proteção e integração.
- `apps/custom_forms/globals.py`, `ordering.py`, `presets.py` e
  `management/commands/provision_cmais_forms.py`: unificação, ordem e provisionamento.
- `apps/custom_forms/migrations/0003_forms_evolution.py`.
- `apps/tickets/models.py`, `services.py`, `forms.py`, `permissions.py`, `views.py`,
  `approvals.py`, `urls.py`, `lifecycle.py`, `lifecycle_views.py` e migration `0006_sensitive_tickets.py`.
- `apps/notifications/services.py` e `apps/planner_integration/services.py`, `tasks.py`,
  `attachments.py`: bloqueios defensivos de dados sensíveis, sem alterar flags.
- `templates/base.html`, templates custom_forms de edição/cards/ordem/lixeira e
  tickets de abertura/detalhes, `static/css/forms.css`, `static/js/form-builder.js`,
  `form-ordering.js`: interface e navegação.
- `config/settings/base.py`, `config/urls.py`: registro de setores.
- `tests/test_sectors.py`, `test_form_presets.py`, `test_forms_evolution.py`, fixtures,
  testes anteriores de abertura adaptados para enviar os globais obrigatórios e
  `scripts/validate-custom-forms-ui.mjs`: validação automatizada real.

Os arquivos de funcionalidades entregues anteriormente permanecem no workspace, sem commit.

## Validação final

**473 testes aprovados**, sem skips, na suíte completa usando PostgreSQL 17 descartável.
Inclui setores, validação e histórico dos globais, presets e idempotência, privacidade
de desligamento e anexos, aprovação autenticada, proteção de consumidores externos,
ordenação concorrente e migrations preservando dados fictícios antigos.
O navegador Edge exercitou desktop/celular, edição de setor, duplicação de pergunta,
publicação, ordenação dos cards, envio, lixeira, restauração, retomada de edição de
arquivado e confirmação de exclusão definitiva.

Ruff, Django check, makemigrations --check, sintaxe JavaScript e diff --check aprovados.
A revisão independente identificou um fallback indevido do suporte restrito, corrigido
com teste de regressão; a revisão final não apontou pendências relevantes. O PostgreSQL
descartável foi encerrado, mantendo os containers existentes de 8000 e 8010 ativos.

## Complemento incremental — acesso por múltiplos grupos

A seleção múltipla, a relação de grupos e a regra de interseção já existiam e foram
reutilizadas. O único acréscimo funcional foi permitir a ADMIN_PORTAL/superusuários
abrir e enviar publicações comuns de outros grupos, usando a mesma política nos cards,
na URL e na gravação. Rascunhos/lixeira continuam fora das aberturas; desligamentos e
aprovações mantêm suas exigências de grupos designados. Nenhum papel de gestão recebeu
privilégios administrativos e nenhuma associação de usuário/grupo foi alterada.

O texto de ajuda do seletor foi esclarecido. Foram adicionados 12 testes de autorização,
interseção entre grupos, edição/publicação, ausência de duplicação, revogação, gestores
sem administração e preservação do fluxo sensível. A suíte completa passou em
**485 testes**, sem skips, no PostgreSQL descartável, incluindo navegador. Ruff, Django
check e makemigrations --check aprovados. Nenhuma migration nova; as três migrations
da evolução continuam pendentes de autorização, sem provisionamento no banco existente.
