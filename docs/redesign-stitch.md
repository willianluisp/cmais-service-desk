# Redesign do C+ Service Desk — entrega para revisão

Referência visual oficial: `design/prototipo.html`, fornecido pelo usuário e lido integralmente. Essa referência tem prioridade sobre a direção visual inicial. Foi mantida uma única implementação no checkout atual; a revisão independente foi somente de leitura.

## O que foi implementado

- Menu navy, barra branca, avatar com dados da sessão, ações azuis, cartões, tabelas, formulários e hierarquia visual baseados no Stitch.
- Estilos do protótipo extraídos para `stitch.css`; adaptação dos componentes reais em `stitch-portal.css` e `admin-stitch.css`. Ícones vetoriais do protótipo reunidos em um sprite local. Nenhum JavaScript de simulação foi incorporado.
- Logos oficiais preservadas. O fundo branco ao redor da logo permite sua leitura no menu escuro sem modificar o arquivo.
- Dashboard com métricas, chamados e atalhos de formulários realmente disponíveis para o usuário. Nenhuma empresa, pessoa, chamado ou indicador demonstrativo foi criado no sistema em uso.
- Abertura Empresa → Departamento → Formulário → Informações → Revisão, seleção por cartões, progresso e resumo lateral.
- Retorno às etapas na mesma página preservando os nós dos campos, textos e arquivos selecionados. Os dados não são gravados em localStorage, sessionStorage ou cookies. Escolher outro formulário exige confirmação porque suas perguntas podem ser diferentes.
- Revisão com valores textuais seguros, sem envio antecipado. Alterar etapas anteriores invalida a revisão, exigindo conferência atualizada antes de confirmar.
- Prévia e remoção de anexos, também nos formulários dinâmicos; limites existentes de cinco arquivos, 2 MB por arquivo e formatos PDF/PNG/JPEG preservados.
- Listagens pessoal e administrativa usando a política real de visibilidade. `view=mine` restringe a lista ao solicitante atual e é preservado nos filtros e na paginação.
- Detalhes com informações, respostas de formulário, arquivos privados, comentários públicos existentes, histórico e dados de atendimento reais. Notas internas não aparecem.
- Empresas, departamentos, formulários, usuários e grupos com o mesmo sistema visual e ações administrativas existentes.
- Integração Microsoft organizada em conexão, plano, colunas e automação. Diagnóstico e recuperação de envios continuam disponíveis, com aviso sobre o processamento de chamados antigos ao ativar.
- Minha conta em `/conta/`: somente consulta dos dados e grupos da própria sessão, troca de senha existente e saída por POST.
- Login dividido como no protótipo, recuperação de senha, primeiro acesso, mensagens e páginas de erro em português.
- Navegação mobile com Escape, controle de foco e bloqueio do conteúdo atrás do menu; foco visível, campos identificados, movimento reduzido e controles de toque ampliados.

## Inventário e correspondência com o protótipo

| Tela do Stitch | Implementação real e comportamento preservado |
| --- | --- |
| Login | `/login/`, autenticação local/LDAP e modo desabilitado existentes; formulário e CSRF reais |
| Início | `/`, dados filtrados por `visible_tickets`, formulários publicados autorizados |
| Abertura guiada | `/chamados/novo/`, suporte padrão e formulários publicados; empresa/departamento validados no servidor |
| Meus chamados | `/chamados/?view=mine`, filtro sobre o conjunto já autorizado |
| Todos os chamados | `/chamados/`, visibilidade administrativa existente; acesso a restritos continua condicionado aos grupos reais |
| Detalhes e histórico | `/chamados/<id>/`, anexos privados, eventos públicos, respostas e comentários públicos existentes |
| Formulários | Listagem, editor, prévia, publicação, ordenação, arquivamento, lixeira, restauração e exclusão definitiva existentes |
| Empresas | Cadastro, edição, ativação/desativação e exclusão protegida existentes |
| Departamentos | Cadastro global compartilhado entre empresas, sem duplicação de grupos |
| Usuários | Administração Django existente com criação, edição, senha temporária, estado ativo, grupos e exclusão protegida |
| Grupos e permissões | Administração existente; participantes e autorizações mantidos no backend |
| Microsoft Planner | Conexão/OAuth, configuração protegida, planos, buckets, automação, sincronização, conferência e teste controlado existentes |
| Minha conta | Consulta autenticada dos próprios dados, sem seletor fictício de perfil |
| Recuperação | Lista administrativa de chamados arquivados/excluídos, restauração e confirmação de exclusão permanente |
| Telas extras do sistema | Recuperação/redefinição de senha, primeiro acesso, erros 400/403/404/500/CSRF, exclusões de cadastros e lixeira de formulários com a mesma apresentação |

