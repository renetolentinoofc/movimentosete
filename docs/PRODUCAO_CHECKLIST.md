# Checklist de produção

Este checklist deve ser concluído antes de promover uma versão para o domínio público. A preparação local não executa deploy, migração externa ou alteração de credenciais.

## Configuração obrigatória

- [ ] `APP_ENV=production`.
- [ ] `DATABASE_URL` aponta para PostgreSQL de produção.
- [ ] `SECRET_KEY` é aleatório e não é compartilhado com desenvolvimento.
- [ ] `PUBLIC_BASE_URL` e `CORS_ORIGINS` usam somente os domínios oficiais.
- [ ] `SESSION_COOKIE_SECURE=true`.
- [ ] `MEDIA_PROVIDER=google_drive` está autorizado.
- [ ] `MEDIA_TOKEN_ENCRYPTION_KEY` foi gerada com Fernet.
- [ ] `GOOGLE_DRIVE_PRODUCT_FOLDER_ID` e `GOOGLE_DRIVE_GALLERY_FOLDER_ID` apontam para pastas separadas.
- [ ] `ERROR_REPORTING_DSN` está configurado em um serviço de observabilidade aprovado.

A API falha no startup quando as credenciais essenciais do provedor de mídia ou do e-mail live estão incompletas. A tela administrativa de prontidão também sinaliza mídia, observabilidade, banco, e-mail, pagamentos e leilão.

## Banco e deploy

- [ ] Backup automático do PostgreSQL está habilitado no Render.
- [ ] Um backup recente foi verificado antes da migração.
- [ ] `flask db upgrade` foi executado pelo `preDeployCommand`.
- [ ] O seed inicial só é executado na criação controlada do ambiente.
- [ ] O health check `/api/v1/health/live` retorna 200.
- [ ] O Cron Job `movimento7-gallery-reconcile` executa sem erro.
- [ ] O Cron Job `movimento7-expire-inventory` executa a cada 10 minutos sem erro.

## Smoke test pós-deploy

1. Abrir o frontend oficial e confirmar páginas institucionais.
2. Fazer login administrativo e trocar a senha inicial.
3. Abrir Sistema e confirmar banco, mídia e prontidão.
4. Criar um álbum de teste, enviar uma imagem e confirmar a publicação.
5. Confirmar que a imagem publicada é entregue pelo URL público.
6. Verificar uma execução recente da reconciliação da galeria.
7. Confirmar que uma inscrição e um contato aparecem no painel.
8. Confirmar que produto sem estoque não pode ser comprado.
9. Criar um pedido de teste não pago e confirmar que a reserva é liberada após o vencimento.

## Rollback e incidentes

- Faça rollback do serviço para o deploy anterior pelo Render.
- Não execute downgrade de migração como rotina.
- Em falha de banco, restaure um backup verificado em um recurso separado e valide contagens antes de redirecionar a aplicação.
- Em falha do Drive, preserve o catálogo e suspenda publicação de novas mídias até a reconciliação concluir.
- Nunca remova arquivos órfãos automaticamente sem decisão operacional registrada.
