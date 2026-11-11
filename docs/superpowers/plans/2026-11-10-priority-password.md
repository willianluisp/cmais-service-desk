# Prioridade administrativa e visibilidade de senha

Objetivo: retirar a prioridade do preenchimento do colaborador, configurar prioridade padrão abaixo das permissões do formulário e unificar mostrar/ocultar senha em todas as páginas existentes.

Diagnóstico: oito formulários na homologação, nenhum campo de prioridade nos dados salvos. O código em andamento aceita o tipo priority e o usa no POST; esse comportamento será removido. Senha já tem toggle textual no primeiro acesso, mas login, alteração, recuperação e administração não compartilham o recurso.

- [x] TDD backend: campo default_priority no FormDefinition com migration aditiva, padrão NORMAL; snapshot publicado inclui o valor. Rascunho não altera publicação e mudança não reescreve chamados históricos. Duplicação preserva a configuração.
- [x] Campos de prioridade legados (tipo dedicado ou rótulo inequívoco) ficam fora do preenchimento e paleta, mas continuam preservados nos esquemas/histórico. Backend ignora prioridade fornecida pelo usuário e lê somente o snapshot autorizado. Não remover outras perguntas.
- [x] Editor: controle default_priority imediatamente após audience, ajuda exata solicitada; papéis administrativos existentes mantidos. Nenhuma alteração de permissões.
- [x] Planner: mapear BAIXA→9, NORMAL→5, ALTA→3, CRITICA→1 na criação. Não escrever prioridade em sincronizações futuras ou tarefas reconciliadas. Se o POST com prioridade receber HTTP 400 explícito, repetir uma vez sem prioridade; nunca repetir em timeout/5xx/429/resultado ambíguo. Sem novas permissões ou chamadas reais de escrita.
- [x] Senhas: script/CSS compartilhados nos layouts portal, login, primeiro acesso e admin; reaproveitar botões do primeiro acesso. Botão type=button, SVG olho/olho riscado, rótulo/pressed/controls, valor/autocomplete/foco preservados. Nenhum armazenamento/log/requisição. Manter validadores existentes.
- [x] Testes: backend prioridades/permissões/histórico/mapping/fallback, Edge desktop/mobile editor/login/primeiro acesso/alteração/admin/reset, regressões de fluxo/observações e testes Node. Ruff, Django check, migration check e suíte geral (única exclusão Compose preexistente).
- [x] Documentação final com arquivos, migration não aplicada em homologação, dados reais vs mocks, restrições e teste futuro em 8010. Sem commit/push/deploy, sem mudar branch ou volumes/8000.

## Resultado

Concluído no código, sem deploy. 609 testes Python aprovados (7 skips e 1 exclusão Compose preexistente), três testes Edge explícitos e cinco testes Node. Ruff, checks Django, migrations check e diff check aprovados. Uma migration aditiva foi criada e exercitada somente em bancos descartáveis; não foi aplicada à homologação. Revisão independente não encontrou P1/P2. Quinze arquivos protegidos de Observações/fluxo permaneceram idênticos por hash. A consulta preventiva de metadados dos oito formulários da homologação não alterou dados. Nenhuma escrita real no Graph.