## Diferenças necessárias entre o protótipo e o backend

1. O protótipo envia comentários e altera a conclusão de chamados por simulação. O backend atual possui registros de comentários, mas não oferece endpoint de envio pelo colaborador nem conclusão manual nesse fluxo. São exibidos os comentários públicos existentes; nenhum botão fictício foi acrescentado.
2. O protótipo associa formulários a departamentos. O sistema real autoriza formulários por grupos e mantém departamentos globais. Essa regra foi preservada.
3. O protótipo exige motivo da exclusão lógica. O fluxo real implementa confirmação e auditoria, sem campo de motivo. O redesign mantém o formulário real e não inventa um dado sem persistência.
4. Não há troca de perfil por seletor, notificações simuladas, credenciais preenchidas, empresas padrão ou sincronização fictícia.
5. Ativação/desativação de cadastros continua sujeita ao salvamento e à validação existentes. Não foram criados toggles que aparentem salvar sem executar o fluxo real.
6. A fonte usa Inter quando disponível e a pilha local Segoe UI/Arial; não foi acrescentado download externo. Algumas áreas de toque e textos auxiliares são maiores ou têm contraste mais forte que o protótipo para melhorar o uso no celular e por teclado.

## Preservação das três melhorias recentes

- Empresa e departamento continuam exigidos e validados; snapshots de empresa e setor nos chamados históricos permanecem intactos.
- Exclusão lógica, cancelamento de filas, auditoria e restauração continuam utilizando os serviços atuais. A manutenção de chamados exige ADMIN_PORTAL no backend.
- Títulos e reconciliação de tarefas Planner não foram alterados. O nome do formulário continua sendo usado conforme a melhoria existente.

## Validação

Os resultados finais estão registrados ao fim deste documento. Os testes Django usam `config.settings.test`, com SQLite em memória. A validação visual usa respostas HTML geradas com dados fictícios e Edge isolado; todas as requisições são interceptadas. Não consulta as portas 8000/8010 nem o tenant Microsoft.

Comandos para reproduzir:

```powershell
.venv\Scripts\python.exe -m pytest -q --tb=line
.venv\Scripts\python.exe manage.py check --settings=config.settings.test
.venv\Scripts\python.exe -m ruff check .
$env:REDESIGN_CAPTURE_DIR='.tmp/redesign-preview'
.venv\Scripts\python.exe -m pytest tests/test_redesign.py -q
node scripts/validate-redesign-ui.mjs
```

O navegador requer Edge e conexão local à porta temporária de depuração do próprio processo. O endereço sintético `localhost:8120` é interceptado; nenhum servidor nessa porta é iniciado ou acessado.

## Como visualizar sem alterar os ambientes existentes

Abra `.tmp/redesign-qa/index.html`, a galeria de capturas desktop/mobile com dados fictícios:

```powershell
Start-Process -FilePath (Resolve-Path '.tmp/redesign-qa/index.html').Path
```

As imagens registram a parte inicial de cada tela; os testes de layout percorrem o documento inteiro. A galeria não é o sistema de produção nem simula salvamento. Os ambientes existentes continuam com sua versão atual até uma atualização futura autorizada. Não iniciar Docker, aplicar migrations ou substituir processos para revisar a galeria.

## Restrições respeitadas e pendências

- Sem commit, push, deploy, migrations em banco em uso, exclusão de dados ou ações reais Microsoft.
- Nenhuma alteração nas logos, credenciais, configurações OAuth/Graph ou arquivos Compose. Nenhuma operação nos serviços 8000/8010.
- Existe uma falha anterior no teste de Compose: ele exige integrações desabilitadas, enquanto `compose.isolated.yaml` já contém flags habilitadas. A falha foi reproduzida antes das alterações e a configuração foi preservada.
- Testes de concorrência com PostgreSQL descartável e o teste antigo opcional de navegador permanecem fora desta execução. A nova verificação Edge cobre os fluxos de interface descritos abaixo.
- Homologação com pessoas usuárias, tecnologia assistiva e tenant Microsoft real continua sendo uma etapa posterior. Não é declarada certificação formal WCAG nem validação de produção.

