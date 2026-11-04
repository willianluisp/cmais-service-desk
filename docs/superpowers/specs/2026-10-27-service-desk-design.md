# C+ Service Desk — desenho de implementação

Data: 27/10/2026. Estado: aprovado pelo usuário em 27/10/2026; Fase 1 implementada.

Referência histórica: especificação funcional fornecida pelo responsável do projeto.

## Objetivo

Criar o portal interno de suporte da C+ Contadores: colaboradores abrem e
acompanham seus chamados; TI atende a fila; o portal consulta o Planner e
notifica mudanças quando as integrações estiverem configuradas e autorizadas.

## Constatações

- O diretório HelpDeskCmais está vazio, sem código ou repositório Git.
- Na descoberta inicial Docker não foi encontrado. Após instalação e
  reinicialização, o build e os cinco containers foram validados em 27/10/2026.
- Não há configurações verificadas de AD, certificados, grupos, OAuth ou e-mail.
- Os identificadores Microsoft fornecidos são referências de configuração;
  não demonstram consentimento, acesso ao plano ou compatibilidade de permissões.

## Arquitetura proposta

Adotar a stack da especificação: Python 3.12+, Django suportado, templates
server-side, CSS responsivo, PostgreSQL, Redis e Celery. HTMX será usado apenas
onde melhorar os formulários e a atualização de status. O backend permanece
responsável por validação, CSRF e autorização por objeto.

Um monólito Django é suficiente para o MVP e permite criar chamado, histórico e
outbox na mesma transação. Uma SPA ou serviços independentes acrescentariam
complexidade de autenticação e operação sem requisito que a justifique.

Serviços Compose: web, db, redis, worker e beat. Migrations serão executadas por
comando explícito, sem concorrência entre processos. Banco e Redis terão acesso
somente pela rede dos containers. Anexos ficarão em volume privado e serão
entregues por endpoint autenticado.

```text
HelpDeskCmais/
  manage.py
  pyproject.toml
  Dockerfile
  compose.yaml
  .env.example
  .gitignore
  .dockerignore
  README.md
  config/
    settings/{base,development,production,test}.py
    urls.py
    celery.py
    wsgi.py
  apps/
    accounts/
    tickets/
    planner_integration/
    notifications/
    audit/
  templates/
  static/
  tests/
  docs/
```

## Incremento inicial proposto: Fase 1

Entregar scaffold executável e documentado, com configuração por ambiente,
Compose e healthchecks, layout institucional em português, páginas de estado
das integrações e estrutura dos cinco apps. Não representar autenticação,
chamados ou sincronização como funcionais antes das respectivas fases.

Configurações de produção falharão de forma explícita quando faltarem segredo,
hosts ou banco adequado. Desenvolvimento/testes usarão configurações separadas;
mocks ficarão restritos a testes e nunca serão um fallback de autenticação.

O backend de e-mail local será de testes/console, sem envio externo. Planner e
LDAP iniciarão desabilitados. As variáveis necessárias terão placeholders em
`.env.example`; nenhum segredo real será criado ou incorporado ao código.

## Evolução do MVP

1. **Base:** scaffold, Docker, configuração, páginas iniciais, testes e operação.
2. **AD:** LDAPS com CA validada, identificação estável, grupos e revalidação de
   permissões; testar sucessos e falhas com mocks antes de homologação real.
3. **Chamados:** modelos, migrations, protocolos únicos, RBAC, fila TI,
   comentários, anexos privados e histórico auditável.
4. **Graph:** validar externamente tipo de plano, permissões e estratégia OAuth;
   até isso ocorrer, manter criação automática desabilitada e vínculo pendente.
5. **Planner:** cliente com timeout, validação de plano, mapeamento de status,
   sincronização POST com CSRF, rate limit, locking e idempotência.
6. **Notificações:** outbox transacional, retries limitados, deduplicação e
   provedor SMTP/Graph conforme configuração aprovada.
7. **Piloto:** homologação, HTTPS, permissões, backups e implantação autorizada.

## Regras essenciais de dados e segurança

- Colaborador acessa somente chamados próprios; TI depende de papel autorizado.
- A mesma ACL protege detalhes, comentários, histórico, sincronização e anexos.
- Comentários internos e dados privados do Planner não aparecem ao solicitante.
- Identificador AD estável vincula o perfil; senhas AD nunca são persistidas.
- TLS é obrigatório para LDAP; indisponibilidade não habilita login alternativo.
- LDAP não produz token Graph. Nenhuma criação de tarefa assumirá suporte a
  `client_credentials`; o fluxo dependerá da validação das permissões aplicáveis.
- Sincronizações registram detecção, sem inventar autor ou horário de edição.
- Chamado FECHADO não é reaberto automaticamente pelo Planner.
- Sem mudança observada, não gerar evento ou e-mail adicional.
- Eventos e outbox são gravados na transação do chamado; envio ocorre depois.
- Upload terá limites, nome aleatório, validação de conteúdo e download privado.

## Validação

Na Fase 1: testar configuração segura, timezone America/Sao_Paulo, rotas,
renderização, healthchecks e falhas de dependências sem expor credenciais.
Executar pytest, lint e Django system checks. Validar Compose e subir serviços
quando Docker estiver disponível; registrar claramente qualquer validação que
não puder ser executada. Sem Docker, testes locais não provarão o funcionamento
dos containers ou do PostgreSQL.

Nas fases seguintes: testes de autenticação e ACL, uploads, transações,
concorrência/idempotência em PostgreSQL, falhas Graph e retries da outbox,
conforme os critérios da especificação original.

## Dependências externas pendentes

AD: controlador, DNS, CA, bases de pesquisa, grupos e conta de bind.
Microsoft: tipo de plano, buckets, responsável Entra, consentimentos e política
de tokens. E-mail: provedor, remetente e destinatários autorizados. Operação:
host Docker, proxy, domínio HTTPS, limites/retenção de anexos e backups.

Esses dados não bloqueiam o scaffold. Integrações reais e implantação dependem
da configuração e autorização específicas. Nenhum deploy, alteração no AD,
consentimento Microsoft, tarefa real, commit ou push integra o incremento inicial.
