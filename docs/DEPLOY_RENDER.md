# Deploy no Render

## Criação inicial

O Blueprint `render.yaml` cria API, frontend e um PostgreSQL 18 na mesma região. Ele usa `preDeployCommand` para `flask db upgrade` e `initialDeployHook` para o seed inicial. A configuração segue a referência atual do Render para monorepos e Blueprints.

Antes de sincronizar, configure os valores `sync: false`: `INITIAL_ADMIN_PASSWORD` (12+ caracteres), `DEPLOYED_AT`, `GIT_COMMIT` e, se aplicável, credenciais Google e chave Fernet de mídia. Não sincronize o Blueprint sem autorização do responsável pelo Render.

## Smoke test

1. `GET /api/v1/health/live` retorna 200 sem detalhes internos.
2. `/saude`, `/`, `/participe`, `/loja`, `/leilao` e `/admin/login` respondem.
3. Login inicial exige troca de senha.
4. Uma inscrição em edição de teste gera protocolo e aparece no painel.
5. Produto sem estoque permanece impossível de adicionar/comprar.
6. Leilão exibe somente modo exposição.

## Rollback

Faça rollback do serviço para o deploy anterior pelo Render. Migrações aditivas permanecem compatíveis; não execute downgrade em produção como rotina. Se uma migração futura for incompatível, restaure backup verificado em novo banco e aponte os serviços após validação de contagens. Nunca recrie recurso externo sem autorização explícita.
