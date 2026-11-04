# Verificação da Fase 1 — 27/10/2026

## Entrega

Scaffold Django, configuração por ambiente, autenticação indisponível sem
fallback local, páginas responsivas, diagnóstico staff, headers, healthchecks,
Celery, Compose de cinco serviços, locks, README e procedimentos operacionais.
Módulos de negócio têm somente sua estrutura de apps, sem chamados ou
integrações reais. Sem deploy, commit, push ou acesso a serviços corporativos.

## Evidências executadas

Ambiente: Windows, Python 3.12.14, Django 5.2.18, Celery 5.6.3; ambiente virtual
em `.venv`. Nenhuma dependência foi instalada globalmente.

| Verificação | Resultado |
| --- | --- |
| `python -m pytest -q` | **41 passaram**, 23,38 s após instalação do Docker |
| `python -m ruff check .` | Sem erros |
| `python -m ruff format --check .` | 35 arquivos formatados |
| `python -m pip check` | Nenhuma dependência quebrada |
| `python manage.py check` | Sem problemas |
| `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | Nenhuma alteração detectada |
| `python manage.py collectstatic --noinput --settings=config.settings.build` | Concluído sem erro |
| `python manage.py check --deploy --fail-level ERROR` com produção sintética | Sem erros; aviso W004 esperado por HSTS em 0 |
| `python manage.py migrate --noinput` em desenvolvimento | 18 migrations internas Django aplicadas no SQLite local |
| Prévia HTTP local | Inicialização em `127.0.0.1:8001`, check Django sem problemas |
| Navegador | Página inicial e acesso conferidos; desktop e viewport de celular 390 × 844; sem overflow horizontal observado |

Os executáveis usados são `.venv/Scripts/python.exe`. Para o sandbox, TEMP/TMP
e o diretório temporário do pytest foram redirecionados para `.tmp` do projeto;
isto não altera a configuração do aplicativo. O acesso ao PyPI e a prévia
loopback precisaram executar fora das restrições de rede do sandbox. A prévia
escuta somente em localhost e não é uma implantação.

## Validação Docker após instalação de Docker Desktop e WSL

Pendência de infraestrutura concluída em 27/10/2026, após a reinicialização
informada pelo usuário. Docker Engine 29.9.2, Docker Desktop 4.97.0, Compose
5.6.1; contexto desktop-linux, WSL 2 e containers linux/amd64.

O arquivo `.env` local foi criado a partir do exemplo, com segredo Django e
senha de banco aleatórios, sem imprimir os valores. Não foram utilizadas
credenciais de AD/Microsoft/e-mail. O acesso ao engine e a verificação HTTP
precisaram executar fora do sandbox restrito.

| Verificação | Resultado |
| --- | --- |
| `docker compose config --quiet` | Configuração válida |
| `docker compose --progress plain build web` | Imagem cmais-service-desk:local construída, incluindo collectstatic |
| `docker compose up -d --wait db redis` | PostgreSQL e Redis saudáveis |
| `docker compose run --rm --no-deps web python manage.py migrate --noinput` | 18 migrations aplicadas no PostgreSQL novo |
| `docker compose up -d --wait` | web, db, redis, worker e beat saudáveis |
| Consulta real ao banco | Vendor postgresql, 18 migrations registradas |
| Redis PING pelo container web | OK |
| Controle Celery pelo broker Redis | Uma resposta pong do worker |
| Beat | PID ativo, agenda persistida em volume, UID 10001 |
| Aplicação/volume de anexos | UID 10001 e criação/remoção de arquivo temporário no volume bem-sucedida |
| Django check e migrate --check dentro do container | Sem problemas ou migrations pendentes |
| HTTP pelo host Windows | localhost:8000/health/ready/ retornou 200 e status ok |

O smoke test HTTP dentro do container confirmou: `/`, `/login/`,
`/health/live/`, `/health/ready/` e `/static/css/portal.css` retornam 200;
`/integracoes/` e `/admin/` redirecionam visitantes para `/login/`; acesso direto
a `/media/private-probe.txt` retorna 404. A página de login não coleta senha.
Os headers CSP e X-Frame-Options também foram conferidos.

Somente `127.0.0.1:8000` foi publicado. PostgreSQL/Redis não publicam portas no
host. As três integrações externas permanecem desabilitadas. O teste de volume
não implementa upload de anexos de chamados, e o pong Celery não homologa uma
fila de notificações ainda inexistente. Nenhuma correção de código da aplicação
foi necessária para o primeiro build e a inicialização dos containers.

## Testes relevantes

- Configuração de produção inválida: chave, DEBUG, PostgreSQL, hosts e HTTPS.
- Variável ALLOWED_HOSTS ausente/vazia não aceita; TLS da URL PostgreSQL preservado.
- Senha de superusuário local não autentica enquanto AD estiver indisponível.
- Diagnóstico restrito a staff; acesso anônimo e colaborador rejeitados.
- CSRF no POST de login; sessão limpa no logout; logout exige POST.
- Mídia privada não publicada por rota direta.
- Readiness testa banco e Redis, retorna 503 em falha e não inclui a exceção.
- Integrações continuam desabilitadas mesmo se flags externas forem definidas.
- Compose sem portas públicas para banco/Redis; processos da aplicação não-root,
  readiness de dependências, healthchecks e volumes.

Os testes automatizados de infraestrutura usam SQLite real e mock do PING Redis.
A execução Docker descrita acima complementou-os com dependências reais.
Os casos de concorrência,
idempotência de chamados/outbox, uploads e Graph pertencem às fases seguintes.

## Revisão independente

Revisão somente leitura identificou dois achados importantes: descarte de
opções TLS da URL do banco e aceitação de ALLOWED_HOSTS ausente em produção.
Ambos foram reproduzidos por testes que falharam, corrigidos e cobertos na
suíte final verde. Nenhum achado menor foi reportado.

Durante a execução local foi identificada e corrigida a conversão indevida do
caractere `+` no caminho da pasta ao montar uma URL SQLite. O caminho local
padrão agora é passado diretamente como Path; teste de regressão passou e as
migrations foram aplicadas.

## Limitações e validações pendentes

- A pendência inicial de Docker indisponível foi resolvida; config, build,
  migrações, inicialização dos cinco serviços e smoke tests foram executados.
- Settings de produção foram examinados com valores sintéticos, sem conectar
  ao banco. HSTS fica em 0, sem includeSubDomains/preload até homologação do
  HTTPS corporativo; o check final retornou o aviso Django W004 neste estado.
  Um ensaio com HSTS habilitado também apontou W005/W021 para as opções de
  subdomínios/preload, que dependem da política do domínio. Não configurar esses
  parâmetros apenas para silenciar o check.
- Os smoke tests locais não substituem a homologação de um host de produção,
  HTTPS, backup/restore ou cargas reais das fases seguintes.
- A validação visual não é auditoria formal de acessibilidade.
- AD, OAuth Planner, SMTP/Exchange, proxy, backups e permissões corporativas
  reais não foram configurados nem homologados.
