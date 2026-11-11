# Formulários configuráveis e fluxo por seleção

> Atualização posterior: prioridade agora é exclusivamente administrativa, abaixo das permissões do formulário. A opção de pergunta Prioridade descrita historicamente nesta entrega foi desativada. Consulte [a implementação atual](form-priority-password-visibility.md). Assunto e navegação permanecem preservados.

Implementação de 10/11/2026, preparada no checkout atual. Sem commit, push ou deploy; o contêiner já existente em 8010 ainda precisa receber o código em uma publicação manual futura. Nenhuma operação foi executada contra o ambiente 8000, os volumes ou os dados reais.

## Editor e títulos

Somente **Empresa e Setor** continuam fixos e obrigatórios no fluxo. Novos formulários começam sem perguntas extras. A paleta oferece **Assunto**, com obrigatório desmarcado inicialmente; o administrador pode exigir, reordenar ou remover o campo. Adicionar o campo não publica a configuração: continua sendo necessário salvar/publicar pelo fluxo administrativo existente.

Regra para novos chamados e novas tarefas Planner:

1. Campo do tipo Assunto preenchido: usar a resposta, com limite de 160 caracteres.
2. Campo ausente ou opcional em branco: usar o nome da versão publicada do formulário.
3. No suporte legado ainda não configurado por formulário: usar `Suporte técnico`.

Campos antigos de texto curto chamados exatamente Assunto (sem diferenciar maiúsculas) são reconhecidos como compatibilidade. Se o administrador adicionar o novo tipo Assunto, ele passa a determinar o título; a pergunta antiga continua preservada como resposta normal. Quando o novo campo opcional estiver vazio, aplica-se o nome do formulário, sem recuperar implicitamente a resposta antiga. Textos legados maiores que 160 caracteres permanecem completos nas respostas e são truncados somente no título do novo chamado.

Prioridade também deixou de ser um campo fixo, seguindo o requisito de apenas dois campos padrão. Pode ser adicionada pela paleta e validada contra as prioridades atuais do sistema. Sem configuração ou sem preenchimento opcional, a prioridade interna é Normal. Parâmetros `title`/`priority` enviados fora do esquema configurado não substituem as escolhas do administrador.

Não houve alteração de registros existentes, publicação automática, mudança de versão de formulários reais ou reescrita de títulos antigos. Snapshots e respostas históricas permanecem intactos. A criação no Planner conserva correlação/idempotência, responsáveis, prazos e checklist; somente a escolha do título foi ajustada para o Assunto configurado. Não foram enviados dados reais ao Graph nesta tarefa: os testes de criação Planner usam mocks.

## Navegação

- Empresa e Setor são opções nativas de envio GET: um clique, Enter/Espaço ou toque seleciona e avança. Funcionam mesmo sem JavaScript. Não há botão Continuar nessas etapas.
- Formulários continuam usando os links diretos existentes, com proteção contra navegação duplicada e destaque do selecionado.
- O Voltar existente e seus handlers foram mantidos. Nas etapas revisitadas dentro da página, opções clicáveis substituem o avanço por Continuar. É possível clicar novamente na opção já selecionada para prosseguir.
- Os mesmos nós de formulário e FileList são mantidos durante a revisão de empresa/setor e a escolha do formulário atual. Texto, respostas e arquivos não são serializados nem gravados em localStorage. O histórico da página guarda apenas etapa e IDs de empresa/setor, com popstate para navegar sem descartar os campos.
- Requisições anteriores de seleção são canceladas quando o histórico muda durante uma consulta. Falhas ao consultar os formulários oferecem retorno às informações preenchidas.
- A revisão e o envio final continuam explícitos. Selecionar Empresa/Setor enquanto o usuário está preenchendo os campos não envia o chamado. O bloqueio existente de duplo envio e a chave de idempotência permanecem ativos.
- Ao escolher outro formulário, permanece a confirmação existente: perguntas e anexos de esquemas diferentes não são transferidos automaticamente. O conteúdo é preservado ao revisar o formulário atual; não há promessa de preservar FileList após recarregar a página ou mudar para outro formulário.

## Arquivos desta alteração

