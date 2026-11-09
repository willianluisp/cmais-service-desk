# Empresas, exclusão lógica e títulos Planner

## Plano e decisões

1. Reutilizar o app `sectors` para Company, com CRUD administrativo auditado,
   ativação, revisão concorrente e proteção contra exclusão de empresas utilizadas.
   Os setores continuam globais; nenhum grupo ou permissão existente é alterado.
2. Adicionar empresa nullable e snapshot no Ticket. Não inserir empresas nem atribuir
   empresas presumidas ao histórico. Exigir empresa ativa nos formulários novos e
   selecionar empresa/departamento antes dos cartões de formulários.
3. Reutilizar archived_at, cancelamento e auditoria existentes para exclusão lógica,
   com confirmação própria e autorização ADMIN_PORTAL no backend. Preservar a
   manutenção legada e os vínculos remotos; restauração pela área administrativa.
4. Usar snapshot do nome do formulário como título Planner. Reconciliar pela
   correlação na descrição (ou protocolo de tarefas legadas), nunca por título novo.
   Resultado de POST incerto permanece em conferência, sem nova tentativa cega.
5. Cobrir CRUD, validação, compatibilidade, exclusão/recuperação, segurança e
   reconciliação em testes SQLite em memória, com Graph simulado. Executar a suíte,
   lint e checagem de migrations. Documentar atualização exclusiva do 8010.

Não executar migrations no banco em uso, commit, push, deploy ou operações no 8000.
Preservar a alteração pré-existente de compose.isolated.yaml.

## Entrega

- Empresa é um cadastro independente dentro do app de setores. Os três cadastros
  oficiais devem ser criados por um administrador; não há seed ou empresas padrão.
- Toda abertura web, inclusive por URL direta, valida empresa ativa no backend.
  O serviço interno mantém argumentos opcionais para compatibilidade com rotinas
  legadas. Chamados antigos conservam empresa nula e o aviso de não informada.
- O nome da empresa fica congelado no chamado. Desativação bloqueia novos envios;
  exclusão física de uma empresa utilizada é protegida pelo banco.
- `Excluir chamado` abre confirmação e usa o arquivamento lógico existente.
  Todas as rotas de manutenção de chamados exigem grupo ADMIN_PORTAL, inclusive
  quando a conta é superusuário. Leitura de solicitações sensíveis mantém a
  política anterior. A administração recupera chamados em **Meus chamados →
  Chamados arquivados / excluídos → Restaurar**.
- A exclusão registra SOFT_DELETE com autor/data/protocolo, preserva dados e
  arquivos e cancela filas. Nenhuma tarefa Microsoft é excluída. Uma requisição
  HTTP que já estava em trânsito pode terminar; o vínculo retornado é preservado
  sem reativar a fila. A restauração conclui a descrição usando esse mesmo ID.
- Novas tarefas de formulário usam o nome do snapshot publicado, sem protocolo.
  Tarefas já vinculadas conservam seus IDs e seus títulos remotos atuais.
  A descrição contém protocolo, empresa, departamento, localização e solicitante.
- Reconciliação usa correlação exata em linha própria na descrição; protocolo
  legado também é aceito quando não existe correlação conflitante. O prefixo de
  protocolo antigo é aceito apenas para compatibilidade de cartões legados.
  Títulos novos iguais jamais são usados para vincular tarefas.
- Um envio novo sem tentativas não varre detalhes de tarefas alheias. Envios
  incertos consultam detalhes das tarefas não vinculadas, com cache por lote.
  Se o POST foi aceito mas seu ID não foi salvo e a descrição nunca foi enviada,
  não há identificação remota confiável: a fila permanece em conferência. Use
  **Integrações → Conferir envios pendentes**, confira a tarefa remota e vincule
  seu ID. Nenhum retry de criação é liberado automaticamente nesse caso.

## Arquivos

- `apps/sectors/models.py`, `intake.py`, `company_forms.py`, `company_views.py`,
  `company_urls.py`: cadastro auditado de empresas e seleção em etapas.
- `apps/sectors/migrations/0002_company.py` e
  `apps/tickets/migrations/0008_ticket_company_ticket_company_name_snapshot.py`:
  migrations aditivas sem dados presumidos.
- `apps/tickets/models.py`, `services.py`, `views.py`, `urls.py`, `lifecycle.py`,
  `lifecycle_views.py`: vínculo, snapshot, exclusão e recuperação.
- `apps/accounts/permissions.py`: disponibilidade dos controles de manutenção
  conforme o grupo, sem alterar a regra geral de administrador do portal.
