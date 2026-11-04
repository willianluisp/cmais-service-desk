# ARQUIVO HISTÓRICO — integração de anexos não utilizada

> **Não aplicar as instruções abaixo.** A decisão vigente mantém os arquivos
> exclusivamente no armazenamento privado do Django, sem SharePoint, OneDrive,
> referências ou links no Planner. Novos anexos não criam publicação. Consulte
> [anexos privados e backup](private-attachments.md).

## Decisão técnica

Usar uma biblioteca/pasta dedicada em **SharePoint Online**, com ACL previamente
aprovada para a TI. A aplicação publica cópias dos PDFs/PNG/JPEG e adiciona seus
`driveItem.webUrl` em `plannerTaskDetails.references`. Esses endereços não
concedem acesso: a Microsoft exige autenticação e permissão SharePoint do técnico.
O atendimento continua exclusivamente no plano Demandas Infra TI. Nenhuma
dependência de CMAIS.LOCAL ou autorização adicional do portal é introduzida.

SharePoint é recomendado em vez de OneDrive pessoal de um colaborador: a posse,
retenção e continuidade ficam com a organização. OneDrive for Business não foi
configurado nem homologado nesta etapa. A implementação exige host corporativo
SharePoint explícito. Não usa `createLink`, convites, links anônimos, links de
organização inteira nem `@microsoft.graph.downloadUrl` pré-autenticada.

## Fluxo implementado

1. A abertura grava chamado, anexos privados e uma publicação pendente por anexo
   na mesma transação. O limite existente de cinco arquivos de até 2 MB permanece.
2. A fila de tarefas cria e vincula o cartão. A fila separada de anexos só
   processa registros cujo chamado já tenha um ID de tarefa.
3. Após todas as aprovações, a aplicação verifica a pasta e suas permissões
   visíveis pela API. Qualquer permissão de link de compartilhamento bloqueia a
   publicação; a mesma verificação é feita no arquivo antes de referenciá-lo.
4. Revalida tamanho/hash do original. O nome remoto é UUID + hash + extensão,
   sem nome do solicitante. Um GET verifica a existência antes do PUT binário;
   retentativas usam o mesmo caminho, sem criar nomes alternativos.
5. Persiste drive, pasta, ID e URL do arquivo. Se o PATCH falhar, reaproveita o
   arquivo já publicado. O PATCH altera apenas a nova referência e usa o ETag
   atualizado dos detalhes, preservando checklist, descrição e outras referências.
6. Registra um evento único no histórico. Erros são códigos sanitizados,
   com backoff/Retry-After e limite de oito tentativas; casos finais ficam FAILED.

A outbox tem PENDING, UPLOADED, PUBLISHED e FAILED. Originais, dados e concessões
existentes não são excluídos. **Não há backfill automático de anexos antigos**:
uma futura seleção para publicação retroativa depende de autorização explícita.
Nenhuma publicação é feita por GET do portal. Retenção, exclusão e revisão de
falhas finais continuam procedimentos administrativos, sem limpeza remota automática.

## Configuração e permissões a aprovar

Todos os novos parâmetros estão vazios/desligados no `.env.example` e as flags
estão forçadas para false no Compose isolado. Não houve alteração de credenciais.

| Configuração | Finalidade |
| --- | --- |
| `GRAPH_ATTACHMENTS_DRIVE_ID` | Biblioteca documental aprovada |
| `GRAPH_ATTACHMENTS_FOLDER_ID` | Pasta preexistente com ACL revisada |
| `GRAPH_ATTACHMENTS_HOST` | Host exato, como `tenant-aprovado.sharepoint.com`; obter com o administrador, não deduzir pelo Tenant ID |
| `GRAPH_ATTACHMENT_SCOPE_ENABLED` | Solicitar consentimento delegado adicional `Sites.Selected` em futura reconexão OAuth |
| `GRAPH_ATTACHMENTS_STORAGE_APPROVED` | Confirmação administrativa da ACL, retenção e destino |
| `PLANNER_ATTACHMENTS_ENABLED` | Habilitar publicação; exige também `MICROSOFT_GRAPH_APPROVED` e `PLANNER_ENABLED` |

O provedor preparado usa OAuth **delegado**, mantendo `Tasks.ReadWrite`, `User.Read`
e os escopos existentes. Para arquivos recomenda-se **Sites.Selected delegado**,
com consentimento administrativo e concessão explícita de papel `write` para a
aplicação **Service Desk C+** somente no site escolhido. O usuário Microsoft que
autoriza também precisa escrever na biblioteca/pasta: a permissão efetiva é a
interseção entre concessão da aplicação e acesso do usuário. Após consentir o
novo escopo, é necessário reconectar para emitir tokens com ele. A aplicação
não recebe `Sites.FullControl.All` e não concede suas próprias permissões.

Um administrador autorizado deve provisionar a concessão de site, por ferramenta
administrativa separada. Esse provisionamento pode exigir `Sites.FullControl.All`
no contexto administrativo que concede o acesso; não adicionar esse privilégio
ao Service Desk. Não adicionar `Files.ReadWrite.All`/`Sites.ReadWrite.All` como
atalho para um 403. A documentação do endpoint de upload lista `Files.ReadWrite`
como permissão delegada básica; o modelo Selected permite limitar o recurso.
A combinação concreta de Selected, biblioteca e leitura de `/permissions` deve
ser homologada no tenant antes da ativação, sem considerar mocks como prova.

## Decisões do supervisor/administradores Microsoft

- Escolher site exclusivo ou biblioteca restrita, drive e pasta existentes.
- Definir o grupo Entra de **técnicos autorizados**, com leitura nos anexos; a
  conta publicadora tem escrita. Revisar proprietários, visitantes, membros,
  herança, convidados e compartilhamentos; impedir links anônimos e de organização.
- Confirmar que os técnicos veem o plano e os arquivos. Acesso ao Planner não
  concede acesso ao SharePoint automaticamente e vice-versa.
- Aprovar que todos os membros autorizados da TI no destino vejam os anexos ali.
  Arquivos sensíveis que exijam equipes menores precisam de política/destino
  específicos antes de habilitar; não há concessão dinâmica por chamado.
- Definir retenção, DLP/rótulos, antivírus/quarentena e limites de acesso externo.
- Conceder consentimento e papel no site; obter os IDs e host reais sem inventá-los.
- Autorizar teste separado com arquivo sintético e verificar acesso permitido e
  negado usando contas Microsoft reais, incluindo revogação e arquivos bloqueados.

A inspeção de `/permissions` rejeita links visíveis, mas **não prova que a ACL
inteira do site é exclusiva da TI**. Grupos SharePoint, herança e políticas do
tenant exigem revisão administrativa. Por isso a aprovação do armazenamento é
obrigatória e independente da disponibilidade do token. O acesso humano ocorre
na Microsoft, não pelo portal nem pelo domínio local. Acesso de colaboradores
ao portal continua restrito aos próprios chamados e anexos.

## Referências oficiais

- [Upload binário driveItem](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0).
- [Referências e ETag do Planner](https://learn.microsoft.com/en-us/graph/api/plannertaskdetails-update?view=graph-rest-1.0).
- [Modelo de permissões Selected](https://learn.microsoft.com/en-us/graph/permissions-selected-overview).

Nenhum upload, consentimento, chamada ao tenant ou teste real foi executado nesta etapa.
