# Assunto configurável e avanço por seleção — plano

**Objetivo:** somente Empresa e Setor fixos; Assunto editável e avanço automático nas seleções, preservando Voltar e Observações do TI.
**Arquitetura:** ampliar o JSON de campos existente com os tipos subject/priority, sem models ou migrations. Chamados sem assunto recebem nome do formulário (suporte legado: Suporte técnico); prioridade ausente recebe NORMAL. Assunto curto legado explicitamente chamado Assunto continua reconhecido. Snapshots e dados históricos não são alterados.
**Restrições:** checkout e branch atuais, sem commit/push/deploy, volumes e porta 8000 intocados. Não sobrescrever trabalho não commitado. Hashes dos arquivos de Observações preservados em `.tmp/forms-before-observations.json` para conferência final.

- [x] Testes backend RED → implementação → GREEN: formulário sem assunto, opcional/obrigatório, remoção/publicação/histórico, assunto legado, prioridade configurável, fallback padrão e Planner real com mocks.
- [x] Editor: paleta Assunto/Prioridade, padrão sem perguntas extras, validação e limites. Atualizar apenas testes cujas expectativas de campos fixos/títulos mudaram intencionalmente.
- [x] Seleções iniciais: botões submit nativos com nome/valor para empresa/setor, avanço sem JavaScript e sem Continuar; feedback e trava contra duplo envio no JS. Formulários permanecem links diretos com um clique.
- [x] Voltar existente na mesma página: conservar campos/anexos e handlers; trocar somente seleções por opções clicáveis que avançam. Ao escolher o formulário atual, restaurar perguntas. Integrar etapas ao histórico via history.state/popstate sem armazenar respostas. Outra escolha de formulário mantém a confirmação existente de perda de perguntas incompatíveis.
- [x] Testes navegador: editor, clique/teclado/toque, empresa/setor/formulário, reclick em selecionado, Voltar/histórico, retenção de texto/FileList, revisão final manual e ausência de duplicatas em desktop/mobile. Não usar Graph real nem dados de homologação.
- [x] Verificação: suíte relevante/geral, teste Edge descartável de Observações, cinco testes Node de leitura, Ruff, checks Django, migrations check, hashes preservados e documentação de testes futuros 8010.

**Decisões:** prioridade é também configurável pois o pedido exige somente Empresa e Setor como campos padrão. Não alterar configurações Docker nem publicar. Preservar a falha preexistente documentada de test_compose em vez de alterar infraestrutura para satisfazê-la.

## Fechamento

Execução no checkout e branch originais, sem alterações de infraestrutura. Nova regra de título e seleções implementadas. Testes RED/GREEN do backend e regressão da precedência de Assunto confirmados; Edge validou editor, clique/teclado/toque, histórico, FileList e envio único. Revisão independente identificou a ambiguidade entre Assunto explícito e texto legado; resolvida dando precedência ao tipo explícito, preservando a resposta antiga. Arquivos de Observações preservados por hash e testes. Resultados finais em `docs/configurable-subject-request-flow.md`.
