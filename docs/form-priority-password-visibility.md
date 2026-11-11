# Prioridade definida pelo TI e visibilidade de senha

Entrega de código em 10/11/2026. Não houve commit, push, deploy, mudança de branch, remoção de volumes ou atualização do ambiente 8000. A homologação 8010 continua com sua imagem anterior até publicação autorizada.

## Verificação preventiva

Foram inspecionados somente metadados e contagens dos oito formulários existentes na homologação: nenhum campo de prioridade foi encontrado nos esquemas de rascunho/publicação dessa base. Não foram lidas respostas de colaboradores nem alterados dados.

No código local ainda não publicado havia um tipo de pergunta `priority`, introduzido na etapa anterior, que podia aparecer no formulário e determinar a prioridade pelo POST. Esse comportamento foi substituído pela configuração administrativa.

Perguntas legadas de tipo priority ou com rótulos inequívocos de prioridade/urgência deixam de aparecer no preenchimento e na paleta. Os demais campos permanecem. Campos legados ocultos continuam preservados na definição quando o administrador salva, e respostas/snapshots históricos não são apagados. Novas submissões não incluem perguntas de prioridade ocultas em seu snapshot de respostas. Rótulos genéricos sobre impacto ou descrição não são tratados como prioridade.

## Configuração e backend

O editor apresenta **Prioridade padrão do chamado** imediatamente abaixo de **Quem pode abrir este formulário?**, usando as classificações já existentes: Baixa, Normal, Alta e Crítica. Não foi criada a classificação Urgente no portal; Crítica corresponde à urgência máxima do Planner.

Ajuda exibida: “A prioridade selecionada será aplicada automaticamente às novas solicitações deste formulário.”

A configuração é salva em `FormDefinition.default_priority` e incluída no snapshot publicado. Salvar rascunho preserva a publicação atual. É necessário publicar para disponibilizar a nova prioridade aos próximos chamados. Duplicar um formulário copia sua prioridade padrão.

A prioridade é determinada exclusivamente no backend pela versão publicada do formulário autorizado. Campos `priority`, `default_priority` e valores `cf_*` de perguntas legadas enviados pelo colaborador não a substituem. Snapshots antigos sem a propriedade usam Normal. O suporte legado ainda não configurado também usa Normal. Alterações administrativas afetam apenas novos chamados: as prioridades já registradas não são reescritas.

Permissões administrativas e públicos dos formulários foram preservados. Um técnico sem a autorização administrativa já existente não ganha acesso de edição por esta funcionalidade.

## Planner

Somente a criação recebe o mapeamento abaixo:

| Portal | Graph priority | Planner |
| --- | ---: | --- |
| Baixa | 9 | Low |
| Normal | 5 | Medium |
| Alta | 3 | Important |
| Crítica | 1 | Urgent |

