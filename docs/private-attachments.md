# Anexos privados e backup

## Política vigente

Os anexos permanecem no armazenamento privado do Django. Não existe rota de
arquivos estáticos, URL pública, token na URL, cópia no Planner ou publicação
SharePoint.

- O colaborador ativo consulta somente seus próprios chamados e anexos.
- Um usuário ativo do grupo `ADMIN_PORTAL` (ou superusuário) possui consulta
  somente leitura a todos os chamados, histórico e anexos pelo portal.
- `TECNICO_TI`, `SUPERVISOR_TI`, `is_staff` e concessões legadas `TicketAccess`
  não ampliam a visibilidade.
- Detalhe, miniatura, visualização e download repetem a autorização no backend;
  alterar UUIDs na URL retorna 404.

O papel administrativo não cria fluxo de atendimento no portal. Atribuição,
movimentação e conclusão continuam exclusivas do Planner.

## Validação e armazenamento

Cada abertura aceita até cinco arquivos PDF, PNG, JPG ou JPEG, com 1 byte a
2 MB por arquivo. O servidor confere tamanho, extensão, MIME declarado e
assinatura do conteúdo. O nome original é normalizado; o caminho físico usa
UUID aleatório e não revela colaborador nem nome do arquivo.

Downloads usam `Content-Disposition: attachment`. A visualização inline aceita
somente `application/pdf`, `image/png` e `image/jpeg`, usa `nosniff`, CSP
restritiva, autenticação, autorização e `Cache-Control: no-store`.

No ambiente isolado, `/app/media` está montado no volume Docker
`cmais-service-desk-isolated_isolated_attachments`. Recriar o container web não
remove arquivos. Não execute `docker compose down -v`, `docker volume rm` ou
limpeza de volumes sem backup e autorização.

## Backup

Os metadados ficam no PostgreSQL e os bytes no volume. Os dois precisam ser
copiados na mesma janela. Grave backups fora do Git e do OneDrive:

```powershell
$backupRoot = Join-Path $env:LOCALAPPDATA 'CmaisServiceDesk\backups'
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

docker run --rm `
  --mount type=volume,src=cmais-service-desk-isolated_isolated_attachments,dst=/data,readonly `
  --mount "type=bind,src=$backupRoot,dst=/backup" `
  alpine:3.21 tar -C /data -czf "/backup/attachments-$stamp.tar.gz" .

docker exec cmais-service-desk-isolated-db-1 `
  pg_dump -U portal -d service_desk -Fc -f "/tmp/service-desk-$stamp.dump"
docker cp "cmais-service-desk-isolated-db-1:/tmp/service-desk-$stamp.dump" `
  (Join-Path $backupRoot "service-desk-$stamp.dump")
docker exec cmais-service-desk-isolated-db-1 rm "/tmp/service-desk-$stamp.dump"
```

Calcule SHA-256 dos dois arquivos e registre data, ambiente e quantidade de
anexos. Teste restauração somente em banco e volumes descartáveis. Criptografe
e restrinja o diretório de backup conforme a política corporativa.

## Planner

A descrição mantém protocolo, solicitação e correlação. Quando há anexos,
acrescenta somente a contagem. Nomes, bytes e URLs não são enviados à Microsoft.
O envio automático continua controlado por `PLANNER_ENABLED`.
