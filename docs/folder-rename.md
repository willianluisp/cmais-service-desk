# Pasta ServiceDeskCmais

Nome oficial do produto: C+ Service Desk.

Destino: pasta `ServiceDeskCmais` no diretório escolhido pelo operador.

Os nomes Compose `cmais-service-desk` e `cmais-service-desk-isolated` devem permanecer iguais, preservando os volumes e containers existentes. Não executar `down -v`, recriar bancos nem mudar os nomes de projeto. O contexto de build e arquivos de ambiente usam caminhos relativos.

A raiz Git foi corrigida pelo responsável e confirmada em 04/11/2026 dentro de ServiceDeskCmais. Não há necessidade de repetir a migração.

Antes do primeiro commit, revisar os arquivos dentro de ServiceDeskCmais:

```powershell
git rev-parse --show-toplevel
# Deve retornar exatamente a pasta ServiceDeskCmais.
git status --short
git add --dry-run .
git add .
git diff --cached --stat
git diff --cached
# Conferir ausência de .env, segredos, anexos e arquivos gerados antes do commit.
git commit -m "Padroniza projeto C+ Service Desk"
```

Para validar sem alterar serviços:

```powershell
docker compose -f compose.isolated.yaml config --quiet
docker compose -f compose.isolated.yaml exec -T web python manage.py check
curl.exe -fsS http://127.0.0.1:8010/health/ready/
```

Referências ao nome antigo em especificações históricas registram o estado inicial e são preservadas. Favoritos de editor e projetos salvos em ferramentas externas podem exigir reabrir a nova pasta. Ambientes virtuais locais com caminhos absolutos devem ser recriados antes do uso; os containers usam Python dentro da imagem.
