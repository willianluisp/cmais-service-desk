# C+ Service Desk — plano de redesign

**Objetivo:** tornar os fluxos existentes compreensíveis para colaboradores e administradores, preservando a marca e as regras de negócio.
**Arquitetura:** Django templates, CSS do protótipo aprovado, componentes compartilhados e JavaScript progressivo local. Nenhuma dependência adicional.
**Especificação funcional:** `C:\Users\reuniao\Downloads\prompt_codex_redesign_cmais.txt`, lido integralmente.
**Referência visual final e prioritária:** `design/prototipo.html`, também lido integralmente. O arquivo foi copiado de Downloads porque o caminho `design/` não existia. A orientação posterior do usuário substitui a direção visual inicial. Uma única implementação no mesmo checkout; revisão independente somente de leitura.

## Restrições

- Logos oficiais intactas. Componentes, menu navy #12233e, azul de ação #2366c5 e demais superfícies conforme o Stitch aprovado; nenhuma marca fictícia.
- Preservar URLs, modelos, integrações, permissões, campos, arquivos privados e auditoria.
- Sem commit/push/deploy, alterações nas portas 8000/8010, credenciais ou migrations em bancos em execução.
- Testes somente com SQLite em memória e Microsoft simulada. Prévia gerada com dados fictícios, sem consultar serviços existentes.

## Etapas

- [x] Estrutura global: navegação recolhível, conta, navegação mobile, feedback e componentes acessíveis.
- [x] Colaborador: início, progresso empresa/departamento/formulário, dados e revisão sem perder campos; anexos dinâmicos; lista e detalhes.
- [x] Administração: cadastros, formulários/publicação/lixeira, usuários/grupos e integração guiada; ações destrutivas separadas e confirmadas.
- [x] Conta e erros: login, recuperação, primeiro acesso e páginas 400/403/404/500.
- [x] Verificação: testes de perfis, erros, etapas e telas; suíte completa, Django check, lint e navegador em 360/390/1366/1920 px.
- [x] Relatório de arquivos, cobertura, resultados, pendências e prévia isolada.

## Pontos de revisão

1. Empresa e departamento continuam validados no servidor, inclusive acessos diretos.
2. Sem persistência de respostas ou senhas no armazenamento do navegador; revisão usa nós de texto.
3. Exclusão lógica exige ADMIN_PORTAL, inclusive superusuário; restauração e snapshots permanecem intactos.
4. Sem ações Microsoft automáticas pela interface; ativação avisa sobre a fila antiga.
5. Sem JavaScript, formulários continuam enviáveis; conteúdo acessível por teclado, com erro localizado e sem overflow.

## Auditoria

Telas: início público/autenticado; login e senhas; seleção de empresa/departamento/formulário; suporte padrão e dinâmico; listagem/detalhes/arquivados/exclusões; empresas/departamentos; editor/prévia/ordenação/listagem/lixeira/exclusão de formulários; admin Django de usuários/grupos; integração Microsoft.

As três melhorias constam de `docs/implementation-companies-deletion-planner.md` e estão implementadas. O modelo possui comentários; o redesign mostra os públicos existentes, sem expor notas internas. Não existe endpoint de envio pelo colaborador: não apresentar um botão simulado. Departamentos são globais, compartilhados por todas as empresas; formulários são autorizados por grupos, não associados a departamentos.

Decisão: manter execução no checkout solicitado e não criar commits/worktrees nem tocar serviços existentes. Reutilizar endpoints atuais; acrescentar apenas a consulta autenticada dos próprios dados em `/conta/` e o filtro optativo `view=mine`, que restringe o conjunto já autorizado.

Revisões: corrigidos título HTML com marcação indevida, retorno de foco de anexos, texto incorreto da busca de usuários, preservação de `view=mine` nos filtros e invalidação da revisão ao voltar às etapas. A configuração Compose e sua falha de teste pré-existente permanecem intactas.
