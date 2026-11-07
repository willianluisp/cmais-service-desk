# Conectar Microsoft pelo painel

O fluxo reutiliza Authorization Code delegado com PKCE S256, estado de uso único
com prazo de dez minutos, retorno fixo e tokens Fernet no banco. A navegação parte
de um link interno, preservando CSP e o login local. O estado também fica vinculado
ao tenant, aplicação e endereço de retorno para rejeitar mudanças durante o login.

## Configuração inicial

Tenant ID, Client ID, estratégia delegada e chave Fernet continuam vindo da configuração
privada existente já injetada pelo Compose isolado. A chave não é regenerada: conexões
existentes precisam permanecer decifráveis. O painel mostra os pré-requisitos ausentes.

O Client Secret pode ser informado uma vez em **Integrações → Configuração inicial
protegida da aplicação**. O administrador salva somente o valor do segredo, cifrado
no banco com a chave existente. Ele não volta ao HTML, auditoria ou logs. A configuração
fica vinculada ao tenant/client atuais. Um valor salvo pelo painel substitui o valor
injetado para permitir rotação pelo navegador; sem configuração local, o segredo
privado existente é reutilizado. Troca e renovação de tokens usam a mesma resolução.

Salvar credenciais não altera `MICROSOFT_GRAPH_APPROVED`, `GRAPH_DELEGATED_OAUTH_ENABLED`
ou qualquer flag de tarefas, sincronização, testes reais, e-mail e anexos.
Enquanto faltar liberação inicial, **Conectar Microsoft** permanece bloqueado com
explicação. A liberação deve ser expressamente autorizada pelo responsável de segurança
e provisionada uma única vez na implantação aprovada, por exemplo pelo override OAuth
isolado existente. O navegador não pode remover um veto administrativo do ambiente.

No Microsoft Entra, o responsável deve confirmar o retorno Web
`http://localhost:8010/integracoes/microsoft/callback/`, as permissões delegadas
User.Read e Tasks.ReadWrite e o consentimento exigido pela organização. offline_access
permite receber refresh token. Este trabalho não altera o registro nem consentimentos
corporativos. Para aplicações Web confidenciais, PKCE acompanha o segredo:
[documentação oficial Microsoft](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow).

## Testar pelo botão depois da aprovação inicial

1. Entre como administrador em `http://localhost:8010/integracoes/`.
2. Se necessário, salve o valor do segredo no formulário protegido. Confira as pendências.
3. Depois da liberação administrativa inicial, clique **Conectar Microsoft**.
4. Autentique a conta corporativa no domínio oficial `login.microsoftonline.com`.
5. O retorno valida estado, expiração, identidade e escopo Planner explícito, cifra
   os tokens e apresenta **Conectado**. Nenhuma tarefa é criada por conectar a conta.
6. **Desconectar Microsoft** usa POST/CSRF, invalida a conexão e apaga seus tokens locais.
   O consentimento no Entra é administrado pela organização, sem revogação remota aqui.
7. Para conectar novamente, clique no mesmo botão; não há edição de .env ou terminal.

Erros de autenticação, recusa de consentimento, permissões insuficientes, sessão local
expirada e estado obsoleto apresentam mensagens seguras e link para tentar novamente.
Se uma renovação indicar autorização expirada/revogada, a conexão é invalidada e seus
tokens apagados, solicitando reconexão. Indisponibilidade transitória não apaga tokens.
Uma falha de renovação antiga só invalida a geração dos tokens que falhou, preservando
uma reconexão concorrente que já tenha gravado tokens novos.

## Situação encontrada e migration

A verificação somente leitura encontrou Tenant ID, Client ID, estratégia e chave
presentes no armazenamento privado, mas Client Secret vazio. As liberações OAuth
permaneceram desligadas. Nenhuma chamada de autenticação ou Microsoft Graph foi feita.

A migration aditiva `planner_integration.0006_microsoftoauthconfiguration` cria uma
tabela para o segredo cifrado e sua vinculação à aplicação. Não reescreve conexões,
tokens ou aprovações existentes. Não foi aplicada ao banco existente nesta entrega.

Testes com transporte simulado cobrem conexão, callback, escopos, expiração, renovação,
rotação do segredo, desconexão e reconexão, CSRF e autorização de administrador.
