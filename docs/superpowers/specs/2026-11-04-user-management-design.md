# Gestão exclusiva de usuários — desenho

## Intenção

Permitir que a conta operacional `willian.pedroso` administre cadastros de
usuários pelo Django Admin já existente, sem transformar essa conta em
`is_staff` ou `is_superuser`, nem ampliar a visibilidade de chamados ou
anexos. Os demais integrantes de `ADMIN_PORTAL` preservam os acessos atuais a
chamados e integrações, mas não podem acessar nem manipular usuários.

## Objetivos

- Restringir a administração normal de `auth.User` à conta ativa
  `willian.pedroso`.
- Permitir consulta, pesquisa, alteração de nome, sobrenome, login único,
  ativação, redefinição de senha e associação a `ADMIN_PORTAL`.
- Usar os formulários e o fluxo de hash/validação de senha do Django Admin;
  nunca expor ou auditar senha, hash, token ou outro segredo.
- Marcar toda senha redefinida para troca obrigatória no próximo acesso.
- Auditar ator, alvo, instante, ação e os campos não sensíveis modificados.
- Impedir que a conta protegida seja desativada, tenha seu login alterado ou
  perca `ADMIN_PORTAL` pelo fluxo administrativo normal.

## Não objetivos

- Criar usuários, conceder `is_staff`, `is_superuser`, permissões individuais
  ou outros grupos por esta interface.
- Alterar regras de visibilidade de chamados, anexos ou Planner.
- Substituir a recuperação administrativa excepcional já disponível para
  superusuários autorizados.

## Abordagens consideradas

1. **Escolhida — especializar o `EmployeeAdmin` existente.** Reutiliza a rota
   `/admin/`, proteção CSRF, validação de unicidade, formulários de senha e a
   navegação atual. Uma permissão nova e estrita, baseada no login protegido,
   limita exclusivamente o modelo de usuários.
2. Nova área de portal. Rejeitada porque duplicaria rotas, formulários e os
   controles maduros do Django Admin.
3. Novo grupo de autorização. Rejeitada porque não garantiria exclusividade a
   uma conta específica.

## Arquitetura e decisões

- `is_portal_admin` permanece inalterado para chamados e integrações.
- `is_user_management_admin` será um predicado separado: usuário autenticado,
  ativo e com login exatamente `willian.pedroso`. Um superusuário ativo
  continua sendo o caminho de recuperação administrativa excepcional.
- `EmployeeAdmin` valida esse predicado em permissões de módulo, lista,
  visualização, alteração, senha e POSTs diretos. O `PortalAdminSite` continua
  protegendo o site como um todo por `ADMIN_PORTAL`, mas não concede acesso ao
  modelo de usuários.
- A tela exibirá somente campos cadastrais requeridos, status ativo e o grupo
  `ADMIN_PORTAL`. Flags globais, permissões individuais e demais grupos não
  serão campos editáveis. A associação a `ADMIN_PORTAL` será limitada no
  formulário e revalidada no backend.
- Para evitar perda acidental de acesso, operações normais não poderão
  desativar, renomear ou remover `ADMIN_PORTAL` de `willian.pedroso`. O acesso
  excepcional por superusuário permanece deliberadamente fora dessa restrição.
- `AccountAudit` ganhará um campo JSON para mudanças não sensíveis. Atualização
  cadastral, ativação e mudança de grupo produzirão registro com antes/depois;
  redefinição de senha terá ação própria sem detalhes secretos.
- Não haverá migração que edite contas existentes. A nova migração cria apenas
  a coluna de auditoria; os testes usam exclusivamente o banco em memória.

## Verificação

Testes automatizados cobrirão autorização de rota e POST direto, edição e
unicidade de login, redefinição sem vazamento de segredo e troca obrigatória,
ativação/desativação, gestão controlada de `ADMIN_PORTAL`, proteção da conta
`willian.pedroso`, auditoria e ausência de escalonamento para flags ou grupos
não permitidos. Serão executados contra a configuração de testes isolada.
