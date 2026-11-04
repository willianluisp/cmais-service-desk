# Fase 4 — validação Microsoft pendente no tenant

Verificação documental em 27/10/2026. Nenhuma chamada ao tenant da empresa foi realizada.

A documentação atual da Microsoft lista permissões de aplicação para obter
tarefa (`Tasks.Read.All`) e criar tarefa (`Tasks.ReadWrite.All`), além das
permissões delegadas. Isso atualiza a premissa conservadora do documento inicial:
não é correto afirmar genericamente que app-only é incompatível com criação.
O suporte documentado não comprova consentimento, licença, tipo de plano ou
acesso do aplicativo ao plano da C+.

Referências oficiais:
- https://learn.microsoft.com/en-us/graph/api/plannertask-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/planner-post-tasks?view=graph-rest-1.0

Antes de habilitar: o administrador confirma tipo do plano e buckets, aplicativo
Entra e estratégia, consentimento mínimo e impacto do escopo, armazenamento e
rotação do segredo/certificado, remetente autorizado e política de notificações.
Registrar evidências sanitizadas de leitura e criação em plano de homologação,
incluindo 401/403/404/429, correlação de criação e comportamento após timeout.

LDAP autentica o domínio local e não fornece token Microsoft. Não usar senha de
colaborador para obter token, nem receber Bearer token arbitrário do navegador.
Até homologação e configuração aprovadas, o portal mantém integração desabilitada,
com vínculo manual e estados locais explícitos. As credenciais não devem ser
enviadas por chat, documentadas neste arquivo ou versionadas.

## Contrato implementado no portal

- A criação do chamado é local e transacional; a criação do cartão ocorre pela
  outbox `PlannerTaskProvisioning`, nunca no ciclo HTTP do formulário.
- O protocolo compõe o título e a descrição do cartão recebe uma correlação
  imutável e o link do portal configurado por `PORTAL_BASE_URL`. O link exige a
  mesma autorização `TicketAccess`/solicitante do portal; ele não torna anexos
  públicos.
- Após o `POST /planner/tasks`, o ID retornado é persistido antes do `PATCH`
  dos detalhes. Assim, timeout na descrição não permite novo `POST` duplicado.
  Timeout anterior à resposta entra em reconciliação por título/protocolo.
- A projeção Planner → Django é somente leitura, idempotente e produz evento e
  notificação apenas se os campos observados mudarem. Ela abrange bucket,
  percentual, responsáveis por ID, prazo e checklist. Nomes de responsáveis
  dependem de uma futura associação autorizada com o diretório corporativo.
- As flags `PLANNER_ENABLED` e `MICROSOFT_GRAPH_APPROVED` continuam sendo
  necessárias; ambas permanecem desligadas em desenvolvimento. Nenhum teste
  automatizado chama o tenant ou envia e-mail real.
