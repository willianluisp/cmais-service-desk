# Lixeira de formulários

Implementar o pedido completo reutilizando permissões ADMIN_PORTAL, auditoria,
revisionamento e bloqueios do serviço existente. Não aplicar migrations existentes,
alterar Docker, Graph, flags, volumes, commit ou push.

1. Testes vermelhos para mover, esconder das listas/intake, restaurar sem publicação,
   manter campos/configuração/snapshots, confirmação explícita, permissões/CSRF,
   dependências, revisão obsoleta e auditoria durável.
2. Migration aditiva 0002: trashed_at, trashed_by (SET_NULL), trashed_by_label.
   Não converter arquivados existentes nem excluir registros. Nome do responsável
   preservado mesmo que sua conta seja posteriormente removida.
3. Reutilizar perform_action para trash/restore. A ação legada delete passa a mover
   para a lixeira; nenhuma rota antiga pode excluir definitivamente sem confirmação.
   Bloquear edição, publicação e duplicação enquanto o formulário estiver na lixeira.
4. Gerenciar formulários e Novo chamado excluem trashed_at preenchido; lixeira
   administrativa mostra somente esses registros com data/responsável/restauração.
5. Nova tela de exclusão definitiva GET/POST com CSRF, nome exato, checkbox e revisão.
   Revalidar dependências e estado sob lock, negar dependências reversas externas,
   preservar auditoria após remoção. Remover somente a definição sem uso e seus
   vínculos próprios de disponibilidade; nunca excluir chamados, respostas ou arquivos.
6. Testar backend, navegador, suíte completa, Ruff/check/migrations. Documentar
   arquivos/migrations e comandos restritos ao projeto Compose isolado da porta 8010.

Concluído: 425 testes aprovados em PostgreSQL descartável, sem skips, incluindo
navegador, concorrência e upgrade da migration com preservação de dados fictícios.
Ruff, check, migration check e revisão independente aprovados. Banco de testes
encerrado. Nenhuma migration ou atualização foi aplicada aos ambientes existentes.
