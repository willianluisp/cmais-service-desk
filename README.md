# C+ Service Desk

Formulários: [evolução, setores oficiais, ordenação e provisionamento](docs/forms-evolution.md).
Setor e localização são obrigatórios nas novas aberturas; a empresa cadastra os setores
pela interface. Desligamentos usam acesso por grupos explicitamente autorizados e aprovação
no portal, sem Planner/e-mail ou alterações externas automáticas. As regras dos chamados
comuns permanecem como descritas abaixo. Migrations e provisionamento aguardam autorização.

Homologação completa sem Microsoft real: [cenários, isolamento PostgreSQL e resultados](docs/homologation-simulated.md).

Acompanhamento do colaborador: **Aberto**, **Em andamento**, **Finalizado**, com
datas de alteração/consulta e notificações preparadas na outbox existente.
Envio permanece desativado. Veja [acompanhamento e e-mails](docs/tracking-and-email.md).

Anexos: armazenamento privado e persistente no Django, acessível ao solicitante
e ao grupo ADMIN_PORTAL. O Planner recebe somente o aviso da quantidade;
arquivos não são publicados no SharePoint nem enviados à Microsoft.
Consulte [anexos privados e backup](docs/private-attachments.md).

Fluxo definitivo: colaboradores abrem e acompanham exclusivamente os próprios
chamados; toda operação da TI ocorre no Planner, no plano Demandas Infra TI.
A abertura grava chamado e fila persistente sem aprovação manual. A entrada
é no bucket Tarefas pendentes configurado com seu ID real. Histórico,
retentativas e consulta de status são preservados. Não há fila de atendimento,
atribuição ou edição local de status no portal. Administração de usuários e
integrações permanece separada. Veja a [política de acesso](docs/access-and-attachments.md).

O painel Microsoft está em `http://localhost:8010/integracoes/`, restrito ao grupo ADMIN_PORTAL e superusuários locais. Permite conectar/desconectar Microsoft, selecionar plano e bucket, testar a conexão sem criar tarefas, autorizar a automação, solicitar sincronização e conferir envios ambíguos. Veja [integração automática: configuração Entra, operação pela interface e limites](docs/planner-automatic-integration.md). O código requer duas migrations ainda não aplicadas e implantação autorizada; nenhum ambiente foi ativado por esta entrega. Teste com criação de tarefa, e-mail e SharePoint continuam sujeitos às liberações específicas existentes.

Revisão final: [resultado, limpeza dos testes e preparação da máquina definitiva](docs/final-review-2026-11-03.md).
Atualização manual e exclusão lógica: [comportamento e flags](docs/planner-sync-and-deletion.md).

Atualização 29/10/2026: autenticação local Django habilitada por padrão e AD adiado. Consulte [login local, importação e homologação](docs/local-authentication.md). O ambiente isolado em 8010 possui web, worker e beat; as integrações Microsoft continuam condicionadas a configuração e autorização.

Atualização 30/10/2026: o Planner possui um fluxo OAuth 2.0 Authorization Code delegado, separado do login local Django e desabilitado por padrão. A configuração segura, o Redirect URI e a ativação controlada estão em [homologação Microsoft](docs/homologation-microsoft.md).

Base do portal interno de suporte da C+ Contadores, em português brasileiro.

**Estado: integrações preparadas para homologação.** O portal possui chamados,
anexos privados, `TicketAccess`, outboxes Celery e clientes seguros para AD/LDAPS,
Microsoft Graph, Planner e Outlook. As integrações externas permanecem bloqueadas
por flags até a homologação autorizada; não há credenciais versionadas nem chamadas
corporativas automáticas. Veja o [procedimento de ativação](docs/integrations-activation.md).

**Docker validado em 27/10/2026:** os cinco serviços iniciaram com healthchecks
saudáveis; PostgreSQL, Redis, worker, beat, migrações e HTTP foram verificados.
O ambiente local está disponível em http://127.0.0.1:8000/. Detalhes e limites
estão no [registro de verificação](docs/verification-phase-1.md).

## Execução local rápida (sem Docker)

Requer Python 3.12+. No PowerShell, a partir desta pasta:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Abra http://127.0.0.1:8000/. O modo local utiliza SQLite e não precisa de Redis
para renderizar as páginas. `/health/ready/` retorna 503 se Redis não estiver
disponível; isso é esperado neste modo. SQLite serve apenas ao desenvolvimento
e aos testes, não substitui a homologação com PostgreSQL.

Linux/macOS: troque `.\.venv\Scripts\python.exe` por `.venv/bin/python`.
Não é necessário ativar o ambiente virtual ou alterar políticas do PowerShell.
`.env` é lido pelo Compose; manage.py utiliza variáveis exportadas no processo.
O servidor local escuta apenas em loopback e não deve ser usado em produção.

## Docker Compose

Requer Docker Engine/Desktop com containers Linux e Compose v2. Copie
`.env.example` para `.env` e substitua `DJANGO_SECRET_KEY` e `POSTGRES_PASSWORD`
por valores aleatórios distintos. Gere cada valor, por exemplo, com
`python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Mantenha `.env` fora do Git; não cole os valores em tickets ou logs.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Edite .env e substitua os dois placeholders antes de continuar.
docker compose config --quiet
docker compose build
docker compose up -d db redis
docker compose run --rm web python manage.py migrate --noinput
docker compose up -d
docker compose ps
```

Neste ambiente, `.env` já foi criado com valores aleatórios exclusivos do
desenvolvimento local. Preserve esse arquivo ao reiniciar os serviços. Para
retomar o ambiente configurado, basta `docker compose up -d --wait`.

