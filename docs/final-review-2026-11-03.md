# Revisão final de homologação — 03/11/2026

Escopo: somente Docker isolado localhost:8010. Sem commit, push, implantação,
alteração de usuários ou escrita de tarefas no Microsoft Planner.

## Exclusão e limpeza

A Microsoft retornou 404 para a tarefa vinculada ao C+2026-000003; a leitura
do plano foi bem-sucedida e a tarefa estava ausente da lista. O POST real de
sincronização confirmou a exclusão lógica e retornou HX-Redirect /chamados/.
Nenhuma tarefa foi excluída pela aplicação durante esta revisão.

Os três registros C+2026-000001, 000002 e 000003 foram arquivados por seleção
explícita, com evento de auditoria e outboxes CANCELLED. Permanecem no banco;
o único anexo registrado continua no volume privado e seu arquivo existe.
Notificações pendentes vinculadas aos testes foram invalidadas sem envio.

Arquivados não aparecem em dashboard, listas, detalhes ou anexos públicos do
portal. A auditoria preserva os registros originais. A criação futura continua
gerando protocolos novos e outboxes PENDING. Reenvios do mesmo formulário usam
submission_key para retornar o mesmo chamado sem gravar anexos ou filas duplicadas.

## Interface e segurança

Mensagens são centralizadas na página base, inclusive após a exclusão.
O painel Microsoft usa controles com contraste e campos consistentes; o Django
Admin usa os assets e cores C+, preservando suas permissões. O menu administrativo
foi corrigido no mobile e o botão do estado vazio teve seu contraste restaurado.
A página pública descreve o portal atual, sem declarar histórico fictício.

Verificação com Edge/Playwright: telas reais de login, recuperação, alteração de
senha, dashboard vazio, listagem, abertura, integrações, administração e usuários
em 1440×1000 e 390×844. Capturas locais em .tmp/final-visual-review (fora do Git).
Sem erros JavaScript/console. Prévia de PNG, ampliação e remoção antes de envio
validadas no navegador, sem submissão de chamado real. Fluxos com chamados e
primeiro acesso também possuem testes automatizados em dados descartáveis.
Adicionalmente, 20 capturas de páginas sintéticas foram verificadas no Edge,
incluindo detalhes, erros e listagens preenchidas. O modal de primeiro acesso
passou em desktop, mobile e sem JavaScript: teclado, foco, Escape, backdrop,
mostrar/ocultar senha e requisitos. Nenhum desses testes enviou chamados reais.

Suíte: 273 testes aprovados; Ruff e Django check aprovados; makemigrations
--check --dry-run sem alterações. Migrations aplicadas somente no banco isolado.
O check --deploy do ambiente local apontou cinco avisos esperados: ausência
de HSTS, redirecionamento HTTPS e cookies Secure de sessão/CSRF, além de DEBUG.
Esses avisos devem ser tratados na máquina definitiva com HTTPS configurado;
não foram suprimidos nem aplicados ajustes de produção ao ambiente HTTP 8010.

## Antes da máquina definitiva

- Atualização de 04/11/2026: raiz Git corrigida dentro de ServiceDeskCmais.
  Revisar o índice e os arquivos ignorados antes do primeiro commit.
- Preparar hostname/HTTPS, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, cookies seguros,
  DEBUG=false, chave Django e segredos fora de Git/OneDrive no novo computador.
  Atualizar Redirect URI no Entra e no Django para o hostname definitivo.
- Fazer backup pareado do PostgreSQL e do volume de anexos, com teste de
  restauração em volumes novos; ver private-attachments.md. Não usar down -v.
- Substituir credenciais iniciais de homologação por credenciais individuais
  antes de liberar acesso corporativo; preservar troca obrigatória no primeiro
  acesso. Nenhuma senha foi alterada nesta revisão.
- Configurar conexão Microsoft e verificar escopos/consentimento da conta
  autorizada; nenhuma credencial deve ser copiada para o repositório.
- Habilitar PLANNER_SYNC_ENABLED e iniciar worker/beat apenas na ativação
  autorizada. Isso é independente de PLANNER_ENABLED (publicação automática).
  E-mails e SharePoint continuam desativados.

O ambiente 8010 está preparado para o teste final de homologação. Essa revisão
não constitui implantação ou homologação da infraestrutura definitiva.
