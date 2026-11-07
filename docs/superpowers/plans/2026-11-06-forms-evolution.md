# Evolução dos formulários C+

Pedido do texto anexado: campos globais obrigatórios, setores oficiais administráveis,
editor completo, ordem visual persistida e sete modelos iniciais idempotentes em rascunho.
Sem migrations ou provisionamento no banco existente, Graph, alterações de Docker existente,
commit ou push. Testes apenas em bases descartáveis.

- Setores: app próprio, CRUD com permissões existentes, sem seed. Contexto imutável por
  chamado guarda FK protegida e nome histórico + localização, sem backfill de chamados antigos.
- Campos globais inseridos na renderização dos formulários (incluindo suporte padrão),
  validados no servidor. Equivalentes semânticos de setor/localização são unificados;
  setor de terceiro/desligado não é confundido com setor do solicitante.
- Extensões de schema: inteiro positivo, setor oficial e data/hora. Duplicação de perguntas
  gera UUID novo. Editor mostra os globais como obrigatórios fixos; publicação versionada.
- Ordenação: singleton com revisão/lock e lista de IDs, incluindo chave única standard.
  Drag/setas, envio validado e revisão rejeitam concorrência obsoleta; cards respeitam grupos.
- Modelos iniciais: comando idempotente por provision_key único, todos DRAFT, sem setores ou
  grupos presumidos. Suporte inicial usa o mesmo card padrão. Registros existentes não mudam.
- Desligamento: classificação sensível persistente, publicação exige grupos explícitos de
  solicitantes e de aprovadores. Chamado guarda grupos autorizados daquele envio; sem acesso
  geral de administradores/TI. Inclusive o solicitante precisa manter participação em um grupo
  autorizado para consultar o chamado sensível. Aprovação registrada por usuário autenticado do grupo aprovador,
  distinto do solicitante, com histórico/auditoria. Não implementa revogação externa.
- Dados sensíveis não entram em Planner, sincronização, publicação de anexos ou e-mail.
  Guardas defensivas em produtores e consumidores, incluindo filas antigas artificiais.
- Reutilizar lixeira/arquivamento/exclusão segura: dependências e snapshots preservados;
  aprovação e contexto removidos somente pela exclusão autorizada do próprio chamado.
- Testes primeiro; suíte completa PostgreSQL descartável + navegador desktop/móvel,
  Ruff, Django check, makemigrations check e revisão independente antes da entrega.

Decisões de implementação: o setor oficial começa vazio e impede envios até configuração;
formulários sensíveis não podem perder sua classificação após ativada. A ordenação visual é
a autoridade após salvar; ordem numérica permanece como posição inicial para formulários novos.

Concluído: 473 testes aprovados no PostgreSQL descartável, sem skips, incluindo
navegador, concorrência, migrations com preservação de dados fictícios e proteção do
fluxo sensível. Ruff/check/migrations check e revisão final aprovados. Banco de teste
encerrado. Nenhuma migration, seed ou implantação executada nos ambientes existentes.
