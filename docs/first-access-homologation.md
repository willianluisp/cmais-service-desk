# Primeiro acesso e importação de homologação

A lista aprovada em 02/11/2026 contém 72 colaboradores. Os arquivos nominativos
ficam no diretório privado `%LOCALAPPDATA%/CmaisServiceDesk/isolated/`, fora do
projeto e do Git. O lote anterior de 64 está integralmente preservado. As 27
exclusões são conferidas pela numeração original, não pela linha física do Excel.

O comando `import_homologation_employees` exige PostgreSQL `service_desk`, origem
`http://localhost:8010`, DEBUG de desenvolvimento, integrações e LDAP desligados,
72 números aprovados, hash SHA-256 do arquivo de conferência e confirmação de
execução. A senha é recebida por entrada oculta, nunca por argumento, variável
persistida ou log. A permissão de importação compartilhada existe somente no
processo do comando, sem ativação no servidor web.

```text
python manage.py import_homologation_employees /tmp/conferencia_72.csv --sha256 HASH_VALIDADO
python manage.py import_homologation_employees /tmp/conferencia_72.csv --sha256 HASH_VALIDADO --apply --confirm-isolated-8010
```

Sem `--apply`, a operação é somente leitura. O arquivo deve ser disponibilizado
temporariamente no container isolado e removido após o uso. Nenhuma senha sai
na resposta do comando. Uma transação cria o lote completo ou desfaz a operação.
Se houver contas existentes, o comando interrompe sem sobrescrever dados.
Os registros de auditoria usam ator nulo para identificar execução pelo operador
local, sem criar administrador fictício nem atribuir a ação a outro usuário.

Somente as seis exceções de nome único aprovadas para o lote histórico são
aceitas pelo importador restrito. O nome disponível vai para `first_name`,
`last_name` fica vazio e o login é o nome em minúsculas. Os demais seguem
`nome.sobrenome`. A relação nominal e o CSV devem permanecer fora do Git.

As contas novas recebem apenas o grupo COLABORADOR, sem staff/superuser ou
permissões individuais, e `LocalAccount.must_change_password=True`.
O importador padrão continua gerando senhas aleatórias individuais. A opção
de senha compartilhada é exclusiva desta homologação local e restrita.
Antes da liberação real, substituir todas as credenciais iniciais compartilhadas
por senhas individuais seguras. Não publicar nem expor este ambiente na rede.

## Troca obrigatória

O login redireciona a `/conta/senha/`. A página apresenta um diálogo nativo com
identidade C+, duas entradas de nova senha, mostrar/ocultar e indicadores de
comprimento, conteúdo não exclusivamente numérico e confirmação. Escape e clique
externo não fecham o diálogo. Sem JavaScript, o formulário continua disponível
em uma página dedicada, sem navegação para funcionalidades.

O middleware bloqueia outras páginas, inclusive POSTs e administração. API e
HTMX recebem 403. Sair da conta continua permitido. O backend é a autoridade,
independentemente de alterações no DOM ou da execução de JavaScript.

O formulário exige 8 caracteres, aplica os validadores configurados do Django
e rejeita a senha inicial atual. A recuperação de senha mantém as mesmas
exigências enquanto a troca inicial estiver pendente. A política das contas que
já concluíram o primeiro acesso não é alterada.

A mudança de hash invalida a autenticação de sessões anteriores no próximo
acesso. `update_session_auth_hash` do Django gira a chave da sessão atual e a
preserva. Uma trava de linha impede que envios concorrentes sobrescrevam uma
senha recém-alterada. A alteração e a liberação do acesso são transacionais e
auditadas. O dashboard confirma o sucesso. Nenhum e-mail é enviado.

## Verificação

`tests/test_first_access.py` cobre nomes únicos, execução restrita, exclusões,
hash do lote, primeiro acesso, bloqueios, CSRF, senha fraca, validação Django,
divergência da confirmação, recuperação e invalidação de outras sessões.
As credenciais de testes são sintéticas. Os testes não precisam de AD/Microsoft.

## Resultado em 02/11/2026

Importação transacional concluída: 72 contas novas, 27 exclusões respeitadas,
73 contas totais. Os hashes usam sais individuais. Todas as contas novas têm
troca pendente e permissões comuns; contas anteriores e chamados foram
comparados antes/depois e preservados. O comprovante sem senhas está em
`%LOCALAPPDATA%/CmaisServiceDesk/isolated/import-final-preview-20261102/resultado_importacao.json`.

Suíte: 229 testes em SQLite e os mesmos 229 em PostgreSQL descartável, sem
falhas. Django check sem problemas e nenhuma migration nova. A validação visual
abrangeu desktop, celular, JavaScript desativado, foco, Escape, clique externo,
mostrar/ocultar e confirmação. O login real em 8010 também confirmou o modal
obrigatório e os bloqueios de páginas/API, sem trocar a senha da conta importada.
Capturas locais ficam em `.tmp/first-access-review/`, fora do versionamento.