## Arquivos modificados e adicionados

```text
apps/accounts/admin.py
apps/core/urls.py
apps/core/views.py
apps/sectors/intake.py
apps/tickets/views.py
design/prototipo.html
docs/redesign-stitch.md
docs/superpowers/plans/2026-11-09-portal-redesign.md
scripts/validate-redesign-ui.mjs
static/css/admin-cmais.css
static/css/admin-stitch.css
static/css/forms.css
static/css/redesign.css
static/css/stitch-portal.css
static/css/stitch.css
static/js/admin-experience.js
static/js/attachments.js
static/js/experience.js
static/js/portal.js
static/js/request-flow.js
static/ui-icons.svg
templates/400.html
templates/403.html
templates/403_csrf.html
templates/404.html
templates/500.html
templates/accounts/account.html
templates/accounts/auth_base.html
templates/accounts/first_access.html
templates/accounts/login.html
templates/accounts/password_form.html
templates/accounts/password_reset_done.html
templates/admin/auth/group/change_list.html
templates/admin/auth/user/change_list.html
templates/admin/base_site.html
templates/base.html
templates/companies/delete.html
templates/companies/form.html
templates/companies/manage.html
templates/custom_forms/_request_fields.html
templates/custom_forms/choose.html
templates/custom_forms/editor.html
templates/custom_forms/intake_selection.html
templates/custom_forms/manage.html
templates/custom_forms/ordering.html
templates/custom_forms/request.html
templates/includes/icon.html
templates/includes/intake_progress.html
templates/includes/intake_summary.html
templates/includes/navigation.html
templates/includes/request_context.html
templates/includes/request_review.html
templates/includes/topbar.html
templates/portal/_quick_access.html
templates/portal/dashboard.html
templates/portal/integrations.html
templates/sectors/delete.html
templates/sectors/form.html
templates/sectors/manage.html
templates/tickets/archived.html
templates/tickets/create.html
templates/tickets/detail.html
templates/tickets/list.html
templates/tickets/permanent_delete.html
templates/tickets/soft_delete.html
tests/test_homologation_improvements.py
tests/test_redesign.py
```

## Resultados finais

- Suíte completa: **540 aprovados, 4 ignorados e 1 falha pré-existente**, em 87,19 s. Falha: `tests/test_compose.py::test_isolated_services_share_localhost_and_disabled_integrations`. O resultado anterior ao redesign era 529 aprovados, 4 ignorados e a mesma falha.
- Testes novos de navegação, seleção, títulos, conta, escopo pessoal, comentários e estrutura das telas: **11 aprovados**. Os testes de captura também foram executados com exportação dos HTMLs sintéticos.
- Testes focados finais de redesign e gestão de usuários: **30 aprovados**.
- `manage.py check --settings=config.settings.test`: **sem problemas**.
- `ruff check .`: **aprovado**.
- `git diff --check`: **aprovado**.
- Logos, configurações, flags e Compose: nenhuma alteração no diff.
- SHA-256 do protótipo canônico idêntico ao arquivo fornecido em Downloads: `509F9445AA5AC6EE2E8EDB9B7D31E25E6DBBF6D853B2F140BA617C75060EB99D`.

- Edge isolado: **46 telas/estados × 4 larguras = 184 verificações de layout**, em 360, 390, 1366 e 1920 px; aprovado.
- Sem overflow horizontal da página, imagens quebradas, IDs duplicados, marcação indevida no título ou controles de seleção com largura incorreta.
- Interações aprovadas: menu e Escape, foco, revisão sem POST, texto tratado sem executar HTML, envio único, retorno por todas as etapas com texto e FileList preservados, invalidação de revisão antiga, anexos dinâmicos com remoção e foco correto, confirmação/cancelamento administrativos e inclusão de campo no construtor.
- Requisições externas durante a validação: **nenhuma**. Resultados em `.tmp/redesign-qa/results.json`; galeria em `.tmp/redesign-qa/index.html`.
- Inspeção visual das capturas desktop e mobile realizada; corrigidos controles de seleção, adaptação de listas e aparência dos cartões administrativos.

A entrega está pronta para revisão de código e homologação autorizada posterior. A falha pré-existente de Compose e as funcionalidades simuladas sem endpoint real permanecem registradas; não é declarado sucesso de produção nem aprovação formal de acessibilidade.
