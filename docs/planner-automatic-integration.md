# Microsoft Planner automático — entrega e operação

## O que foi reaproveitado

OAuth delegado Authorization Code com PKCE S256, state de uso único e expiração,
escopos verificados, tokens Fernet criptografados e refresh token rotativo protegido
por bloqueio no banco. Chamados comuns já criavam uma intenção persistente na outbox;
chamados sensíveis não são publicados. A sincronização existente já projetava status,
progresso, responsáveis, prazo, checklist e bucket com histórico idempotente.

As lacunas eram plano fixado na administração, ausência de seleção/ativação pelo painel,
ausência de teste somente leitura e sincronização geral, sobreposição dos jobs e intenção
de criação perdida se o processo terminasse após enviar o POST.

## O que está implementado

- Seleção persistente de plano entre planos retornados pela Microsoft; consulta de buckets.
- Bucket padrão obrigatório; mapeamentos de andamento e conclusão opcionais e distintos.
- Ativação e pausa explícitas, auditadas e subordinadas à aprovação Graph do ambiente.
  Salvar credenciais ou conectar uma conta não ativa a automação.
- Testar conexão sem criar tarefa; sincronização solicitada pelo painel e gravada no banco
  antes do despacho ao Celery. Se Redis falhar, o agendamento de 30 segundos recupera o pedido.
- Desconexão apaga tokens locais e pausa a automação. Reconectar exige autorização Microsoft;
  revogação/consentimento corporativo continuam sob gestão do Entra.
- Lease compartilhado no banco impede sobreposição de jobs; expira após 15 minutos em caso
  de interrupção. Tasks têm limites de 600/660 segundos. Retry-After/429 é respeitado entre jobs.
- Chamados com falha têm próxima tentativa própria, evitando bloquear o restante da fila.
- Antes do POST, a intenção ambígua é persistida. Timeout ou interrupção provoca reconciliação
  por protocolo/título antes de qualquer nova criação. ID remoto é preservado antes do PATCH
  da descrição; falhas desse PATCH não criam outra tarefa.
- Mensagens de conexão, fila pendente, erros e ausência de processamento recente na administração.
  Operações administrativas usam os grupos existentes, POST e CSRF. Nenhum segredo é mostrado.

Não há execução de DELETE no Planner. Histórico, anexos privados e grupos de acesso são preservados.
Publicação de anexos, e-mail e armazenamento externo continuam sujeitos às aprovações específicas existentes.

## Configuração inicial (responsável técnico e Entra)

Esta entrega contém código e duas migrations **escritas, não aplicadas**:

- `planner_integration/0007_plannerruntime`: configuração e coordenação duráveis.
- `tickets/0007_ticket_next_planner_sync_at`: distribuição das próximas sincronizações.

É necessário autorizar separadamente aplicação das migrations e implantação. Nenhum Docker,
servidor, commit, push ou deploy foi executado. Os ambientes das portas 8000 e 8010 foram preservados.
Não abra o painel com o código novo em um banco ainda sem essas migrations.

No Microsoft Entra:

1. Usar registro de aplicação corporativa do tenant correto, plataforma **Web**.
2. Registrar exatamente `http://localhost:8010/integracoes/microsoft/callback/` para o ambiente
   isolado. Produção deve usar seu endereço HTTPS próprio; não alterar a porta 8000.
3. Permissões delegadas Graph: `User.Read` e `Tasks.ReadWrite`. O fluxo também solicita
   `openid profile offline_access`; offline_access permite renovação automática.
4. Conceder o consentimento requerido pela política do tenant. Não são necessários
   `Group.ReadWrite.All`, `Directory.Read.All`, acesso amplo a arquivos ou permissões de e-mail.
5. A conta conectada precisa de licença e acesso ao plano suportado pelo Graph. A listagem
   `/me/planner/plans` retorna planos compartilhados com a conta; não é um catálogo irrestrito
   de todos os planos da organização. As APIs Planner do Graph não cobrem planos premium.
6. Provisionar Tenant ID, Client ID, estratégia `delegated`, `MICROSOFT_GRAPH_APPROVED=true`,
   `GRAPH_DELEGATED_OAUTH_ENABLED=true`, URL do portal e chave `GRAPH_TOKEN_ENCRYPTION_KEY`
   no armazenamento protegido existente. Preservar a chave atual: trocá-la torna tokens
   e segredos antigos ilegíveis. O Client Secret pode ser salvo/rotacionado pelo painel.
7. Na implantação autorizada, web, worker e beat devem usar o mesmo banco/configuração e
   Redis; apenas um beat por ambiente. O override OAuth isolado existente libera somente
   web: ele não constitui configuração completa de automação dos workers. Aprovação e
   estratégia delegada precisam chegar também a worker e beat, sem compartilhar recursos
   ou cookies com o ambiente 8000. Nenhum arquivo Compose foi alterado nesta entrega.

Flags antigas de publicação/sincronização continuam compatíveis enquanto não houver escolha
explícita pelo painel. Depois de salvar automação, a escolha persistida controla publicação
e leitura periódica; aprovação Graph continua obrigatória. A primeira ativação inclui os
chamados comuns já pendentes, conforme informado na própria caixa de autorização.

## Testar tudo pela interface, após implantação autorizada

1. Entrar como administrador em `http://localhost:8010/integracoes/`.
2. Conferir os pré-requisitos. Se necessário, abrir Configuração inicial protegida e salvar
   o valor do segredo. Ele não volta a ser exibido.
