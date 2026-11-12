# Checklists configuráveis por formulário

## Entrega local

O editor administrativo oferece **Checklist do Planner**, com habilitação opcional, inclusão, edição, remoção, setas de ordenação e prévia. O limite é 20 itens e a aplicação limita cada título a 100 unidades UTF-16, validando também no backend e impedindo títulos duplicados. Nenhuma dependência foi adicionada.

Para configurar: abra **Formulários → Criar/Editar → Checklist do Planner**, habilite, preencha os itens, confira a prévia e publique. Salvar rascunho não altera a configuração publicada. Desabilitar e publicar afeta apenas novos chamados. Duplicar um formulário copia a configuração para um novo rascunho.

## Arquitetura e persistência

- `FormDefinition.checklist_enabled` e `checklist_items`: configuração em edição.
- `FormDefinition.published_checklist`: versão interna publicada, separada de `published_snapshot`, que continua público e sem itens internos.
- `PlannerTaskProvisioning.checklist_snapshot`: cópia imutável da lista publicada no instante da abertura, na mesma transação do chamado e da submissão. Cada item recebe UUID derivado do UUID do chamado e da posição na cópia.
- A outbox registra IDs reconhecidos, IDs/ETag da tentativa em andamento e data de conclusão da inclusão automática. O checklist de execução continua pertencendo ao Planner; a projeção `Ticket.planner_checklist` é somente leitura.

Migrations aditivas: `custom_forms/0005_formdefinition_checklist_enabled_and_more.py` e `planner_integration/0008_plannertaskprovisioning_checklist_acknowledged_ids_and_more.py`. Defaults vazios/desabilitados preservam os registros antigos. Não existe backfill de tarefas nem aplicação retroativa de modelos.

## Criação e recuperação

1. O formulário publicado fornece o snapshot interno ao criar o chamado.
2. O worker existente cria/reconcilia e vincula a tarefa antes de enviar o checklist. A descrição mantém o fluxo existente.
3. Lê `GET /v1.0/planner/tasks/{id}/details` e seu próprio `@odata.etag`.
4. Envia `PATCH` para o mesmo endpoint com `If-Match` e somente IDs ainda não reconhecidos, `isChecked: false` e `orderHint`. Itens manuais, títulos já alterados e itens concluídos não são reenviados. Descrição, referências, responsáveis, prazo, bucket e status não fazem parte desse PATCH.
5. O diário é salvo antes do HTTP. Conflitos 409/412 causam até três leituras/tentativas; persistindo a falha, a outbox existente agenda nova execução. Autenticação, autorização, indisponibilidade e throttling usam o tratamento existente, inclusive `Retry-After` e pausa compartilhada. Os logs registram identificador do provisionamento e código de erro, sem conteúdo de credenciais.
6. A falha não apaga a tarefa vinculada: o retry segue o vínculo já salvo, sem novo POST de tarefa. Uma conclusão automática reconhecida não é executada novamente.

O worker verifica também os 20 itens remotos, incluindo os manuais. Se não houver espaço, registra `CHECKLIST_LIMIT` e preserva a lista até que a equipe resolva o limite no Planner.

### Resposta ambígua e remoção manual

Um timeout ou interrupção do processo pode ocorrer após o Planner aceitar a escrita. No retry, IDs presentes são reconhecidos sem sobrescrita. Se os ausentes estiverem associados ao mesmo ETag original, uma nova tentativa com os mesmos IDs é segura. Se o ETag mudou e algum ID em andamento está ausente, não é possível distinguir com segurança uma remoção manual de uma inclusão que não chegou a ocorrer.

Nessa situação, o código registra `CHECKLIST_RECONCILIATION` e não recria itens. O administrador com acesso ao chamado deve conferir e ajustar a tarefa no Planner e usar **Conferi: manter checklist atual do Planner**. O POST exige autenticação, papel administrativo, acesso ao chamado, CSRF e confirmação; repete as verificações sob lock e registra evento interno. A ação aceita a lista remota, sem PATCH ou alteração do modelo. Itens ausentes não serão recriados. O worker retoma as etapas restantes normalmente.

## Personalização e permissões

No detalhe de um chamado autorizado, o TI vê a projeção interna e **Personalizar no Planner**. O link abre o Planner; localize a tarefa pelo número do chamado no plano existente. Na seção nativa **Lista de verificação**, adicione/remova itens, edite os pendentes e reordene conforme a interface do Planner permitir. Preserve os itens concluídos. Use **Atualizar status** ao voltar ao portal; a projeção respeita os `orderHint` remotos. Nenhuma mudança individual altera o formulário ou outros chamados.

Administradores existentes (`ADMIN_PORTAL` ou superusuário) configuram os modelos. A visualização interna exige `TECNICO_TI`, `SUPERVISOR_TI` ou administração, além do acesso prévio ao chamado pela política `visible_tickets`. Pertencer ao TI não concede acesso geral aos chamados. As regras existentes de `TicketAccess` e demais permissões não foram ampliadas.

Solicitantes comuns recebem um objeto de detalhe com checklist e contadores removidos antes da renderização. Os itens não entram no snapshot público, nos cards, nos campos de solicitação ou no JSON de Atualizar status. O histórico de conferência é interno e segue o filtro existente. Não há endpoint público de edição de itens. Permissões Microsoft e login local permanecem inalterados; no Planner, a visibilidade continua seguindo o acesso já concedido pela organização.

## Limitações preservadas

