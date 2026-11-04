# Administração por ADMIN_PORTAL

`ADMIN_PORTAL` é um grupo de autorização do portal, não uma permissão global
do Django. Uma conta autenticada e ativa nesse grupo pode acessar `/admin/`
(cadastro de colaboradores) e `/integracoes/` (configuração e diagnóstico
Microsoft), sem precisar de `is_staff` ou `is_superuser`.

O predicado `apps.accounts.permissions.is_portal_admin` é usado no site
administrativo, nas permissões do cadastro, na navegação e nas verificações de
autorização das rotas Microsoft. Superusuários ativos existentes preservam seu
acesso. `is_staff` sozinho não autoriza a administração do portal.

Administradores por grupo podem consultar o cadastro e criar/alterar contas
comuns. Não podem atribuir grupos, permissões individuais, staff ou superuser.
Não podem alterar, desativar ou redefinir a senha de contas privilegiadas,
incluindo a própria conta administrativa. A alteração da própria senha continua
disponível no fluxo normal `/conta/senha/`. Exclusão de usuários permanece
bloqueada. A gestão de outros administradores exige superusuário autorizado ou
operação local explicitamente autorizada, nunca um formulário de colaborador.

O grupo não concede acesso aos chamados de terceiros. A consulta de chamados
e anexos continua restrita ao solicitante. Administrar o portal não cria um
fluxo de atendimento paralelo ao Planner.

Adicionar/remover a associação ao grupo concede/revoga o acesso na próxima
requisição autenticada. A troca obrigatória do primeiro acesso e CSRF continuam
valendo para administradores. Uma conta com troca pendente será redirecionada
para `/conta/senha/` antes de poder entrar nos painéis; a promoção não redefine
a senha nem libera essa restrição.

As verificações de aprovação Microsoft e os controles de confirmação de testes
permanecem inalterados. Ser ADMIN_PORTAL não habilita integrações nem realiza
chamadas externas. A promoção local é registrada em AccountAudit, preservando
o histórico anterior. Não é necessário aplicar migrations.

Validação: `tests/test_portal_admin_role.py` cobre concessão sem flags globais,
negação às outras funções, revogação, bloqueio de escalada por POST direto,
contas privilegiadas, primeiro acesso, CSRF, elegibilidade OAuth sem chamada
externa e privacidade dos chamados.