Abra http://127.0.0.1:8000/. Apenas web publica porta, restrita a localhost.
PostgreSQL e Redis ficam na rede interna. Web, worker e beat rodam como UID
10001, sem privilégios. Banco, anexos e estado do beat usam volumes nomeados.
Não há tarefas periódicas externas na Fase 1.

O Dockerfile coleta estáticos no build, sem segredos. Migrations são uma etapa
explícita e não rodam no startup de web/worker/beat.

`compose.yaml` é a base de **desenvolvimento local**. Configuração de produção,
proxy HTTPS e rede corporativa exigem homologação conforme [operação](docs/operations.md).

## Verificações

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py collectstatic --noinput --settings=config.settings.build
```

Os testes usam banco isolado em memória e mocks apenas nas dependências de
infraestrutura. Nenhum teste consulta AD, Graph ou e-mail reais. As versões
diretas estão fixadas em `pyproject.toml`; os locks incluem dependências
transitivas. Instale pelos locks para reproduzir a versão validada.

## Rotas nesta fase

| Rota | Comportamento |
| --- | --- |
| `GET /` | Apresentação pública ou dashboard autenticado com indicadores reais |
| `GET /login/` | Aviso de acesso indisponível, sem coletar senha |
| `POST /login/` | CSRF obrigatório; 503 enquanto autenticação não for implementada |
| `POST /logout/` | Encerra sessão; GET não permitido |
| `GET /integracoes/` | Estado das integrações, restrito a staff autenticado |
| `GET /admin/` | Estrutura Admin protegida; sem login local alternativo |
| `GET /health/live/` | Processo HTTP vivo; não consulta dependências |
| `GET /health/ready/` | Consulta `SELECT 1` e Redis PING; 503 em falha |

Diagnóstico e administração não estão acessíveis pelo login nesta fase; os
controles de sessão/permissão são exercitados nos testes. Criar um superusuário
local não habilita autenticação: o backend recusa todas as senhas até a Fase 2.
Não há contas de demonstração ou endpoint de login de testes.

## Organização

- `config/`: settings de desenvolvimento, produção, testes e build, URLs e Celery.
- `apps/core/`: páginas, headers, healthchecks e administração protegida.
- `apps/accounts/`: autenticação inicialmente indisponível; base para AD.
- `apps/tickets/`, `planner_integration/`, `notifications/`, `audit/`: limites
  dos módulos futuros, sem integração externa ou modelo de negócio nesta fase.
- `templates/`, `static/`: interface server-side, sem CDN ou fontes externas.
- `tests/`: configuração, controles de acesso, páginas, infraestrutura e Compose.
- `docs/`: desenho aprovado, plano, resultados e procedimentos operacionais.

## Próxima fase

Configurar AD por LDAPS com CA corporativa e grupos autorizados. São necessários
controlador/DNS, bases DN, grupos e política da conta de bind. Configurações
Microsoft e SMTP não são inferidas. LDAP não fornece token Graph.

Referências técnicas verificadas em 27/10/2026:
[Django 5.2.18](https://docs.djangoproject.com/en/5.2/releases/5.2.18/),
[Celery com Django](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html),
[readiness no Compose](https://docs.docker.com/compose/how-tos/startup-order/).

## Ambiente isolado

O [construtor de formulários personalizados](docs/custom-forms.md) permite criar,
publicar e organizar solicitações pelo portal, com respostas e snapshots por chamado.
Consulte as migrations aditivas pendentes antes da implantação.
O [fluxo simplificado Microsoft](docs/microsoft-simple-connect.md) documenta a configuração
inicial protegida, aprovações e conexão/reconexão pelo navegador.

O fluxo de autenticação local, importação aprovada e troca obrigatória de senha
está descrito em [primeiro acesso de homologação](docs/first-access-homologation.md).
Esse fluxo não depende do Active Directory e não ativa integrações Microsoft.

Para testar a versão em desenvolvimento sem afetar o ambiente em `8000`, copie
`.env.isolated.example` para `.env.isolated`, gere segredos locais e execute:

Em uma máquina Windows nova, inicialize também o armazenamento protegido
exigido pelo Compose: `powershell -File scripts/Configure-IsolatedMicrosoft.ps1 -InitializeOnly`.
Isso não solicita Client Secret nem habilita integrações. Não copie o arquivo
protegido, `.env`, bases ou anexos para o Git. O diretório será criado fora
do projeto/OneDrive com ACL privada.

```powershell
docker compose --env-file .env.isolated -f compose.isolated.yaml up -d --build web db redis
docker compose --env-file .env.isolated -f compose.isolated.yaml exec -T web python manage.py migrate --noinput
```

O portal isolado fica em `http://localhost:8010/`. Para parar somente esse
ambiente: `docker compose -f compose.isolated.yaml down`.

Crie o administrador local na máquina nova com `python manage.py createsuperuser`
executado no serviço web. O código não inclui os colaboradores, senhas,
chamados, anexos ou tokens deste ambiente: a migração de dados requer backup
e restauração separados conforme [anexos privados e backup](docs/private-attachments.md).

Consulte [acesso e anexos](docs/access-and-attachments.md) para a política de
`TicketAccess`, anexos privados e a futura associação AD/Planner.

### Anexos privados no ambiente isolado

Cada chamado aceita até cinco arquivos PDF/PNG/JPG/JPEG de até 2 MB. Os bytes
ficam no volume `cmais-service-desk-isolated_isolated_attachments`; apenas o
solicitante e `ADMIN_PORTAL` autenticado podem visualizar ou baixar. O Planner
recebe somente a quantidade, sem arquivos ou links externos.

Inclua o volume e o dump PostgreSQL no mesmo conjunto de backup. Os comandos e
o local recomendado fora do Git/OneDrive estão em
[anexos privados e backup](docs/private-attachments.md).
