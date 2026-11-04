# Operação — Fase 1

## Configuração e limites

Os settings `development` aceitam SQLite para prévia local e usam e-mail de
console. Em Compose, o banco é PostgreSQL e Redis é o broker. Os settings
`production` exigem chave forte, DEBUG false, PostgreSQL e hosts sem curingas;
cookies Secure/HttpOnly/SameSite e redirecionamento HTTPS ficam habilitados.
`build` serve somente ao collectstatic. `test` nunca deve servir o portal.

O projeto não lê `.env` automaticamente fora do Compose. Exporte variáveis no
ambiente do processo quando executar comandos diretamente. A imagem assume
settings de produção; Compose seleciona explicitamente o desenvolvimento local.

As flags LDAP/Planner/e-mail são reservadas e permanecem false no código, mesmo
que alteradas no ambiente. Isto evita sugerir que mudar uma flag ativa uma
integração ainda não implementada. Não há chamadas HTTP ao Graph, LDAP ou SMTP.

Redis não publica porta e só participa da rede backend interna. Aplicações
participam também de uma rede de saída para futuras integrações. Não conecte
containers não confiáveis à rede backend. ACL/TLS de Redis e escopo de saída
devem ser definidos ao preparar produção.

## Implantação futura (não executada nesta fase)

1. Validar host Docker, DNS, backups, capacidade e imagens homologadas. Fixar
   imagens por digest após validação de segurança e arquitetura do host.
2. Configurar `DJANGO_SETTINGS_MODULE=config.settings.production`, chave aleatória
   de pelo menos 50 caracteres, `DJANGO_DEBUG=false`, banco e hosts explícitos.
3. Configurar proxy corporativo HTTPS e `CSRF_TRUSTED_ORIGINS` HTTPS. Somente
   ativar `TRUST_PROXY_HEADERS=true` se o proxy remover/substituir o header
   X-Forwarded-Proto enviado pelo cliente e o app não tiver acesso público direto.
4. Manter localhost/127.0.0.1 em ALLOWED_HOSTS para o healthcheck interno, além
   do domínio corporativo. Os endpoints de health são isentos do redirect HTTPS
   para uso interno; não exibem credenciais ou diagnóstico detalhado.
5. Fazer backup e revisão das migrations. Executar `docker compose build`,
   `docker compose run --rm web python manage.py check --deploy` e migrations
   explicitamente no processo de release, antes de subir os processos.
6. Iniciar serviços e conferir healthchecks, HTTPS, estáticos, cookies e logs.
   HSTS começa em 0; habilitar por política após comprovar HTTPS em toda a rota.
7. Ativar módulos externos somente após implementação, testes e autorização.

Não utilizar `development` como configuração pública. O Admin nesta fase está
sem modelos operacionais e sem login alternativo. A criação controlada de
administradores deverá acompanhar a implementação do backend corporativo e
sua política de contingência; `createsuperuser` não contorna o backend atual.

## Diagnóstico

```text
docker compose ps
docker compose logs --tail=80 web worker beat
docker compose exec web python manage.py check
docker compose exec worker celery -A config inspect ping --timeout 3
```

`/health/live/` indica apenas processo HTTP. `/health/ready/` exige banco e Redis;
não certifica login AD, Planner ou e-mail. Readiness retorna somente `ok` ou
`unavailable`, sem exceções/conexões. O healthcheck do beat verifica seu PID,
não comprova execução de uma tarefa periódica. Não há agenda externa nesta fase.

Evite compartilhar logs completos de produção. Não ative DEBUG publicamente.
Backups de dados, `.env`, certificados e anexos exigem acesso restrito e retenção
definida pela TI. Não registrar senhas, tokens ou conteúdo de anexos em logs.

## Backup e restore

Com o ambiente configurado, gere dump em arquivo dentro do container:

```text
docker compose exec db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/service-desk.dump'
docker compose cp db:/tmp/service-desk.dump ./service-desk.dump
```

Isso evita redirecionar dados binários pelo PowerShell antigo. Retire o dump da
pasta de trabalho para armazenamento protegido. Faça snapshot/exportação do
volume de anexos no mesmo ponto de consistência, com escrita pausada quando
houver chamados em produção. Redis/beat não substituem o banco e sua outbox.

Teste restore em **projeto Compose separado**, com volumes distintos e sem
integrações reais. Copie o dump para o container de teste e execute pg_restore
para um banco novo com `--no-owner --exit-on-error`. Confira contagens, vínculos
e downloads após restaurar banco e anexos. Não sobrescreva banco ativo para
testar restauração. Defina RPO/RTO com a TI antes de produção.

## Rollback e parada

Guarde a imagem anteriormente validada e os backups do mesmo release. Em falha,
pare web/worker/beat, avalie compatibilidade do schema e restaure a imagem
anterior. Reverter migrations requer revisão; não é um passo automático. Se o
schema não for compatível, restaure banco e anexos no ponto aprovado antes de
reiniciar. Não executar migrations destrutivas sem backup e revisão.

`docker compose down` para serviços preserva volumes. Não usar `down -v` como
procedimento de atualização, pois remove dados persistentes.