- `apps/custom_forms/services.py`, `views.py`: empresa nos formulários dinâmicos
  e ordem consistente dos locks empresa → departamento.
- `apps/planner_integration/services.py`, `tasks.py`: títulos, descrição,
  reconciliação e cancelamento durante o processamento.
- `config/urls.py`, `templates/base.html`, `templates/companies/*.html`,
  `templates/custom_forms/intake_selection.html`, `choose.html`,
  `templates/tickets/soft_delete.html`, `detail.html`, `list.html`, `archived.html`,
  `templates/portal/dashboard.html`: navegação e apresentação.
- `tests/test_companies_planner_titles.py`: cenários novos e migração do legado.
  `tests/conftest.py`, `test_custom_forms.py`, `test_employee_experience.py`,
  `test_form_group_access.py`, `test_forms_evolution.py`, `test_full_homologation.py`,
  `test_planner.py`, `test_sectors.py`: adaptação ao fluxo e aos títulos novos.
- Esta documentação e `docs/planner-automatic-integration.md`.

`compose.isolated.yaml` já possuía alterações antes desta tarefa e foi preservado.

## Atualizar somente o ambiente isolado 8010

Os comandos abaixo são instruções; não foram executados nesta entrega. Execute
na raiz do projeto, após fazer backup do banco e do volume de anexos **isolados**.
Mantenha `.env.isolated` e o arquivo Microsoft já usado pelo Compose. Confira
que o projeto é `cmais-service-desk-isolated` e a publicação é `127.0.0.1:8010:8000`.
Não use `compose.yaml`, não remova volumes e não habilite integrações para atualizar.

```powershell
docker compose --env-file .env.isolated -p cmais-service-desk-isolated -f compose.isolated.yaml build web
docker compose --env-file .env.isolated -p cmais-service-desk-isolated -f compose.isolated.yaml stop web worker beat
docker compose --env-file .env.isolated -p cmais-service-desk-isolated -f compose.isolated.yaml run --rm --no-deps web python manage.py migrate --noinput
docker compose --env-file .env.isolated -p cmais-service-desk-isolated -f compose.isolated.yaml run --rm --no-deps web python manage.py check
docker compose --env-file .env.isolated -p cmais-service-desk-isolated -f compose.isolated.yaml up -d --no-deps web worker beat
```

Pare a sequência se algum comando falhar; não reinicie os processos com schema
incompleto. Depois abra `http://localhost:8010/administracao/empresas/` e cadastre
os três nomes reais, ative-os e confira os departamentos compartilhados. Valide
abertura, exibição de chamado antigo, exclusão/recuperação e autorização com
usuários de teste. A validação remota do Planner depende da autorização já
configurada; os testes automatizados usam Graph simulado e não acessam o tenant.

## Verificação automatizada

Usar `.venv\Scripts\python.exe -m pytest -q` e `-m ruff check .`.
As configurações `config.settings.test` usam SQLite em memória; nenhuma migração
foi aplicada ao banco em execução. Há cobertura explícita da migração de um
chamado anterior com vínculo Planner, sem preenchimento artificial da empresa.
Os testes de concorrência PostgreSQL e navegador são opcionais e não foram
executados. A checagem Django e `makemigrations --check --dry-run` também usam
`--settings=config.settings.test`.

O teste de Compose que exige Graph/OAuth desabilitados conflita com a alteração
pré-existente em `compose.isolated.yaml`, onde essas duas flags estão habilitadas.
Essa configuração e a expectativa do teste foram preservadas.

Resultado final em 09/11/2026:

- `python -m pytest -q --tb=short`: **529 passaram, 4 ignorados, 1 falhou**
  em 56,44 s. Única falha: `tests/test_compose.py::test_isolated_services_share_localhost_and_disabled_integrations`,
  pelo conflito pré-existente descrito acima.
- Testes focados de empresas, exclusão, Planner e automação: **67 passaram,
  1 ignorado**. Graph simulado, sem chamadas ao tenant.
- `python -m ruff check .`: aprovado.
- `python manage.py check --settings=config.settings.test`: sem problemas.
- `python manage.py makemigrations --check --dry-run --settings=config.settings.test`:
  nenhuma migration faltante.
- `git diff --check`: aprovado. Revisão independente realizada; os achados de
  varredura desnecessária no Planner e prazo de retomada da restauração foram corrigidos.

Não foram feitos commit, push, deploy, alterações do banco em execução ou ações
nos serviços das portas 8000/8010.
