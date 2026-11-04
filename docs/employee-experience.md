# Revisão da experiência dos colaboradores

Foram mantidos os assets oficiais, azul institucional, detalhes verdes, fonte
Segoe UI existente, navegação e arquitetura Django Templates/HTMX. O foco foi
orientar abertura, confirmação e acompanhamento, sem alterar integrações.

## Telas e arquivos alterados

- `templates/tickets/create.html`: instruções de preenchimento, campos obrigatórios,
  ajuda associada ao campo, resumo de erros com links/foco, orientação para
  selecionar novamente anexos após erro e confirmação de envio em andamento.
- `apps/tickets/forms.py`: rótulos/ajuda e opção inicial de categoria mais clara;
  mesmas regras, campos e limites de negócio.
- `apps/tickets/views.py`: mensagem pós-envio com protocolo; POST vazio agora
  produz erros de formulário em vez de retornar silenciosamente um formulário
  não vinculado. Autorização, persistência e serviços continuam os mesmos.
- `templates/tickets/list.html`: categoria, prioridade, responsável, status,
  abertura/última atualização, acesso aos detalhes, limpar filtros, resultados
  vazios com ação e tabela que vira cartões completos no celular.
- `templates/tickets/detail.html`: confirmação de sucesso, metadados alinhados,
  instruções compreensíveis de integração, anexos com ação de download, datas
  semânticas no histórico e feedback de consulta/loading sem exposição de IDs
  técnicos de buckets. Rotas de download e sincronização preservadas.
- `templates/portal/dashboard.html`: hierarquia dos indicadores, lista de últimas
  solicitações, ação primária e organização consistente com as demais telas.
- `templates/base.html`: marcação da página atual na navegação e carregamento do
  script de feedback. Login, autenticação e administração não foram redesenhados.
- `static/css/portal.css`: ritmo, cartões mobile, foco com maior contraste,
  metadados, erros, confirmação, anexos, diálogo e estados desabilitados/loading.
- `static/js/portal.js`: prevenção de duplo envio no navegador, aviso de envio,
  recuperação ao voltar pelo navegador e mensagem de erro HTMX compreensível.
- `static/js/attachments.js`: miniaturas locais, ampliação por diálogo nativo,
  Escape/retorno de foco, remoção individual e validações de seleção sem truncar
  silenciosamente a lista. Não faz upload antecipado.
- `apps/core/middleware.py`: CSP permite `blob:` apenas em imagens para as
  miniaturas locais. Scripts continuam self, objetos bloqueados, sem CDN ou URL
  externa liberada. Validação dos arquivos no servidor permanece igual.

O link de recuperação e os campos de login foram preservados. Nenhuma regra de
Microsoft/AD, credencial, registro de usuário/chamado ou migration foi alterada.

## Validação

`tests/test_employee_experience.py` cobre formulário vazio, erros vinculados,
confirmação com protocolo, histórico/anexo preservados, categoria na listagem,
estados vazios, recuperação de filtros, identidade do login e CSP restrita.
A suíte completa passou com 206 testes, Ruff sem erros, Django check aprovado
e nenhuma migration pendente de geração.

`scripts/validate-employee-ui.py` usa Playwright e o Edge local headless com HTML
renderizado por testes e dados sintéticos. Todas as requisições são interceptadas:
não faz login real, não grava chamados no portal e não acessa Microsoft. Foram
verificados 1440x1000 e 390x844, sem overflow de página ou exceções JavaScript.
Verifica miniaturas reais, ampliação por teclado, Escape/retorno de foco, remoção,
limite de arquivos, bloqueio de upload antes de confirmar, estado de envio e
mensagem de falha de consulta simulada. Capturas ficam em `.tmp/ui-review/`,
fora do Git. Protocolos nas capturas pertencem aos testes, não aos dados reais.

Isso é uma revisão de acessibilidade básica, não uma certificação WCAG completa.
Os componentes nativos preservam navegação e validação sem dependências de UI.

Para reproduzir, gere HTML dos testes com `PORTAL_UI_CAPTURE_DIR=/tmp/cmais-ui-preview`,
copie a pasta para `.tmp/ui-preview/` e execute o script visual com Python que
tenha Playwright instalado. Ele utiliza o Edge já instalado; não é dependência
do portal nem altera sua imagem de produção.