3. Clicar **Conectar Microsoft**, autenticar no domínio oficial Microsoft e consentir.
   O portal preserva o login local e mostra Conectado.
4. Clicar **Consultar planos**, selecionar o plano de atendimento e **Selecionar plano**.
   Salvar o bucket padrão; os outros mapeamentos são opcionais.
5. Clicar **Testar conexão**: resultado esperado “Conexão validada”, sem nova tarefa.
6. Marcar a autorização de envio/sincronização, ciente de que inclui a fila pendente,
   e **Salvar automação**. Acompanhar o último processamento na mesma tela.
7. Como colaborador, abrir um chamado comum com texto fictício. A fila é verificada a cada
   30 segundos, em lotes de 25; verificar uma única tarefa com protocolo, título e descrição.
   Reenvio do mesmo formulário preserva o chamado e a intenção única.
8. Alterar responsáveis, prazo, checklist, bucket e progresso no Planner. Após o ciclo de
   aproximadamente 120 segundos (mais o tempo necessário para os lotes), reabrir o chamado:
   dados e histórico devem refletir o Planner, sem clicar Atualizar status.
9. **Sincronizar agora / Tentar novamente** solicita um lote em segundo plano; não ignora
   Retry-After ou tentativas já adiadas. Recarregar o painel para acompanhar o resultado.
   Se houver envio ambíguo, **Conferir envios pendentes → Consultar tarefas existentes**
   permite selecionar uma tarefa já existente e confirmar o vínculo depois de conferir
   o protocolo no Planner. Use a busca pelo protocolo ou título nos planos com muitas tarefas.
   A seleção é validada novamente na Microsoft, sem criar tarefa.
10. Abrir chamado restrito com texto fictício e verificar que ele não vai ao Planner e
    continua limitado aos grupos autorizados. Atribuição no Planner não cria permissão local.
11. **Desconectar Microsoft** pausa a automação e remove tokens locais, preservando dados.
    Reconectar e salvar a ativação novamente retoma a fila. Em falha Microsoft, o chamado
    permanece salvo; erros transitórios são retomados automaticamente.

Renovação não exige botão: ocorre na primeira operação que precise de um token prestes a
expirar, incluindo operações do worker. Depois de deixar o token vencer, Testar conexão
exercita a renovação. Revogação, política de acesso condicional, MFA exigida novamente e
expiração do segredo podem exigir reconexão ou rotação pelo painel; OAuth não elimina
essas exigências da organização. Não é necessário expor tokens para validar isso.

## Fonte de verdade e limites

| Informação | Fonte e regra |
| --- | --- |
| Protocolo, título, descrição, categoria e prioridade iniciais | Portal; publicados durante a criação e conclusão do envio da descrição |
| Progresso, responsáveis, prazo, checklist e bucket | Planner; projeção somente leitura no portal, sem conceder acesso local |
| Status do atendimento | Mapeamento de bucket existente tem precedência; sem mapeamento usa progresso (100% resolvido) |
| Fechamento definitivo | Portal; sincronização não reabre um chamado fechado |
| Identidade, grupos e chamados restritos | Portal; conta Microsoft da integração não substitui login local |

O processamento é periódico, não instantâneo. Atualmente 25 chamados por lote; volume alto
aumenta a latência. A tarefa agendada não depende da página estar aberta. Não há sincronização
de edição de texto do portal após o envio inicial nem atualização de status de volta ao Planner;
isso evita loops. Responsáveis são armazenados pelos IDs estáveis retornados pelo Planner;
não são criadas contas nem consultado todo o diretório para descobrir nomes.

Microsoft Graph não fornece chave de idempotência para criar plannerTask. Se uma criação
ficar ambígua e nenhuma tarefa com o título original aparecer, a outbox permanece em conferência;
não há repostagem cega. Alterar o título de uma tarefa antes da primeira reconciliação pode
impedir a correspondência. Se forem encontradas múltiplas tarefas, a operação é bloqueada,
sem excluir qualquer tarefa; a administração pode resolver o vínculo pela seção de conferência.
Quando não existe tarefa confirmada, não se libera repostagem cega. Não é possível prometer criação “exatamente uma vez” em todos
os cenários de rede usando essa API; preserva-se o chamado e prioriza-se evitar duplicatas.

Planner não consta na lista de recursos suportados para change notifications; mantém-se polling,
sem criar subscriptions fictícias ou exigir endpoint público adicional.

## Validação automatizada

Graph e credenciais são simulados. SQLite em memória com `--nomigrations`; nenhum banco do
ambiente é alterado. Testes de migrations existentes foram explicitamente excluídos da execução
final, respeitando a proibição. Testes de concorrência PostgreSQL e navegador permanecem opt-in.
O bloqueio usa SELECT FOR UPDATE no PostgreSQL, mas concorrência real não foi exercitada nesta entrega.

Resultado final: **511 testes aprovados, 4 pulados e 2 testes de migrations excluídos**.
Ruff e `git diff --check` passaram. Nenhuma credencial real foi usada nos testes.

Referências oficiais:

- [Authorization Code e PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [Planos compartilhados com a conta](https://learn.microsoft.com/en-us/graph/api/planneruser-list-plans?view=graph-rest-1.0)
- [Criação de tarefas e Tasks.ReadWrite](https://learn.microsoft.com/en-us/graph/api/planner-post-tasks?view=graph-rest-1.0)
- [Recursos suportados por notificações](https://learn.microsoft.com/en-us/graph/change-notifications-overview)
