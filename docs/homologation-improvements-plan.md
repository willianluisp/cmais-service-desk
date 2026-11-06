# Melhorias de homologação — 05/11/2026

Escopo autorizado: as 11 melhorias do pedido, preservando Django, templates locais,
papéis existentes e integração Planner. Sem commit/push, dados reais ou chamadas externas.

## Análise e decisões

- `EmployeeAdmin` já restringe gestão ao Willian/superusuários; criação e exclusão
  estão desabilitadas. Reutilizar esse fluxo e `LocalAccount` para troca obrigatória.
- A auditoria própria compara campos e ADMIN_PORTAL; o Django registra/menciona
  alteração até em POST sem mudanças. Comparar estado persistido, grupos e permissões.
- Exclusão deve bloquear relações e histórico, inclusive relações SET_NULL/CASCADE;
  preferir desativação, impedir exclusão do próprio gestor e da conta protegida.
- Categoria é FK protegida e aparece no payload Planner. Manter esquema/históricos,
  retirar do formulário e atribuir categoria interna padrão somente na criação.
- Contadores do portal são agregados antes dos filtros. Agregar o queryset final,
  preservando a política `visible_tickets`. Verificar também facetas do Admin.
- Integrações têm estilos e pré-condições divergentes entre botões e endpoints.
  Centralizar capacidades locais e verificar novamente no POST, sem consultar Graph
  ao carregar a página. Conexão não comprova autorização remota.
- Logo oficial, tokens CSS e link ao portal já existem. Reutilizar identidade e
  componentes, trocar a apresentação institucional por atalhos operacionais.

## Execução

1. Testes de regressão para usuários, filtros, categoria e disponibilidade.
2. Gestão de usuários: criação/senha temporária, auditoria efetiva, navegação,
   proteção de contas e exclusão confirmada sem perda de relacionamentos.
3. Chamados: contagem filtrada e categoria interna estável, sem migração destrutiva.
4. Integrações: capacidades compartilhadas, estados visuais e feedback de envio.
5. Interface: início compacto, atalhos, Login destacado e retorno ao portal.
6. Ruff, checks Django, verificação de migrações, suíte completa e revisão do diff.

## Foco da validação

Elevação de privilégio via POST; POST sem mudanças e grupos/permissões intactos;
exclusão de conta ligada a históricos; filtros combinados com visibilidade/arquivo;
ações Microsoft bloqueadas apesar de conexão persistida. Testes usam banco em
memória, armazenamento temporário e Graph simulado. Validar JS e responsividade
em navegador local com dados fictícios quando houver runtime disponível.
