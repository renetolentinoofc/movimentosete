# Movimento 7

Plataforma nova do Movimento 7: Next.js/React no frontend, Flask REST na API e PostgreSQL como fonte de verdade. Inclui canal institucional, inscrições, perfis, loja, exposição/leilão, galeria e painel administrativo.

## Estrutura

- `apps/web`: Next.js 16, React 19, TypeScript estrito e CSS por tokens;
- `apps/api`: Flask 3.1, SQLAlchemy 2, serviços de domínio e OpenAPI 3.1;
- `migrations`: primeira migração completa Alembic;
- `packages/ui`: design tokens compartilhados;
- `tests`: testes API e frontend;
- `docs`: arquitetura, banco, operação, LGPD e deploy.

## Desenvolvimento local

Requer Node 24+, Python 3.13/3.14, Docker e PostgreSQL.

```bash
docker compose up -d postgres
python3 -m venv .venv
.venv/bin/pip install -e 'apps/api[dev]'
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
export DATABASE_URL=postgresql+psycopg://movimento7:movimento7-local@127.0.0.1:54327/movimento7
export INITIAL_ADMIN_PASSWORD='defina-uma-senha-local-forte'
PYTHONPATH=apps/api FLASK_APP=wsgi:app .venv/bin/flask db upgrade
PYTHONPATH=apps/api FLASK_APP=wsgi:app .venv/bin/flask seed
npm ci
PYTHONPATH=apps/api FLASK_APP=wsgi:app .venv/bin/flask run --port 5000
npm run dev -w @movimento7/web
```

Abra `http://localhost:3000`. O seed pode ser repetido sem duplicar categorias, papéis, parceiros ou produtos. Para recriar somente o banco local, remova o volume Docker explicitamente e execute migração/seed novamente; nunca faça isso em recurso externo.

## Qualidade

```bash
.venv/bin/ruff check apps/api/movimento7 tests/api
.venv/bin/pytest tests/api
npm run lint -w @movimento7/web
npm run typecheck -w @movimento7/web
npm test -w @movimento7/web
npm run build -w @movimento7/web
```

## Deploy

Veja `docs/DEPLOY_RENDER.md`. O `render.yaml` declara serviços, banco, health checks, migração e variáveis sem valores secretos. Nenhum push, Blueprint sync ou deploy faz parte da preparação local.

## Feature flags e integrações

- `AUCTION_BIDDING_ENABLED=false`: aguarda regras e validação jurídica;
- `PAYMENT_PROVIDER=manual`: cria pedido pendente sem simular pagamento;
- `MEDIA_PROVIDER=local`: Drive fica desativado até OAuth e chave de criptografia estarem configurados;
- envio automático de e-mail/WhatsApp fica desligado sem provedor e credenciais.
