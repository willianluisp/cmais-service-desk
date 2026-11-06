# Administração do portal e cadastro de usuários

`ADMIN_PORTAL` mantém os acessos existentes de chamados e integrações, sem
conceder `is_staff` ou `is_superuser`. O cadastro `/admin/auth/user/` é separado:
somente a conta ativa `willian.pedroso` pode gerenciá-lo no fluxo normal.
Superusuários ativos preservam acesso excepcional para recuperação autorizada.
O site administrativo continua exigindo `ADMIN_PORTAL` ou superusuário.

O cadastro permite pesquisar/consultar usuários, editar nome, sobrenome e login,
ativar/desativar e adicionar/remover somente `ADMIN_PORTAL`. Outros grupos,
e-mail, flags globais e permissões individuais são preservados. Criação usa senha
temporária aleatória e troca obrigatória no primeiro acesso. Exclusão exige
confirmação e ausência de relacionamentos/histórico; prefira desativar.
Contas staff/superusuário exigem o operador
excepcional para alteração ou redefinição, evitando tomada de contas globais.

No fluxo normal, `willian.pedroso` não pode ser renomeado, desativado nem perder
`ADMIN_PORTAL`. Não existe concessão automática desse grupo: a conta deve já
possuir acesso ao site. Recuperação excepcional pode corrigir esses atributos.
A conta `willian.pedroso` e a conta do próprio operador não podem ser excluídas.

Senhas atuais e hashes não são exibidos no cadastro. O link Redefinir senha
usa os validadores e o hash do Django, invalida sessões anteriores e marca
`LocalAccount.must_change_password`, reutilizando a troca obrigatória existente.
Senhas redefinidas não são registradas em auditoria. A troca da própria senha
continua disponível em `/conta/senha/`.

`AccountAudit` registra ator, alvo, instante, ação e mudanças antes/depois dos
campos cadastrais e de `ADMIN_PORTAL`. Redefinição registra apenas a ação.
Mudanças efetivas de grupos e permissões também são comparadas no backend.
Salvar sem alterações não registra `AccountAudit` ou `LogEntry` e não exibe
mensagem de modificação. Outros grupos e permissões não são editáveis nesse fluxo.
Os formulários de criação e edição têm apenas Salvar e Sair sem salvar na faixa
de ações. Salvar permanece na edição; na criação, abre a edição da nova conta.
Sair sem salvar retorna à lista, com confirmação do navegador se houver mudanças
pendentes. O link de exclusão permanece nas ferramentas do usuário, separado.
A migração `0005_accountaudit_changes` adiciona a coluna JSON sem editar contas.
Deve ser aplicada primeiro em homologação, antes de implantar o código.

Permissões de chamados e anexos continuam independentes: acesso ao cadastro
não concede visibilidade adicional. O grupo `ADMIN_PORTAL` mantém a visibilidade
que já possuía. Nenhuma alteração dispara operações no Planner.

Se LDAP for habilitado futuramente, o diretório continuará sendo a origem de
nomes, grupos e credenciais dessas identidades e poderá sobrescrever mudanças
locais na revalidação. Redefinição local não altera senha do AD.

Validação isolada: `.venv/Scripts/python.exe -m pytest` usa SQLite em memória
e usuários sintéticos; não aplicar migrações ou comandos de importação ao banco
real durante os testes. Nenhum commit ou push faz parte deste procedimento.

Roteiro e resultados das melhorias de 05/11/2026:
[homologation-improvements.md](homologation-improvements.md).
