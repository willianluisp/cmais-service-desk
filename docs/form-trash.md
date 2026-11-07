# Lixeira de formulários

## Uso

Em **Administração → Gerenciar formulários**, a aba **Lixeira** aparece junto da
listagem principal. A ação **Mover para a lixeira** fica disponível na listagem e
no editor, inclusive para formulários publicados, arquivados ou com chamados.

Mover é uma remoção lógica: data, responsável e nome do responsável são registrados.
O formulário sai imediatamente da listagem principal, filtros e cards de Novo chamado.
O acesso direto e o envio de formulários na lixeira ficam bloqueados. Seus campos,
configurações, publicações anteriores, grupos e respostas não são apagados.

Na lixeira, **Restaurar como rascunho** mantém a configuração original, mas sempre
volta ao estado Rascunho. O formulário só aparece aos colaboradores depois de uma
nova publicação explícita. O arquivamento anterior continua independente da lixeira.

**Revisar exclusão definitiva** abre uma tela separada. O administrador precisa digitar
o nome exato e marcar a confirmação de irreversibilidade. O servidor repete a conferência,
verifica a revisão e bloqueia a definição durante a operação. A exclusão só remove a
definição e seus vínculos próprios de disponibilidade; não exclui usuários ou grupos.

Chamados/respostas vinculados impedem a exclusão, preservando seus snapshots e anexos,
inclusive em chamados arquivados. Outras relações reversas, inclusive relações ocultas
com exclusão em cascata, também bloqueiam a remoção. Formulários com dependências
podem permanecer na lixeira indefinidamente ou ser restaurados. Não existe limpeza automática.

As operações exigem o papel `ADMIN_PORTAL` ou superusuário, sessão ativa e CSRF.
Auditoria registra `FORM_TRASHED`, `FORM_RESTORED` e `FORM_PERMANENTLY_DELETED`
com ID, revisão e versão. O registro de auditoria sobrevive à remoção definitiva.
O nome do responsável pela remoção lógica permanece visível mesmo se sua conta for removida.

A ação antiga `delete` agora move para a lixeira, impedindo exclusão definitiva por
formulários ou links antigos. Não há alteração de permissões Microsoft nem operações Graph.

## Migration necessária — não aplicada ao banco existente

`custom_forms.0002_form_trash`, dependente de `custom_forms.0001_initial` e do modelo
de usuário configurado, adiciona à tabela `custom_forms_formdefinition`:

- `trashed_at`: data/hora opcional, com índice.
- `trashed_by`: FK opcional para o responsável, com SET_NULL.
- `trashed_by_label`: identificação do responsável no momento da remoção, inicialmente vazia.

Registros existentes permanecem fora da lixeira; nenhum formulário é arquivado,
despublicado ou removido pela migration. Não há migration de dados, movimentação de
arquivos ou alteração de tokens. A migration foi testada somente em bancos descartáveis,
inclusive com definição e resposta criadas sob o esquema anterior.

As entregas anteriores ainda podem exigir `custom_forms.0001_initial` e
`planner_integration.0006_microsoftoauthconfiguration`; verificar o plano real antes
da implantação. Esta tarefa não aplicou migrations ao PostgreSQL existente.

## Atualização do ambiente isolado 8010

Fazer o backup normal do PostgreSQL e anexos antes da janela de atualização conforme
[anexos privados e backup](private-attachments.md). Executar na raiz deste projeto.
Usar o mesmo conjunto de arquivos Compose e overrides atualmente autorizado para 8010,
preservando as liberações existentes. Os exemplos abaixo usam a configuração base isolada;
se a instalação já usa um override, acrescentá-lo ao array antes de executar os passos.
Não adicionar overrides de autorização Microsoft que ainda não tenham sido aprovados.

```powershell
$isolatedComposeArgs = @(
    '--project-name', 'cmais-service-desk-isolated',
    '--env-file', '.env.isolated',
    '-f', 'compose.isolated.yaml'
)

# 1. Construir a imagem; não recria nenhum serviço existente.
docker compose @isolatedComposeArgs build web

# 2. Revisar as migrations pendentes usando um web temporário sem publicar portas.
docker compose @isolatedComposeArgs run --rm --no-deps web python manage.py migrate --plan

# 3. Após revisar o plano e o backup, aplicar somente no banco do projeto isolado.
docker compose @isolatedComposeArgs run --rm --no-deps web python manage.py migrate --noinput

# 4. Atualizar somente o web da porta 8010, sem iniciar/recriar worker ou beat.
docker compose @isolatedComposeArgs up -d --no-deps web
```

Os serviços db/redis do projeto isolado precisam estar ativos para os comandos `run`.
Não usar `compose.yaml`, o projeto da porta 8000, `down -v`, prune ou remoção de volumes.
Os comandos acima são instruções de implantação: não foram executados nesta entrega.

Depois, abrir `http://localhost:8010/administracao/formularios/`, mover um formulário
fictício sem uso para a lixeira, restaurá-lo e verificar que retorna como rascunho.
Mover novamente e testar **Revisar exclusão definitiva**. Para um formulário usado,
a confirmação deve mostrar o bloqueio e o chamado antigo deve manter suas respostas.

## Arquivos desta implementação

- `apps/custom_forms/models.py`: metadados da lixeira.
- `apps/custom_forms/migrations/0002_form_trash.py`: schema aditivo.
- `apps/custom_forms/services.py`: transições, proteção de dependências e auditoria.
- `apps/custom_forms/forms.py`: confirmação explícita no servidor.
- `apps/custom_forms/views.py` e `urls.py`: listagem e rotas administrativas.
- `templates/custom_forms/manage.html`, `editor.html`, `trash.html` e
  `permanent_delete.html`: ações e telas na identidade C+.
- `static/css/forms.css`: abas, metadados e confirmação responsivos.
- `static/js/form-builder.js`: remoção da confirmação antiga de exclusão direta.
- `tests/test_form_trash.py`: permissões, CSRF, restauração, dependências, snapshots,
  arquivos, auditoria, revisões e preservação de dados na migration.
- `tests/test_custom_forms.py`: atualização do contrato antigo de exclusão.
- `scripts/validate-custom-forms-ui.mjs` e `tests/test_custom_forms_browser.py`:
  navegação real por lixeira, restauração e exclusão confirmada, inclusive no celular.
- `docs/custom-forms.md`, este documento e o plano da tarefa: instruções atualizadas.

## Resultado da validação

**425 testes aprovados**, sem skips, na suíte completa com PostgreSQL 17 descartável.
Inclui navegador Edge em desktop/celular, concorrência, confirmação incorreta/correta,
permissões/CSRF, dependência oculta CASCADE e upgrade 0001 → 0002 com dados fictícios
preservados. Ruff, Django check, makemigrations --check, sintaxe JavaScript e diff --check
aprovados. Revisão independente não encontrou bugs concretos no escopo da lixeira.
O banco descartável foi encerrado e os containers existentes de 8000/8010 permaneceram ativos.
