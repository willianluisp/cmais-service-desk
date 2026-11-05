# Plano de gestão exclusiva de usuários

Objetivo: adaptar EmployeeAdmin conforme o desenho aprovado em
`docs/superpowers/specs/2026-11-04-user-management-design.md`.

1. Criar testes de exclusividade, edição, unicidade, grupo, senha, auditoria e proteção da conta; executar para confirmar falhas.
2. Separar permissão de cadastro da permissão geral do portal; restringir formulários e navegação.
3. Adicionar detalhes seguros de auditoria por migração exclusivamente estrutural.
4. Preservar recuperação excepcional por superusuário e testar regressões de chamados/integrações.
5. Executar pytest completo, verificação de migrações e lint no ambiente isolado.

Sem commit/push, usuários reais, banco de produção ou operações externas.
