# Login pelo AD com papéis no portal (`LDAP_ROLE_SOURCE=portal`)

O usuário entra no chamados com o **mesmo login e a mesma senha do Windows** (domínio CMAIS).
O AD só confere a senha. Papéis (`COLABORADOR`, `TECNICO_TI`, `SUPERVISOR_TI`, `ADMIN_PORTAL`),
ativação, `is_staff` e `is_superuser` continuam sendo dados no próprio portal.

O modo original (`LDAP_ROLE_SOURCE=ad`, padrão) não mudou: nele os papéis vêm dos grupos do AD.

## Como funciona

| Situação | Resultado |
|---|---|
| Conta do portal com `username` igual ao `sAMAccountName` (sem diferenciar maiúsculas) | Primeiro login vincula pelo `objectGUID`; depois o vínculo segue o GUID, mesmo se o login mudar no AD |
| Login digitado como `CMAIS\nome.sobrenome` ou `nome.sobrenome@cmais.local` | Aceito |
| Conta existe no AD mas não no portal | Negado. Nada é criado: quem cadastra continua sendo o administrador do portal |
| Conta desativada no AD ou no portal | Negado |
| Conta do AD recriada (GUID novo) com o mesmo login de uma conta já vinculada | Negado (não herda a conta antiga) |
| Senha local antiga de quem já entrou pelo AD | Deixa de valer (fica inutilizável) |
| Superusuário | Também entra pelo AD; mantém a senha local como **acesso de emergência** (`LDAP_LOCAL_SUPERUSER_FALLBACK=true`) |
| Sessão aberta | Revalidada no AD pelo GUID a cada `LDAP_REVALIDATE_SECONDS` (padrão 300 s). Se a conta for desativada ou o AD não responder, a sessão cai, mas o cadastro do portal não é alterado |
| "Alterar senha" e "Esqueci minha senha" | Para contas vinculadas ao AD, o portal orienta a trocar a senha pelo Windows |

A conexão exige LDAPS (ou StartTLS) com verificação do certificado pela CA corporativa e do nome do DC.

## Variáveis (`.env`)

```dotenv
LOCAL_AUTH_ENABLED=false
LDAP_APPROVED=true
LDAP_ENABLED=true
LDAP_ROLE_SOURCE=portal
LDAP_LOCAL_SUPERUSER_FALLBACK=true
AUTH_LDAP_SERVER_URI=ldaps://SERVIDOR.cmais.local:636
AUTH_LDAP_START_TLS=false
AUTH_LDAP_BIND_DN=CN=svc.ldap.chamados,OU=Servico,OU=CMAIS,DC=cmais,DC=local
AUTH_LDAP_BIND_PASSWORD='<senha da conta de serviço, entre aspas simples>'
AUTH_LDAP_USER_SEARCH_BASE=DC=cmais,DC=local
LDAP_CA_CERT_PATH=/run/secrets/cmais-ad-ca.pem
LDAP_REVALIDATE_SECONDS=300
# Opcional: só quem estiver neste grupo entra (exige AUTH_LDAP_GROUP_SEARCH_BASE)
# LDAP_ACCESS_GROUP_DN=CN=GRP_App_Chamados,OU=Grupos,OU=CMAIS,DC=cmais,DC=local
# AUTH_LDAP_GROUP_SEARCH_BASE=DC=cmais,DC=local
INSTALL_LDAP=true
COMPOSE_FILE=compose.yaml:compose.ldap.yaml
```

`compose.ldap.yaml` instala o python-ldap na imagem, monta `secrets/cmais-root-ca.pem` só leitura
em web, worker e beat, e fixa `SERVIDOR.cmais.local` no IP do DC (`LDAP_DC_IP`, padrão 192.168.1.100).

## Antes de ativar: prévia dos vínculos

Com as variáveis acima e `LOCAL_AUTH_ENABLED=true` ainda ligado, rode só a prévia (não altera nada):

```bash
docker compose run --rm -e LOCAL_AUTH_ENABLED=false web python manage.py ldap_link_report
```

`SEM_CONTA_AD` mostra quem não vai conseguir entrar: ajuste o `username` no portal para o login do
Windows dessa pessoa antes de ativar.

## Voltar ao login local

`LOCAL_AUTH_ENABLED=true` e `docker compose up -d`. Os vínculos ficam guardados. Quem já entrou pelo AD
fica sem senha local; o administrador redefine pelo portal se for preciso.