| Arquivos | Mudança |
| --- | --- |
| `apps/custom_forms/globals.py`, `schema.py`, `forms.py`, `services.py` | Tipos Assunto/Prioridade, validação, compatibilidade e resolução do título |
| `apps/tickets/forms.py` | Suporte legado sem Assunto/Prioridade fixos e fallback interno |
| `apps/planner_integration/services.py` | Título Planner respeitando Assunto configurado e snapshot histórico |
| `apps/sectors/intake.py` | Retorno à seleção da empresa e preservação da escolha de setor |
| `static/js/form-builder.js`, `request-flow.js` | Paleta configurável, avanço, feedback, histórico e proteção de duplicatas |
| `static/css/stitch-portal.css` | Destaque da opção selecionada e toque, mantendo tokens do redesign |
| `templates/custom_forms/editor.html`, `intake_selection.html`, `templates/includes/request_context.html` | Instruções corretas, opções nativas e remoção de Continuar |
| `tests/test_manual_form_fields.py`, `test_employee_experience.py`, `test_tickets.py` | Expectativas atualizadas para os novos campos padrão, mantendo validações de segurança |
| `tests/test_configurable_subject.py` (novo) | Assunto ausente/opcional/obrigatório, histórico, inclusão/remoção, prioridade, Planner e seleções |
| `tests/test_request_flow_browser.py`, `scripts/validate-request-flow-ui.mjs` (novos) | Editor e fluxo completo em Edge com servidor/banco pytest descartáveis |
| `docs/superpowers/plans/2026-11-10-configurable-subject-flow.md` e este documento (novos) | Plano e registro de entrega |

## Observações do TI preservadas

Os 16 arquivos protegidos da entrega anterior, incluindo leitor Graph, rotas, templates, scripts, CSS e testes, foram comparados por SHA-256 antes/depois: **16 de 16 idênticos**. Isso inclui os pontos de integração existentes em base, lista, detalhe e dashboard. O arquivo compartilhado de configuração que já tinha mudanças não commitadas não foi sobrescrito.

Os testes de Observações continuam presentes e foram executados novamente: backend coberto pela suíte geral, cinco testes Node de leitura aprovados e teste Edge desktop/mobile aprovado separadamente. Não foram alterados a API, o controle de leitura ou as configurações Microsoft.

## Verificações

Resultado final: **591 testes Python aprovados, 6 pulados e 1 excluído, em 60,50 s**. Os 17 casos de Assunto configurável estão incluídos nessa suíte. Em execução explícita separada, **2 testes de navegador aprovados em 30,12 s** (fluxo/editor e Observações), além de **5 testes Node de leitura aprovados**. Quatro dos skips restantes são três testes que exigem PostgreSQL descartável e um navegador antigo de formulários fora desta validação; os outros dois são os navegadores executados separadamente.

A suíte é executada com uma única exclusão preexistente: `test_isolated_services_share_localhost_and_disabled_integrations` exige OAuth/Graph desligados, mas `compose.isolated.yaml` já tem esses flags ligados no HEAD. Esse arquivo e teste não foram alterados para contornar a divergência.

Comandos para repetir sem dados reais:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -k 'not test_isolated_services_share_localhost_and_disabled_integrations'
$env:RUN_REQUEST_FLOW_BROWSER='1'
$env:RUN_OBSERVATIONS_BROWSER='1'
.\.venv\Scripts\python.exe -m pytest tests/test_request_flow_browser.py tests/test_observations_browser.py -q
node --test tests/observations-state.test.cjs
.\.venv\Scripts\python.exe manage.py check --settings=config.settings.test
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings.test
```

Ruff também foi executado nos arquivos Python alterados, junto das verificações de sintaxe JavaScript e `git diff --check`. Não há models/tabelas novos nem migrations necessárias. Capturas do novo fluxo usam apenas dados fictícios e ficam em `.tmp/request-flow-ui/`.

## Testar futuramente na porta 8010

Nenhum deploy foi executado. Após atualizar manualmente somente a imagem/web do Compose isolado, preservando seu banco e volumes:

1. Entrar em `http://localhost:8010` como administrador e criar um formulário vazio. Confirmar que não foi inserido Assunto.
2. Publicar, abrir como colaborador e escolher Empresa → Setor → Formulário com um clique por opção. Enviar sem Assunto e conferir o nome do formulário no chamado e, quando o envio Planner estiver habilitado nesse ambiente, na tarefa criada.
3. No editor, adicionar Assunto opcional, publicar e conferir tanto envio em branco quanto com texto. Marcar obrigatório, publicar e confirmar bloqueio quando vazio. Remover e publicar novamente; conferir que os chamados anteriores preservam respostas e títulos.
4. Preencher texto e anexar um arquivo, usar o Voltar existente, trocar Empresa/Setor e selecionar o formulário atual. Conferir preservação dos dados. Repetir com Voltar/Avançar do navegador, teclado e viewport móvel.
5. Conferir que a revisão ainda exige confirmação final e que duplo clique não duplica a solicitação.
6. Com Observações habilitadas no ambiente isolado, repetir a leitura e a notificação de um chamado fictício vinculado ao Planner, conforme [a documentação de Observações](planner-observations.md).

O código atual em disco não muda automaticamente a imagem Docker. No ambiente em execução ainda sem atualização, esses novos comportamentos não estarão disponíveis.
