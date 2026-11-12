# Formulários personalizados

Checklist interno opcional: [configuração, integração nativa, permissões e validação](planner-checklists.md).

Evolução atual: [campos globais, setores, ordenação, presets e solicitações sensíveis](forms-evolution.md).
As instruções de implantação e migrations adicionais desse documento têm precedência
para a versão atual do código; os comportamentos básicos abaixo continuam aplicáveis.

## Administração e uso

Administradores do papel `ADMIN_PORTAL` e superusuários acessam **Administração →
Gerenciar formulários**, abaixo da administração de usuários quando esta estiver disponível.
O módulo não concede acesso à administração de usuários ou a outros modelos Django.

Em **Criar formulário**, configure nome, descrição, ícone, ordem e disponibilidade.
Grupos em branco permitem todos os colaboradores autenticados e ativos. Os grupos
selecionados limitam tanto os cards quanto o acesso direto e o envio do formulário.
Alterações de disponibilidade entram em vigor ao publicar.
A intenção de acesso restrito fica persistida separadamente dos vínculos de grupos:
excluir o último grupo não torna o formulário público.

A paleta permite adicionar texto curto, texto longo, número, data, seleção única,
múltipla escolha, checkbox e anexo. Cada pergunta tem nome, obrigatoriedade,
ajuda e, quando aplicável, placeholder e padrão. Opções são editadas uma por linha.
Arraste a alça ou use as setas para reordenar; **Remover** altera somente o rascunho.
O editor avisa sobre alterações não salvas ao sair da página.

**Visualizar prévia** abre o rascunho atual em outra aba, sem salvá-lo e sem criar
chamados. A prévia usa o mesmo gerador Django Forms do formulário publicado.
**Salvar rascunho** preserva a publicação existente. **Publicar formulário** cria
uma nova versão e atualiza o card. **Despublicar** retorna ao estado de rascunho;
**Arquivar** impede novos envios; **Duplicar** cria um rascunho independente.
A ação **Mover para a lixeira** retira o formulário das listagens sem apagar dados.
Na [Lixeira de formulários](form-trash.md), restaure como rascunho ou revise a exclusão
definitiva, disponível somente sem chamados/respostas e outras dependências, com
confirmação explícita. O arquivamento permanece independente.

**Novo chamado** apresenta cards publicados e o suporte técnico padrão, sempre
disponível durante a transição. O caminho explícito do formulário padrão é
`/chamados/novo/suporte/`; POSTs legados em `/chamados/novo/` continuam compatíveis.

## Validação e histórico

- Esquemas limitados a 40 perguntas, 50 opções por seleção, IDs UUID exclusivos
  e tipos permitidos. Rótulos, ajuda, opções e padrões são texto, sem HTML executável.
- O navegador valida os atributos nativos e os grupos de múltipla escolha obrigatórios;
  Django repete a validação no servidor, incluindo datas, decimais, opções e arquivos.
- Número: até 14 inteiros e quatro casas decimais; data: formato ISO no armazenamento.
  Checkbox obrigatório exige marcar a confirmação. Múltipla escolha admite várias opções.
- Até cinco campos de anexo; um arquivo por campo, PDF, PNG ou JPEG válido, até 2 MB.
  Reutiliza assinatura, MIME, nome seguro, armazenamento privado e autorização do chamado.
- Respostas recebem nomes `cf_<UUID>` e jamais são atribuídas a status, solicitante,
  responsável, permissões ou outros atributos internos.
- Cada chamado conserva uma cópia do esquema publicado, metadados, versão e respostas.
  Edição, despublicação e arquivamento posteriores não reescrevem essa cópia.
- Edições concorrentes usam revisão; envios de versão obsoleta exigem recarga. A chave
  de envio existente evita duplicar chamado, respostas e filas no reenvio do navegador.
- A criação usa o serviço existente de chamados e mantém evento e filas duráveis na
  mesma transação. Não faz rede. Respostas detalhadas permanecem no portal; a descrição
  genérica do chamado direciona o atendente ao portal, sem copiar respostas para Graph.
- Solicitantes e administradores consultam respostas pelas mesmas regras dos detalhes.
  Chamados antigos permanecem compatíveis. Exclusão permanente autorizada do chamado
  remove suas respostas via CASCADE e mantém o tratamento seguro dos arquivos existente.
- Auditoria registra criação, edição, publicação, duplicação, despublicação,
  arquivamento e exclusão com IDs e versões, sem registrar respostas ou arquivos.

## Migrations pendentes — não aplicadas ao banco existente

`custom_forms.0001_initial` cria somente:

1. `custom_forms_formdefinition`: rascunho, publicação, versão e revisão.
2. `custom_forms_formdefinition_allowed_groups`: disponibilidade por grupos existentes.
3. `custom_forms_formsubmission`: respostas/snapshot, FK protegida para o formulário
   e relação única com o chamado, removida apenas junto da exclusão permanente deste.

Não adiciona campos ao Ticket, não atualiza registros existentes e não move anexos.
Depende de `tickets.0005_ticketdeletionaudit_privatefiledeletion` e `auth.0012`.
Há também `planner_integration.0006_microsoftoauthconfiguration`, da entrega Microsoft,
que cria apenas a tabela de segredo inicial cifrado, sem alterar aprovações ou conexões.
`custom_forms.0002_form_trash` acrescenta os metadados da lixeira sem mover registros
existentes. O procedimento de atualização restrito a 8010 está em [Lixeira](form-trash.md).

Antes da implantação, revisar essas migrations e o backup normal do ambiente 8010.
Aplicar somente no banco isolado, depois de disponibilizar a imagem atualizada. O módulo
exige as novas tabelas antes de servir suas páginas. Não executar rollback com respostas
reais: remover essas tabelas destruiria seus dados. Nenhum rollback foi executado.

## Verificação

Testes de backend: `python -m pytest tests/test_custom_forms.py`.
A suíte completa também cobre chamados antigos, notificações, anexos, Planner e exclusão.
Ruff, Django check e makemigrations --check conferem código e coerência dos modelos.

O teste opt-in `tests/test_custom_forms_browser.py` usa `RUN_FORMS_BROWSER=1`, Node 22+
e Edge headless local. Ele abre um servidor pytest temporário e banco descartável,
bloqueia qualquer origem diferente desse localhost e valida editor, ordenação, remoção,
publicação, cards, telas móveis, múltipla escolha obrigatória e abertura real de chamado.
Capturas fictícias ficam em `.tmp/custom-forms-ui/`. Nunca aponta ao portal existente.

Validação inicial do construtor: **403 testes aprovados**, sem skips, em PostgreSQL 17
descartável, incluindo navegador Edge e bloqueios concorrentes. Ruff, Django check,
makemigrations --check e verificação de sintaxe JavaScript aprovados. O container
descartável foi encerrado ao fim; bancos, volumes e aplicações existentes permaneceram intactos.
