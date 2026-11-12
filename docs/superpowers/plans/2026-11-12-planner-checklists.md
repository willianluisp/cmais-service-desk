# Checklists configuráveis do Planner

**Objetivo:** modelos internos por formulário, provisionados na lista nativa do Planner.
**Arquitetura:** configuração rascunho/publicada separada do snapshot público; snapshot imutável e IDs por chamado na outbox existente. Personalização e execução diretamente no Planner; projeção interna apenas para TI com acesso prévio ao chamado.
**Restrições:** sem novas dependências, sem e-mail, sem alteração de acesso, sem commit/push/deploy. Chamados sensíveis continuam fora do Planner. Configuração nova não retroage.

- [x] Testar e implementar configuração opcional, publicação independente, duplicação e snapshot na outbox; migrations aditivas.
- [x] Testar e implementar PATCH parcial com ETag, IDs estáveis, diário de envio, recuperação e conflitos, preservando progresso e alterações remotas.
- [x] Testar e implementar editor acessível com reordenação/prévia e isolamento no backend da visualização interna.
- [x] Executar regressão, lint e verificação de migrations; documentar configuração, personalização e validação real.

Riscos de revisão: falha após PATCH aceito; remoção manual antes do retry; rascunho alterado antes de envio; limite remoto ocupado por itens manuais; técnico sem acesso ao chamado.
Decisão: em resposta ambígua seguida de ETag alterado e item ausente, exigir conferência em vez de ressuscitar uma possível remoção manual. Erros definitivos (400/401/403/409/412/429) permitem tentativa posterior com nova leitura.

Validação final: 670 aprovados/8 pulados na suíte padrão; 672 aprovados/5 pulados/1 falha preexistente no PostgreSQL 17; 25 testes específicos aprovados também no PostgreSQL; navegador desktop/mobile aprovado; Ruff, system check e migrations consistentes. Revisão independente sem defeitos acionáveis.

Decisão: preservar a concorrência existente de arquivamento. A falha PostgreSQL `test_inflight_planner_work_finishes_before_archive` foi reproduzida no HEAD original e está documentada em `docs/planner-checklists.md`; não foi alterado comportamento fora do escopo. Commit/push/produção não executados.
