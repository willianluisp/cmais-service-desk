# Campos manuais nos formulários

**Objetivo aprovado (atualizado pelo usuário):** empresa, setor, assunto e prioridade permanecem padrão e obrigatórios; todas as outras perguntas são cadastradas manualmente por formulário, incluindo suporte.

**Arquitetura:** reutilizar o editor e os snapshots existentes. Preservar assunto e prioridade e remover localização, descrição e anexos automáticos do preenchimento. Preservar versões e respostas antigas. Localização passa a ser uma pergunta comum, sem tratamento especial pelo rótulo.

**Execução:** inline, preservando as alterações já presentes nesta pasta.

- [x] Escrever e executar testes para os quatro campos padrão, perguntas manuais e envio sem localização automática.
- [x] Ajustar campos globais, envio e suporte sem configuração; permitir publicação sem perguntas adicionais.
- [x] Disponibilizar o suporte no editor, atualizar instruções e testes afetados pelo comportamento aprovado.
- [x] Executar testes relevantes, checks Django e revisão do diff.

**Validação:** pytest com `config.settings.test` e banco descartável; não alterar o banco existente nem publicações existentes.

**Resultado:** 545 testes aprovados na suíte geral, quatro omitidos por exigirem PostgreSQL ou opt-in, e uma falha preexistente em `test_compose.py` (integrações habilitadas no compose isolado, arquivo sem alterações nesta tarefa). Os seis testes específicos finais passaram, assim como Ruff, Django check, makemigrations --check e diff --check. Edge validou quatro telas em 360, 390, 1366 e 1920 px, sem overflow, IDs repetidos, imagens quebradas ou erros JavaScript; confirmou os quatro campos padrão e ausência de localização automática.
