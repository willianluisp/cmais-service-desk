# Formulários personalizados — plano de implementação

Implementar o pedido completo em `apps/custom_forms`, integrado ao portal Django existente.
Sem commit/push, Graph, alterações de flags ou aplicação de migrations ao banco existente.

- Criar modelos aditivos FormDefinition e FormSubmission: rascunho JSON validado,
  publicação independente com versão, grupos de disponibilidade e snapshot por chamado.
- Administradores ADMIN_PORTAL/superusuários usam CRUD próprio, sem acesso global ao Django admin.
  Auditoria local registra ações e IDs, sem copiar respostas ou arquivos para logs.
- Validar schemas com limites, IDs estáveis e tipos/opções/defaults permitidos. Usar Django Forms
  para validação no servidor e atributos HTML nativos; nunca atribuir POST ao modelo Ticket.
- Editor visual responsivo na identidade existente: metadados, paleta, propriedades dos campos,
  opções por linha, arraste e botões acessíveis de ordenação, prévia do rascunho com render servidor.
  JavaScript externo e json_script preservam a CSP; texto renderizado sem innerHTML do usuário.
- Novo chamado mostra cards e suporte técnico padrão. Preservar POST legado e adicionar URL
  explícita para o suporte padrão. Publicações só aparecem aos grupos permitidos.
- Criar chamado pelo serviço atual e gravar respostas/snapshot na mesma transação.
  Arquivos passam pela validação e armazenamento privados existentes; compensar gravações
  físicas em falha. Total máximo de cinco anexos por solicitação, até 2 MB cada.
- Integrar respostas aos detalhes depois da autorização existente e remoção ao ciclo de
  exclusão permanente já autorizado. Arquivamento preserva respostas e esquema.
- Escrever testes primeiro, observar falhas, implementar e executar suíte completa, Ruff,
  Django check, migration check e teste de interface em banco fictício.

Decisões: grupos existentes representam disponibilidade (vazio = todos autenticados ativos).
Campos personalizados usam nomes isolados; assunto e prioridade permanecem controles do chamado.
Publicação incrementa a versão, edição usa revisão otimista, envio obsoleto exige recarga.
Não há exclusão de formulário usado; arquivamento desabilita novas solicitações.

Concluído: implementação, revisão independente e correções com testes de regressão.
Validação final: 403 testes aprovados em PostgreSQL descartável, incluindo UI Edge,
concorrência, ambos os módulos e compatibilidade; Ruff/check/migration check aprovados.
Migrations existentes não aplicadas, sem implantação nos ambientes 8000/8010.
