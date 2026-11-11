# Revisão da entrega para produção — 11/11/2026

Preparação local, sem commit, push, deploy, reinício ou alteração de dados de
produção. A lista exata de arquivos deste commit está em
`commit-files-2026-11-11.txt`, com um caminho por linha. O manifesto inclui a si
mesmo e este relatório. Nenhum arquivo foi adicionado ao índice Git pelo agente.

## Escopo e revisão

- Conversa: incluir o leitor existente completo, views, rotas, contexto, templates,
  JavaScript e CSS. Isso evita repetir a publicação incompleta diagnosticada no
  Debian. Mantidos cache, paginação segura, autorização por chamado, proteção de
  conteúdo, flags explícitas e tratamento de falhas. Origem HTTPS suportada.
- Responsáveis: incluir o resolvedor de displayName e sua integração na projeção
  e no detalhe, preservando IDs, validação e cache positivo/negativo.
- Atualizar status: ação principal junto ao status, ícone existente, adaptação
  móvel e tratamento HTMX preservado.
- Alterações anteriores já presentes no diretório: manter título configurável,
  prioridade administrativa no envio Planner e visibilidade de senha. Os assets
  compartilhados acompanham todos os templates que os referenciam. Nenhuma
  reversão dessas funcionalidades foi feita nesta revisão.
- Testes, validadores de navegador e documentação funcional acompanham o código.
  `compose.observations.isolated.yaml` é apenas um override de homologação e não
  deve ser aplicado ao Compose de produção.

Os três planos históricos em `docs/superpowers/plans/2026-11-10-*.md` foram
revisados, mas ficam fora deste commit: não são dependências do produto e
registram estados anteriores. Foram preservados no disco, sem remoção.

## Intervalos do Planner

`CELERY_BEAT_SCHEDULE` contém sincronização de tarefas vinculadas **a cada 5
segundos** e provisionamento **a cada 5 segundos**. O checkout ainda usava 30
segundos para a primeira tarefa; foi alinhado ao intervalo informado pelo
operador para o Debian. O teste em `test_configuration.py` fixa os dois valores.

Isso é o intervalo do agendador, não uma promessa de consultar cada tarefa ou
atualizar o chat a cada 5 segundos. Foram preservados o prazo mínimo de 120
segundos por chamado em `_synchronize_linked_tasks`, trava compartilhada,
Retry-After e cooldown. O leitor de conversa continua com cache/polling de 120
segundos. Alterar esses limites seria uma mudança funcional adicional.

## Segurança do conjunto

O manifesto usa caminhos explícitos, sem globs, caminhos absolutos ou travessia
de diretórios. Não inclui `.env` (nem exemplos), credenciais, bancos, backups,
exports, logs, perfis de navegador, capturas ou resultados temporários. As
proteções de `.gitignore` e `.dockerignore` existentes foram verificadas.

Foram examinados os arquivos modificados e não rastreados em busca de chaves
privadas, JWTs, tokens de provedores, atribuições de credenciais, e-mails e
identificadores pessoais. Os valores de senha usados em testes são fictícios e
não autenticam em qualquer ambiente real. E-mails de teste usam domínios de
exemplo. Identificadores dos testes de responsáveis foram substituídos por UUIDs
sintéticos; o identificador operacional da tarefa de homologação foi omitido da
documentação. Não foram copiadas mensagens, nomes de colaboradores ou dados do
servidor para fixtures.

Não usar `git add .`: depois da revisão humana, o manifesto pode orientar uma
seleção exata com `git add --pathspec-from-file=docs/commit-files-2026-11-11.txt`.
Esse comando não foi executado pelo agente.

## Condições para uma publicação futura

Esta revisão não altera `.env`, configuração ou serviços do Debian. A futura
publicação precisa levar o conjunto completo, revisar a alteração local já
existente no settings do servidor e manter o intervalo do Beat consistente entre
web/worker/beat. Sem o módulo de observações, registrar o contexto quebra a
renderização; não publicar somente o settings isoladamente.

No web, `PLANNER_OBSERVATIONS_ENABLED=true` precisa estar presente, junto das
aprovações Graph e OAuth delegado já existentes, e `PORTAL_BASE_URL` deve continuar
apontando para a origem HTTPS correta. A flag permanece false por padrão; esta
preparação não autoriza ativá-la no servidor. A resolução de responsáveis depende
das permissões existentes para ler perfis; sem elas a página mostra o fallback.

Não há migração nova nesta revisão. Deve-se verificar o estado das migrações já
versionadas antes de qualquer publicação, sem supor que estão aplicadas porque
os testes locais passaram. O endpoint Microsoft de conversa continua em beta,
cujo uso em produção não é suportado pela Microsoft:
https://learn.microsoft.com/en-us/graph/api/plannertask-list-messages?view=graph-rest-beta

## Validação final

Foi criada uma cópia limpa com `git archive HEAD` e sobrepostos somente os **47
arquivos** do manifesto. Nenhum outro arquivo não rastreado do diretório foi
usado como dependência. Nessa cópia:

- Suíte completa: **645 aprovados, 8 ignorados**, sem exclusão por expressão.
  Três testes ignorados exigem PostgreSQL descartável; cinco são opt-in de
  navegador. Quatro desses navegadores foram executados separadamente abaixo;
  o teste antigo de custom forms não foi executado como navegador nesta revisão.
- Edge: **4 aprovados**, cobrindo conversa, ação de status em 1440/390/320 px,
  formulário/seleção/Assunto e prioridade/visibilidade de senhas. Servidor e banco
  pytest descartáveis; APIs externas simuladas ou bloqueadas.
- Settings de produção carregados com configuração e credenciais sintéticas,
  sem conexão ao banco real: system check aprovado.
- `collectstatic` com `CompressedManifestStaticFilesStorage`: aprovado, incluindo
  os seis assets obrigatórios de conversa, senha, estilo e ícones. A saída ficou
  somente em diretório temporário ignorado.

No diretório de trabalho, Ruff completo, cinco testes Node, sintaxe dos scripts
JavaScript, Django system check, `makemigrations --check --dry-run` e
`git diff --check` passaram. O teste do agendamento falhou primeiro com 30
segundos e passou após o ajuste para 5 segundos.

Limites: não foi feito build da imagem Docker nem teste de escrita no Graph ou
de mensagens reais. PostgreSQL de produção não foi modificado; os testes gerais
usaram SQLite descartável. A disponibilidade real da integração e as permissões
no Debian precisam ser verificadas quando uma publicação for autorizada.
