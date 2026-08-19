# Deploy no Render

## Criação inicial

O Blueprint `render.yaml` cria a API, um Cron Job de reconciliação da galeria e um PostgreSQL 18 na mesma região. A API usa `preDeployCommand` para `flask db upgrade` e `initialDeployHook` para o seed inicial. A configuração segue a referência atual do Render para monorepos e Blueprints.

Antes de sincronizar, configure os valores `sync: false`: `INITIAL_ADMIN_PASSWORD` (12+ caracteres), `DEPLOYED_AT`, `GIT_COMMIT`, credenciais Google, chave Fernet de mídia e `GOOGLE_DRIVE_GALLERY_FOLDER_ID`. O Cron Job roda a cada seis horas em UTC e usa a mesma base PostgreSQL. Não sincronize o Blueprint sem autorização do responsável pelo Render.

O checklist completo está em [`docs/PRODUCAO_CHECKLIST.md`](PRODUCAO_CHECKLIST.md). Ele deve ser revisado antes de qualquer promoção para produção.

## Reconciliação da galeria

O serviço `movimento7-gallery-reconcile` executa:

```bash
PYTHONPATH=apps/api FLASK_APP=wsgi:app flask reconcile-gallery --limit 500
```

O job termina após a verificação; ele não mantém um processo contínuo. Arquivos ausentes, divergentes ou órfãos são registrados para tratamento administrativo e não são removidos automaticamente.

## Smoke test

1. `GET /api/v1/health/live` retorna 200 sem detalhes internos.
2. `/saude`, `/`, `/participe`, `/loja`, `/leilao` e `/admin/login` respondem.
3. Login inicial exige troca de senha.
4. Uma inscrição em edição de teste gera protocolo e aparece no painel.
5. Produto sem estoque permanece impossível de adicionar/comprar.
6. Leilão exibe somente modo exposição.

## Rollback

Faça rollback do serviço para o deploy anterior pelo Render. Migrações aditivas permanecem compatíveis; não execute downgrade em produção como rotina. Se uma migração futura for incompatível, restaure backup verificado em novo banco e aponte os serviços após validação de contagens. Nunca recrie recurso externo sem autorização explícita.
