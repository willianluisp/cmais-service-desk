# Acesso, anexos e consulta técnica

Os anexos permanecem no armazenamento privado do Django. Não há URL pública,
token na URL, cópia no Planner ou publicação SharePoint. A política operacional
e o backup estão em [anexos privados](private-attachments.md).

## Concessão de acesso

Cada colaborador acessa somente seus chamados. `ADMIN_PORTAL` e superusuários
ativos possuem consulta somente leitura a todos os chamados e anexos para a
administração do portal; papéis de TI e `is_staff` não recebem esse acesso.

Registros legados `TicketAccess` e campos de responsável local são preservados
no PostgreSQL para compatibilidade e auditoria, mas concessões antigas não
autorizam a consulta de chamados de terceiros no portal. Não há migração ou
exclusão de dados. O vínculo de identidades AD/Entra existente permanece
preservado e não concede acesso adicional.

## Atendimento pela TI

Todo gerenciamento ocorre no plano Demandas Infra TI: entrada em Tarefas
pendentes, atribuição, movimentação, checklist e conclusão. O portal salva o
chamado com sua outbox na mesma transação, sem aprovação manual, e consulta
o Planner para atualizar a projeção e registrar o histórico. Retentativas e
reconciliação são preservadas; integrações continuam desativadas nesta etapa.

O Planner recebe apenas a quantidade de anexos, sem nomes, bytes ou links.
Solicitante e `ADMIN_PORTAL` acessam os arquivos pelas rotas autenticadas; os
demais usuários recebem 404 mesmo com concessão legada.

Novos uploads não criam fila de publicação externa. Estruturas SharePoint antigas
permanecem apenas para compatibilidade de dados e não são ativadas.

Superusuários mantêm administração de usuários, configuração Microsoft e
auditoria existentes, separadas do acompanhamento de chamados. A fila técnica
do painel de integrações monitora a outbox, não é uma fila de atendimento.

## Limites

Cada abertura aceita no máximo cinco PDFs, PNGs ou JPEGs, cada um até 2 MB. O
servidor valida tamanho, extensão, MIME informado e assinatura do conteúdo;
nomes são normalizados e chaves de armazenamento são aleatórias.
