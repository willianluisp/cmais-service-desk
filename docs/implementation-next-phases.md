# Continuação autorizada em 27/10/2026

Referência: desenho aprovado em docs/superpowers/specs/2026-10-27-service-desk-design.md.
O usuário autorizou aplicar os arquivos da marca e continuar as demais fases.

1. Aplicar SVGs oficiais, azul #003a56, verde #80b21c e imagens do site institucional, mantendo origem registrada e acessibilidade.
2. Implementar AD com configuração fail-closed, TLS verificado, grupos e perfil estável; testar sem consultar domínio real. Homologação depende de dados do administrador.
3. Implementar chamados internos, protocolo, autorização por objeto, comentários e auditoria transacional; testar antes de liberar interface.
4. Integrar componentes, executar suíte, reconstruir containers e conferir interface.
5. Prosseguir com Planner/outbox conforme contratos do desenho; criação real e tokens dependem de estratégia Microsoft aprovada.

Execução por tarefas independentes com revisão posterior. Não há Git neste diretório; sem commits, deploy externo ou acesso a serviços corporativos reais.
Interfaces: accounts fornece UserProfile/papéis e backend configurável; tickets referencia AUTH_USER_MODEL e usa grupos COLABORADOR/TECNICO_TI/SUPERVISOR_TI/ADMIN_PORTAL; UI e URLs principais integrados pelo coordenador.