- Chamados sensíveis continuam exclusivos do portal, sem tarefa no Planner. O checklist não é provisionado nesses chamados; o editor mostra um aviso. Isso inclui desligamento quando o formulário usa a política sensível existente. Enviar esses chamados ao Planner exigiria uma mudança separada de política.
- Tarefas antigas e formulários sem checklist não recebem itens retroativamente.
- A edição de execução é feita no Planner, sem controles locais concorrentes de progresso. O link abre a página principal do Planner, para evitar depender de rotas internas de tarefas não documentadas.
- Não houve chamada autenticada real ao Microsoft Graph nesta entrega; os testes usam transporte simulado. Nenhuma credencial, permissão Microsoft ou configuração de produção foi alterada.

## Validação automatizada

- Suíte padrão: `python -m pytest -q` — 670 aprovados, 8 pulados (3 dependem de PostgreSQL e 5 são opt-in de navegador).
- Testes novos: `tests/test_planner_checklists.py` cobre 25 casos, incluindo modelos, publicação, reordenação/remoção, compatibilidade, snapshots independentes, erros Graph, conflitos, crash após PATCH, preservação de progresso/remoção manual, privacidade HTML/JSON, papéis e CSRF.
- Navegador: `RUN_FORMS_BROWSER=1 python -m pytest tests/test_custom_forms_browser.py -q` — aprovado no Edge headless com banco descartável, viewport desktop 1440px e celular 390px, sem overflow horizontal. O roteiro existente foi atualizado para empresa/setor, revisão de envio e confirmação de ações, além do checklist. Capturas locais em `.tmp/custom-forms-ui/editor-desktop.png` e `editor-mobile.png` foram inspecionadas.
- Ruff, Django system check, consistência das migrations e `git diff --check` aprovados. Revisão independente sem defeitos acionáveis.
- PostgreSQL 17 descartável: 672 aprovados, 5 pulados e 1 falha preexistente; as migrations foram aplicadas em banco de teste vazio. Os 25 casos novos também foram executados separadamente nesse banco: todos aprovados.

### Falha preexistente identificada no PostgreSQL

**Atualização:** a correção posterior à versão `3c939d4` está descrita em [proteção de concorrência](planner-concurrency.md). O histórico abaixo registra o diagnóstico anterior à correção.

`tests/test_ticket_deletion.py::test_inflight_planner_work_finishes_before_archive` espera que o arquivamento bloqueie enquanto o POST remoto da tarefa está em andamento. O worker original já libera a transação antes do HTTP e verifica o cancelamento ao persistir o vínculo; por isso o arquivamento não bloqueia como esse teste pressupõe.

A mesma falha foi reproduzida isoladamente numa cópia de `git archive HEAD`, sem as alterações desta entrega, usando PostgreSQL descartável. A política de arquivamento e o teste original foram preservados, evitando uma alteração de concorrência fora do escopo. A suíte PostgreSQL completa, portanto, **não está integralmente verde**; essa divergência deve ser tratada separadamente antes da preparação de produção.

## Validação recomendada com Microsoft Graph real

Realizar em homologação, com plano e usuários de teste já autorizados. A documentação exige `Tasks.ReadWrite` delegado ou `Tasks.ReadWrite.All` de aplicação para esse endpoint; não conceder permissões adicionais automaticamente.

1. Configurar um formulário comum de teste com dois itens e publicar. Confirmar que outro formulário, sem checklist, permanece independente.
2. Abrir o chamado como solicitante; conferir que os itens não aparecem nos cards, formulário, detalhe ou respostas de rede do portal.
3. Executar o worker existente de homologação e conferir uma única tarefa, com dois itens pendentes na Lista de verificação nativa e na ordem configurada.
4. No Planner, concluir um item, alterar o título de outro, adicionar um terceiro e reordenar. Atualizar status no portal como TI com acesso e confirmar a projeção; repetir como solicitante e confirmar a privacidade.
5. Publicar um modelo diferente e abrir outro chamado. Conferir que apenas a nova tarefa usa o novo modelo e a anterior preserva personalização/progresso.
6. Simular falha temporária controlada no transporte de homologação após o vínculo, incluindo conflito 412 e resposta perdida após PATCH. Confirmar que o retry não duplica tarefas/itens e não reabre itens concluídos.
7. Testar o caso ambíguo com remoção manual: verificar alerta, proibição de recriação automática e ação administrativa de aceitar o estado remoto.
8. Conferir formulário desabilitado, tarefa anterior à implementação e formulário sensível, preservando os comportamentos descritos acima.

## Arquivos da entrega

Modificados:

- `apps/custom_forms/{models,forms,services,views}.py`
- `apps/planner_integration/{models,client,services,views,urls}.py`
- `apps/tickets/views.py`
- `templates/custom_forms/editor.html`, `templates/tickets/detail.html`
- `static/css/forms.css`
- `scripts/validate-custom-forms-ui.mjs`, `tests/test_custom_forms_browser.py`
- `docs/custom-forms.md` (link para esta documentação)

Criados:

- As duas migrations citadas acima.
- `apps/planner_integration/checklists.py`
- `static/js/planner-checklist-editor.js`
- `templates/custom_forms/_planner_checklist.html`, `templates/tickets/_planner_checklist.html`
- `tests/test_planner_checklists.py`
- `docs/superpowers/plans/2026-11-12-planner-checklists.md` e este documento.

## Referências técnicas

- [PATCH de plannerTaskDetails, ETag e permissões](https://learn.microsoft.com/en-us/graph/api/plannertaskdetails-update?view=graph-rest-1.0)
- [Limites do Planner](https://learn.microsoft.com/en-us/planner/planner-limits)
- [Ordenação nativa por orderHint](https://learn.microsoft.com/en-us/graph/api/resources/planner-order-hint-format?view=graph-rest-1.0)

A entrega encerra a Fase 1. Commit, push e preparação da atualização de `/opt/cmais-service-desk` dependem da aprovação explícita da Fase 2. Nenhuma migration foi aplicada em produção, nenhum container existente foi reiniciado e nenhum deploy foi executado.
