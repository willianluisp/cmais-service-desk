# Melhorias de homologação — 05/11/2026

## Resultado

Implementação local das 11 melhorias, reutilizando Django Admin, templates,
identidade C+, controles de acesso, auditoria, armazenamento e serviços existentes.
Nenhum commit/push, alteração de usuário real, chamado histórico, banco ou volume
Docker, configuração de produção ou chamada externa ao Planner.

1. **Login sugerido:** criação sugere `nome.sobrenome`, removendo acentos,
   normalizando caixa e espaços. Alteração manual interrompe a sugestão. Edição
   mantém o login salvo. Backend rejeita duplicatas inclusive diferenças de caixa.
2. **Logo:** preservada a oficial nos templates compartilhados do portal, login,
   primeiro acesso e Admin. Proporção automática, sem cópia adicional nas páginas.
   Corrigido contraste do Admin mesmo quando o sistema operacional usa tema escuro.
3. **Sem mudança:** comparação de campos persistidos, grupos e permissões. POST
   idêntico não registra auditoria própria nem LogEntry, nem mensagem de alteração.
4. **Botões:** apenas Salvar e Sair sem salvar. Salvar permanece na edição;
   ao criar, abre a edição da nova conta. Sair sem salvar retorna à lista.
   Exclusão preservada nas ferramentas do usuário, fora da faixa de ações.
   `beforeunload` alerta quando há diferença real,
   inclusive ao sair pelo link ao portal. Salvar não dispara esse aviso.
5. **Contas:** criação/exclusão somente Willian ou recuperação por superusuário;
   flags globais nunca concedidas na criação. Senha temporária gerada com `secrets`,
   validada no backend e exibida no formulário de criação para entrega segura.
   Depois de salvar fica somente o hash; troca obrigatória reutiliza `LocalAccount`.
   Exclusão exige POST confirmado com CSRF e revalidação no backend. Relações de
   chamados, anexos, auditoria, diretório, Microsoft e demais modelos bloqueiam
   exclusão, inclusive relações SET_NULL/CASCADE. Somente o marcador LocalAccount
   e associações de grupos/permissões podem acompanhar uma conta sem histórico.
   A conta protegida e o próprio operador nunca podem ser excluídos. Contas criadas
   pelo fluxo já têm auditoria e devem ser desativadas para preservar esse histórico.
6. **Contagens:** resumo do portal é agregado depois da busca, status e prioridade,
   sobre o mesmo queryset autorizado e antes da paginação. Arquivados/excluídos
   seguem a política existente de visibilidade. As facetas “Mostrar contagens”
   do cadastro de usuários já funcionavam; foram verificadas com filtro ativo.
7. **Retorno:** botão Voltar ao portal destacado no cabeçalho compartilhado do Admin.
8. **Categoria:** removida da abertura, listagem e detalhe do colaborador. FK,
   registros históricos e payload Planner preservados. Criações do portal usam
   `Atendimento geral`, criada atomicamente quando necessária. Um POST forjado
   não escolhe categoria. Categoria padrão desativada gera erro controlado, sem
   reativar silenciosamente um cadastro. Chamadas internas existentes com categoria
   explícita continuam funcionando. Nenhuma migração de dados foi criada/executada.
9. **Integrações:** capacidades locais compartilhadas entre botões e endpoints.
   Operações disponíveis têm botão azul; indisponíveis ficam cinza/desabilitadas.
   Conexão armazenada, disponibilidade, erro e envio em andamento são distintos.
   OAuth requer configuração local válida; consultas/teste também verificam plano,
   autorização e estratégia; teste exige flag específica e bucket de entrada.
   Mapeamento é operação local e requer buckets consultados. Client credentials
   não exige conexão delegada. Expiração delegada preserva renovação autorizada.
   GET não contata Microsoft. Permissões remotas só são confirmadas na operação.
10. **Início:** página interna compacta com atalhos Abrir chamado, Meus chamados,
    Acompanhar solicitações e Administração conforme permissão. Sem banner,
    fotografia ou link promocional. Dashboard preserva indicadores e solicitações.
11. **Login:** botão explícito Login, azul C+ com detalhe verde, foco acessível e
    ícone discreto. Rotas e formulários de autenticação preservados.

## Arquivos alterados

- Contas: `apps/accounts/admin.py`, `apps/accounts/admin_forms.py`,
  `static/js/managed-users.js`, `templates/admin/auth/user/managed_form.html`,
  `templates/admin/auth/user/managed_delete.html`.
- Chamados: `apps/tickets/forms.py`, `apps/tickets/services.py`,
  `apps/tickets/views.py`, `templates/tickets/list.html`, `templates/tickets/detail.html`.
- Integrações: `apps/planner_integration/admin_panel.py`,
  `apps/planner_integration/views.py`, `templates/portal/integrations.html`.
