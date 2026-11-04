# Homologação integrada sem serviços Microsoft reais

## Isolamento

O cenário `tests/test_full_homologation.py` usa Django Client com autenticação e
CSRF, ORM real, serviços e filas persistentes existentes. O perfil
`config.settings.test_postgresql` cria e descarta **test_cmais_homologation** no
PostgreSQL do Compose isolado. Seu nome-base aponta deliberadamente a um banco
inexistente para impedir uso acidental fora do runner. Não usa o banco
`service_desk`, nem envia POST ao portal em funcionamento. Anexos sintéticos
ficam em diretório temporário, fora do volume de anexos do portal.

Planner e SharePoint são simuladores com estado em memória. O e-mail é capturado
em memória. O teste bloqueia `urllib.request.OpenerDirector.open`: qualquer
tentativa inesperada de HTTP falha imediatamente. Overrides de aprovação
existem somente no processo pytest para exercitar os serviços com clientes
injetados; não são gravados em variáveis de ambiente, banco do portal ou
credenciais. Todas as flags reais permanecem false.

## Fluxo verificado

1. Colaborador sintético autenticado abre formulário e envia título, descrição,
   categoria e PDF com CSRF. Confirma registro no PostgreSQL, protocolo,
   histórico, outbox Planner, publicação de anexo e confirmação de recebimento.
2. A tarefa simulada entra em Tarefas pendentes. O teste executa três variantes:
   429 antes da criação, timeout após a criação remota e timeout no PATCH da
   descrição. As retentativas respeitam available_at; a reconciliação reutiliza
   a tarefa, preserva correlação/descrição e não duplica o POST aceito.
3. A publicação do anexo bloqueia a ACL simulada inadequada. Após correção da
   simulação, publica um arquivo e lida com timeout de referência, reaproveitando
   a cópia já registrada. TI autorizada lê o arquivo no simulador; outra
   identidade é negada. A segurança efetiva do SharePoint ainda exige homologação
   Microsoft — o simulador não atesta ACLs corporativas.
4. Consultas pelo endpoint POST/HTMX acompanham Tarefas pendentes → Desenvolvendo
   → Finalizada. Dashboard, listagem e detalhes exibem Aberto → Em andamento →
   Finalizado. Uma falha de leitura preserva o status anterior; a próxima consulta
   recupera o fluxo. Consultas repetidas não duplicam eventos nem notificações.
5. A outbox registra exatamente Recebido, Em andamento e Finalizado para o e-mail
   do solicitante. Um 429 simulado falha uma vez e recupera; três mensagens são
   capturadas em memória uma única vez. Nenhum e-mail real é enviado.
6. Outro colaborador e um técnico são impedidos de listar/abrir/sincronizar o
   chamado e de baixar seu anexo, inclusive com concessão TicketAccess legada.
   O solicitante acessa o arquivo original privado normalmente.

Os IDs de plano, buckets, drive e pasta usados nos testes são explicitamente
fictícios e nunca substituem a configuração real de Demandas Infra TI.

## Defeito identificado e corrigido

Após falha do PATCH de descrição de uma tarefa já criada, o retry completava o
vínculo mas mantinha `Ticket.sync_state=ERROR` e o erro anterior. Agora a
recuperação bem-sucedida limpa o erro e restaura SYNCED. O cenário `details`
reproduziu o erro antes da correção e passou depois dela, sem reabrir ou reenviar
o chamado e sem apagar histórico. A correção não é aplicada retroativamente
por script aos chamados existentes: ocorre somente na recuperação normal.

## Execução reproduzível

No diretório ServiceDeskCmais, com Docker isolado iniciado:

```powershell
docker cp tests cmais-service-desk-isolated-web-1:/app/tests
docker cp config/settings/test_postgresql.py cmais-service-desk-isolated-web-1:/app/config/settings/test_postgresql.py
docker compose -f compose.isolated.yaml exec -T web python -m pip install pytest==9.1.1 pytest-django==4.14.0 PyYAML==6.0.3 ruff==0.15.22
docker compose -f compose.isolated.yaml exec -T web python -m pytest --ds=config.settings.test_postgresql -p no:cacheprovider -q
docker compose -f compose.isolated.yaml exec -T web env DJANGO_SETTINGS_MODULE=config.settings.test python -m pytest -p no:cacheprovider -q
docker compose -f compose.isolated.yaml exec -T web python -m ruff check --no-cache .
docker compose -f compose.isolated.yaml exec -T web python manage.py check
```

O banco de teste deve estar ausente antes do teste; se o runner encontrar um
banco existente, investigue sua procedência, não autorize exclusão cega nem use
`--create-db` para sobrescrevê-lo. pytest cria/aplica migrations e descarta
somente esse banco dedicado. Não utilizar esse perfil em 8000/produção.

Resultado desta execução: **200 testes aprovados no PostgreSQL descartável** e
**200 aprovados no SQLite de teste** (mesma suíte, não 400 testes distintos),
Ruff e Django check aprovados, sem migrations novas.

As filas foram processadas pelos serviços reais dentro do runner, não por
workers de produção. A entrega distribuída via broker e a autorização/entrega
real Microsoft continuam dependentes da futura homologação autorizada.