O Graph aceita prioridade de 0 a 10 e documenta esses valores representativos: [plannerTask](https://learn.microsoft.com/en-us/graph/api/resources/plannertask?view=graph-rest-1.0). O POST continua usando as permissões existentes: [Create plannerTask](https://learn.microsoft.com/en-us/graph/api/planner-post-tasks?view=graph-rest-1.0).

Se o POST com prioridade receber HTTP 400 explícito, o cliente tenta uma única criação mínima sem prioridade. Nesse caso, a rejeição confirma que a criação não foi aceita; não há repetição automática para timeout, resultado ambíguo, 5xx, 429, 401 ou 403. A prioridade do chamado continua preservada no portal mesmo se o campo não puder ser enviado ao Planner.

Não há PATCH periódico de prioridade, nem aplicação do padrão administrativo a tarefas reconciliadas ou já vinculadas. Decisões posteriores do TI no Planner não são sobrescritas por esta configuração. O portal continua guardando a prioridade aplicada na abertura; não foi acrescentada sincronização reversa de prioridade. Responsáveis, status, prazos, checklist e correlação/idempotência existentes foram preservados.

As escritas Planner desta entrega foram validadas com mocks; nenhuma tarefa real foi criada ou modificada nesta execução. A validação real anterior de leitura das Observações permanece documentada em [Observações do suporte](planner-observations.md).

## Mostrar e ocultar senha

Um script/CSS compartilhado aprimora os campos password dos layouts de login, portal, primeiro acesso e administração. Foram cobertas as telas existentes de login, troca obrigatória, alteração com senha atual/nova/confirmação, criação de usuário, redefinição administrativa e redefinição por link. Campos de segredo de outras páginas que já usem password no mesmo layout recebem o mesmo controle; não foram criadas novas telas.

O primeiro acesso já tinha botões textuais: sua estrutura foi reaproveitada e somente o handler duplicado de visibilidade foi substituído. Validação de tamanho, confirmação e troca obrigatória continua no código existente.

Os controles começam ocultos, mostram ícone de olho e alternam para olho riscado quando o conteúdo está visível. Botões type=button têm aria-controls, aria-pressed e rótulos Mostrar senha/Ocultar senha. Clique por ponteiro preserva foco/cursor do campo; ativação por teclado mantém o foco no botão. Valor e autocomplete não são alterados. Ao retornar pelo histórico com pageshow, a apresentação volta a password.

A senha temporária gerada no cadastro administrativo antes usava TextInput somente leitura. Seu widget agora é PasswordInput com render_value, conservando a geração, o valor somente leitura e as regras existentes, mas ocultando a apresentação inicial. O administrador pode revelá-la para realizar a entrega segura já prevista no fluxo.

O novo componente não grava em localStorage/sessionStorage, não faz requisições e não registra valores em logs ou console. Não altera a autenticação ou validadores.

## Arquivos desta etapa

- `apps/custom_forms/models.py` e `migrations/0004_formdefinition_default_priority.py`: configuração persistente, aditiva, com padrão Normal.
- `apps/custom_forms/forms.py`, `globals.py`, `services.py`, `views.py`: validação/configuração, ocultação de campos legados, persistência/publicação e prioridade no servidor.
- `templates/custom_forms/editor.html`: controle imediatamente após audience e instruções atualizadas.
- `apps/planner_integration/client.py`, `services.py`: prioridade somente na criação e fallback após rejeição explícita.
- `apps/accounts/admin_forms.py`: apresentação inicialmente oculta da senha temporária gerada.
- `static/js/password-visibility.js`, `static/css/password-visibility.css`, `templates/includes/password_visibility_assets.html` (novos): controle compartilhado.
- `templates/base.html`, `accounts/auth_base.html`, `accounts/first_access.html`, `admin/base_site.html`: carregamento dos assets.
- `static/js/first-access.js`: removido somente o handler de visibilidade substituído pelo componente compartilhado.
- `tests/test_form_default_priority.py`, `tests/test_password_visibility_browser.py`, `scripts/validate-priority-password-ui.mjs` (novos): backend, migration e navegador.
- `tests/test_configurable_subject.py`, `tests/test_manual_form_fields.py`, `tests/test_full_homologation.py`: expectativas de prioridade administrativa e simulador Graph atualizados.
- Este documento e `docs/superpowers/plans/2026-11-10-priority-password.md` (novos): registro e plano.

## Migration e preservação

Foi criada uma única migration: **custom_forms.0004_formdefinition_default_priority**. Ela acrescenta a coluna com default NORMAL; não altera tickets, respostas, campos JSON, público, snapshots publicados ou prioridades históricas. Foi aplicada e revertida somente nos bancos descartáveis dos testes. Não foi aplicada ao banco da homologação nem ao ambiente 8000.

Um teste específico parte da versão 0003 com formulário/pergunta/resposta e chamado Crítica; após migrar, confirma Normal no novo atributo e todas as informações anteriores intactas. Os 15 arquivos protegidos de Observações e navegação desta etapa tiveram hashes SHA-256 idênticos antes/depois. Assunto configurável e permissões foram cobertos novamente pela suíte de regressão.

## Validação

Resultado final: **609 testes Python aprovados, 7 pulados e 1 excluído em 83,98 s**. Inclui 18 casos novos de prioridade/migration. Em execução explícita separada, **3 testes Edge aprovados em 46,72 s** (prioridade/senhas, Assunto/fluxo e Observações). Também passaram os **5 testes Node de leitura**, Ruff, verificações de sintaxe JS, Django check, migration check e diff check.

Três dos skips padrão são os navegadores executados explicitamente; três testes exigem PostgreSQL descartável e um é um navegador antigo de formulários fora desta validação. A suíte geral mantém uma única exclusão preexistente: `test_isolated_services_share_localhost_and_disabled_integrations`, que exige flags OAuth desligados enquanto o Compose já versionado os mantém ligados. Esse arquivo não foi modificado.

O teste Edge usa servidor, banco, usuários e sessões descartáveis, bloqueia conexões externas e não usa credenciais reais. Verifica editor/publicação, telas de senha, olho/ocultar, clique real e cursor, teclado, viewport de 390 px, nenhuma submissão pelo toggle e nenhum efeito no armazenamento. O armazenamento preexistente de tema do Django Admin é preservado, não confundido com armazenamento de senha. Capturas fictícias: `.tmp/priority-password-ui/`.

Para repetir:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_form_default_priority.py -q
$env:RUN_SECURITY_UI_BROWSER='1'
$env:RUN_REQUEST_FLOW_BROWSER='1'
$env:RUN_OBSERVATIONS_BROWSER='1'
.\.venv\Scripts\python.exe -m pytest tests/test_password_visibility_browser.py tests/test_request_flow_browser.py tests/test_observations_browser.py -q
node --test tests/observations-state.test.cjs
.\.venv\Scripts\python.exe manage.py check --settings=config.settings.test
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings.test
```

## Validação futura em 8010

Nada foi publicado. Em uma atualização manual futuramente autorizada, preparar a nova imagem isolada, executar a migration 0004 contra o banco isolado antes de iniciar o web com o código novo e preservar todos os volumes. Não usar comandos do Compose padrão ou down -v.

1. Em `http://localhost:8010`, abrir um formulário como administrador. Conferir ordem audience → prioridade e o texto de ajuda; definir Alta e publicar.
2. Como colaborador, abrir a solicitação. Não deve existir seleção de prioridade. Após envio, conferir Alta no chamado. Repetir com outro formulário de prioridade diferente.
3. Alterar o padrão e publicar; conferir a nova prioridade apenas em uma solicitação nova. A antiga deve permanecer intacta.
4. Em chamado fictício com criação Planner já autorizada nesse ambiente, conferir o valor mapeado na tarefa; mudar manualmente a prioridade no Planner e conferir que a sincronização não a sobrescreve.
5. Nas telas existentes de senha, digitar um valor fictício, alternar olho duas vezes e usar Tab/Enter. O conteúdo não deve sumir e nenhum formulário deve ser enviado. Repetir em celular.
6. Revalidar Assunto opcional/obrigatório, seleções com um clique, Voltar com arquivo/texto e leitura/notificação das Observações do TI.

Sem JavaScript, a senha permanece ocultada e a autenticação funciona; o controle visual progressivo não é disponibilizado. A escrita real de prioridade no Graph permanece para a homologação após autorização de atualização. Não foram solicitadas permissões Microsoft adicionais.