- Interface: `templates/base.html`, `templates/portal/home.html`,
  `templates/portal/dashboard.html`, `templates/portal/_quick_access.html`,
  `static/css/admin-cmais.css`, `static/css/portal.css`.
- Testes: `tests/test_homologation_improvements.py`, `tests/test_user_management.py`,
  `tests/test_employee_experience.py`, `tests/test_full_homologation.py`,
  `tests/test_graph_delegated_oauth.py`, `tests/test_microsoft_admin.py`.
- Validação visual: `scripts/validate-homologation-ui.mjs`,
  `scripts/validate-employee-ui.py`.
- Documentação: este arquivo, `docs/homologation-improvements-plan.md` e
  `docs/portal-administration.md`.

## Verificação manual no navegador

Use somente uma instância de homologação descartável com contas fictícias. Não
execute botões de operação remota enquanto estiver verificando a apresentação.

| Item | Caminho e verificação |
| --- | --- |
| 1 | Willian → Administração de usuários → Adicionar. Digite `Róbson` / `Lémes`: login `robson.lemes`. Edite o login e depois o nome: o manual deve permanecer. Na edição de conta existente, mudar nome não muda login. Tente login duplicado: erro no formulário. |
| 2 | Confira logo em `/`, `/login/`, primeiro acesso, `/admin/` e cadastro; reduza a janela para celular e confira proporção. |
| 3 | Abra conta fictícia e salve sem editar: permanece na edição sem mensagem de modificação; histórico do Admin permanece sem evento novo. |
| 4 | Altere um nome e salve: permanece na edição com confirmação. Salve novamente sem mudar nada: sem nova mensagem ou auditoria. Crie conta fictícia: Salvar abre sua edição. Nos dois formulários, digite sem salvar e clique Sair sem salvar: confirme o alerta e verifique que nenhuma alteração foi persistida. |
| 5 | Crie conta fictícia copiando a senha temporária. Faça login com ela: troca obrigatória antes de qualquer página. Desative-a pelo cadastro. Outro ADMIN_PORTAL deve receber 403 no cadastro/criação/exclusão. Conta protegida não oferece exclusão. Conta com histórico mostra bloqueio na confirmação. Exclusão de conta legada sem vínculos exige confirmação explícita. |
| 6 | `/chamados/`: combine busca, prioridade e status. Soma dos cartões deve coincidir com total de resultados autorizados; compare colaborador e ADMIN_PORTAL. No cadastro, teste Mostrar contagens com Ativo e busca. |
| 7 | No Admin, use Voltar ao portal; com formulário alterado há aviso e nenhuma gravação automática. |
| 8 | `/chamados/novo/`: abra solicitação fictícia sem categoria. Lista/detalhe não mostram o campo; protocolo, anexos e histórico continuam disponíveis. |
| 9 | `/integracoes/`: com integração desligada, operações remotas cinza. Ambiente preparado mostra ações disponíveis coloridas. Mapeamento só habilita com snapshot de buckets. Confirmar chamada real depende de autorização da empresa; não clicar nos testes remotos durante esta homologação visual. |
| 10 | Visite `/` sem login e com colaborador/administrador. Confira atalhos, contagens, últimos chamados, permissões e ausência de marketing. Teste em 1440px e 390px. |
| 11 | Sem sessão, confira Login destacado no cabeçalho e navegue usando Tab/Enter. |

## Validações e limites do ambiente

Comandos usados: `ruff check .`; `manage.py check --settings=config.settings.test`;
`manage.py makemigrations --check --dry-run --settings=config.settings.test`;
`python -m pytest -q`. Banco dos testes SQLite em memória; anexos temporários;
Graph simulado. Após simplificação dos botões: **336 testes aprovados, 1 ignorado** (concorrência
que exige PostgreSQL descartável). Ruff aprovado; Django sem problemas; nenhuma
migração nova necessária. Sintaxe JS e whitespace do diff verificados. Revisão
independente somente leitura não encontrou problemas concretos.

UI: `node scripts/validate-homologation-ui.mjs`, Edge headless local sem pacotes
npm. Todos os requests das páginas são interceptados e servidos a partir do HTML
dos testes e dos estáticos locais. Vinte capturas em 1440×1000 e 390×844, com
checagens de layout, imagens, JS de sugestão/manual/edição, dois controles de ação,
confirmação nativa ao sair da criação/edição com alterações não salvas,
botões desabilitados e carregamento. Artefatos ignorados pelo Git em
`.tmp/homologation-ui/`. O script Playwright anterior foi atualizado para o
formulário sem categoria; o runtime Playwright não está instalado neste ambiente.

Pendências externas: teste de concorrência exige PostgreSQL descartável; confirmar
configuração/consentimento/scopes Microsoft e permissões do plano exige ambiente
e autorização da empresa. Não foram alteradas flags de integração, credenciais,
contas reais ou tarefas Planner. Esta validação visual básica não substitui
homologação dos fluxos corporativos com a infraestrutura da empresa.
