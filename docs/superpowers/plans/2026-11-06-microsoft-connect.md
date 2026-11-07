# Conexão simplificada Microsoft

Implementar o pedido autorizado usando o OAuth/PKCE existente. Não modificar aprovações,
flags de publicação, dados existentes, volumes ou o ambiente da porta 8000. Sem commit/push.

1. Escrever e executar testes de prontidão, configuração inicial protegida, conexão,
   expiração, permissões, desconexão e reconexão, com transporte Microsoft simulado.
2. Centralizar o diagnóstico local; preservar veto explícito das duas flags OAuth.
   Reutilizar IDs, estratégia e chave já injetados pelo armazenamento privado.
3. Permitir ao administrador salvar o Client Secret inicial cifrado no banco pelo painel,
   sem alterar liberações. Preferir a configuração privada existente quando presente.
   Acrescentar migration aditiva, sem aplicar aos dados reais durante a implementação.
4. Reutilizar esse segredo na troca e renovação de tokens; manter PKCE e estado de uso único.
   Tornar explícita a validação de escopo e os erros seguros com caminho para tentar novamente.
5. Acrescentar desconexão POST/CSRF local, apagar tokens da conexão e permitir reconexão.
6. Executar suíte completa, lint dos arquivos alterados, checks Django e revisão do diff.
   Documentar configuração inicial, aprovações pendentes e teste pelo navegador.

A configuração inicial pela interface foi escolhida porque o segredo privado está vazio
nesta instalação. A alternativa de editar o arquivo privado por conexão contraria o pedido.
O armazenamento local não concede consentimento no Entra nem substitui aprovação de segurança.

Concluído e validado junto ao módulo de formulários: 403 testes aprovados no total,
revisão independente, Ruff e checks Django aprovados. A aplicação da migration e a
implantação foram deixadas pendentes para revisão conjunta das migrations solicitada
na tarefa de formulários. Nenhuma aprovação foi alterada e nenhuma chamada Graph realizada.
