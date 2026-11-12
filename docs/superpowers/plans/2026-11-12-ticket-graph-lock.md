# Serialização de operações Graph por chamado

Objetivo: arquivamento/exclusão não confirma enquanto o chamado tem escrita Graph em execução ou resultado incerto.

- [x] Reproduzir em testes PostgreSQL com eventos: POST, descrição, leitura/PATCH do checklist, conflito, cancelamento e recuperação.
- [x] Criar mutex de sessão PostgreSQL por UUID, independente das transações curtas existentes. Worker tenta sem espera; manutenção aguarda no máximo 2 segundos e retorna erro claro. Liberar em finally; se o desbloqueio falhar, fechar a conexão.
- [x] Compartilhar o protocolo entre provisionamento e manutenção. Registrar intenção de escrita durável para descrição e demais escritas; preservar reconciliação existente para POST/checklist. Não arquivar/excluir com resultado remoto ainda incerto.
- [x] Verificar publicação de anexos e resolução administrativa; proteger os fluxos necessários sem alterar permissões ou recursos Microsoft.
- [x] Executar regressão PostgreSQL/SQLite, Ruff, Django checks e migrations; revisão independente.

Restrições: sem HTTP em transação de produção; sem commit/push/produção; preservar snapshot, UUIDs e privacidade da versão 3c939d4. O mutex de sessão exige conexão PostgreSQL com afinidade de sessão (sem pool em modo transaction). Timeout remoto não equivale a cancelamento no Graph: conciliar antes de confirmar manutenção.
