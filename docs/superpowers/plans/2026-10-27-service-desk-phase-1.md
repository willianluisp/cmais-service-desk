# C+ Service Desk Fase 1 — plano de implementação

> Execução: superpowers:executing-plans, nesta sessão. Desenho aprovado pelo usuário em 27/10/2026 com “PODE INICIAR”.

**Goal:** entregar a base local do portal, sem integrações reais.
**Architecture:** monólito Django; PostgreSQL, Redis, Celery; templates e CSS próprios.
**Tech Stack:** Python 3.12, Django 5.2 LTS, Celery 5.6; dependências fixadas após instalação e validação.
**Spec:** ../specs/2026-10-27-service-desk-design.md

## Global Constraints

- Português brasileiro; America/Sao_Paulo; persistência UTC.
- Sem deploy, commit, push ou acesso real a AD/Microsoft/e-mail.
- Integrações desabilitadas; nenhum mock de autenticação em produção.
- Sem migrations no startup; containers não-root; banco/Redis sem portas públicas.
- Não há Git neste diretório; não criar repositório ou worktree para este incremento.

## Review Focus

1. Configuração incompleta de produção deve falhar sem expor segredos.
2. Healthcheck indisponível retorna 503 sem mensagens de conexão ou credenciais.
3. Visitante não acessa diagnóstico detalhado nem administração autenticada.
4. Redis indisponível não retorna readiness bem-sucedida.
5. Interfaces não sugerem login/chamados/integrações funcionais nesta fase.

### Task 1: configuração e fundação

**Files:** pyproject.toml, requirements*.lock, manage.py, config/settings/*,
config/celery.py, config/urls.py, config/wsgi.py, apps/*/apps.py,
tests/test_configuration.py.
**Interfaces:** settings por DJANGO_SETTINGS_MODULE; Celery app config.celery.app;
DATABASE_URL/REDIS_URL em ambiente; flags externas permanentemente false na Fase 1.

- [x] Criar ambiente virtual e instalar dependências; fixar versões resolvidas.
- [x] Escrever testes de timezone, autenticação negada, configuração produção e Celery.
- [x] Executar testes e registrar falha por comportamento ausente.
- [x] Implementar settings separados, backend de autenticação indisponível,
  apps e Celery sem tarefas externas.
- [x] Executar testes e Django checks; esperado: todos passam.

### Task 2: páginas e diagnóstico

**Files:** apps/core/{views,urls,health,middleware}.py, templates/*,
static/css/portal.css, tests/test_pages.py, tests/test_health.py.
**Interfaces:** GET /, GET /login/, GET /integracoes/ (staff somente),
GET /health/live/, GET /health/ready/. Readiness testa DB e Redis;
apenas staff vê estado de integração, sem valores de configuração.

- [x] Escrever testes de páginas, CSRF, acesso staff e healthchecks com mocks das dependências.
- [x] Executar testes; esperado: falhas por rotas/comportamento ausentes.
- [x] Implementar layout responsivo e acessível, login indisponível sem campo de senha,
  integração desabilitada, headers e diagnóstico sanitizado.
- [x] Executar suíte; esperado: sucesso. Verificar visual desktop/mobile se navegador disponível.

### Task 3: containers e operação

**Files:** Dockerfile, compose.yaml, .env.example, .dockerignore, .gitignore,
README.md, docs/operations.md, scripts/*, tests/test_compose.py.
**Interfaces:** Compose com web/db/redis/worker/beat; comando explícito migrate;
healthchecks por serviço; volumes para dados, anexos e beat.

- [x] Escrever testes estruturais dos serviços, isolamento de rede, healthchecks e usuário.
- [x] Executar e registrar falhas; implementar Docker e documentação.
- [x] Testar instalação por locks, suíte completa, lint, collectstatic e checks de produção.
- [x] Executar Compose, build, migrações e smoke tests reais após instalação do Docker/WSL.
- [x] Fazer revisão independente dos arquivos, corrigir problemas relevantes com regressões.
- [x] Atualizar registro de execução e documentar comandos e resultados.

## Registro de execução

- Ruling: executar diretamente na pasta vazia, sem Git/worktree/commits — restrição do incremento.
- Ruling: usar ambiente virtual local; Python 3.12.14 disponível no runtime do Codex.
- Ruling inicial: ausência de Docker não impediu implementação; pendência resolvida após instalação do Docker/WSL e reinicialização em 27/10/2026.
- Ruling: aprovação para iniciar já recebida; executar as três tarefas sem novas confirmações intermediárias.
- Ruling: adicionar apps/core para páginas, healthchecks e headers; manter apps de negócio sem modelos até a fase correspondente.
- Ruling: não adicionar HTMX sem interação assíncrona nesta fase; templates/CSS bastam às páginas entregues.
- Task 1: complete — configuração testada; backend de senhas indisponível; dependências fixadas.
- Task 2: complete — testes de páginas/ACL/CSRF/health; conferência visual desktop e mobile no navegador.
- Task 3: complete — build/runtime Docker, PostgreSQL, Redis, Celery, migrações, volume e HTTP validados; cinco serviços saudáveis.
- Final: fixed — caminho SQLite com caractere + preservado; regressão RED→GREEN; migrations locais aplicadas.
- Final: fixed — opções TLS PostgreSQL preservadas; regressão RED→GREEN.
- Final: fixed — ALLOWED_HOSTS obrigatório em produção; regressão de variável ausente RED→GREEN.
- Final review: revisão independente, dois achados importantes corrigidos em passe único; nenhum menor reportado.
- Final: Ruling inicial: execução real aguardava Docker; resolvida com validação dos cinco containers e smoke tests locais, sem homologação de produção.
- Final: Ruling: AD/OAuth/SMTP/chamados/ACL de objetos aguardam próximas fases, conforme desenho aprovado.
- Final: Ruling: conferência visual realizada pelo implementador em desktop e mobile; sem auditoria formal de acessibilidade.
- Final: suíte completa 41/41; lint e formato aprovados; detalhes em docs/verification-phase-1.md.
- Retomada após instalação: 41/41 em 23,38 s; lint/formato aprovados; .env local gerado sem expor valores; containers deixados em execução em localhost:8000.
