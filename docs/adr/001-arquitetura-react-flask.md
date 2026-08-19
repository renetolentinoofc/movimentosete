# ADR 001 — Monorepo Next.js e Flask

- Status: aceita
- Data: 2026-08-12

## Contexto

O Movimento 7 precisa combinar conteúdo indexável, formulários interativos, operação administrativa, comércio, galeria e leilão. A plataforma começa sem banco ou código legado. Os documentos fornecidos definem identidade e requisitos, não uma arquitetura a preservar.

## Decisão

Usar um monorepo com dois processos implantáveis:

- `apps/web`: Next.js 16, React 19 e TypeScript 5.9 em modo estrito. Server Components são o padrão. Client Components ficam restritos a formulários, carrinho, menus, filtros, uploads e atualizações de estado.
- `apps/api`: Flask 3.1, SQLAlchemy 2, Flask-Migrate/Alembic e PostgreSQL. A API REST versionada contém todas as regras de negócio e emite OpenAPI 3.1.
- `packages/ui`: tokens CSS e componentes React reutilizáveis sem identidade visual de terceiros.
- `packages/config`: configuração TypeScript e convenções compartilhadas.

O navegador conversa com `/api/*` no domínio do frontend. O Next.js encaminha essas chamadas ao Flask sem reproduzir regras de negócio. Sessões administrativas usam cookie opaco `HttpOnly`; mutações usam CSRF. Dados comerciais e decisões de autorização permanecem no Flask/PostgreSQL.

## Limites

- Web: renderização, acessibilidade, estado transitório e apresentação.
- API: validação autoritativa, autenticação, RBAC, idempotência, estoque, pedidos, lances, auditoria e integrações.
- PostgreSQL: fonte de verdade, constraints, locks e histórico.
- Provedores externos: adaptadores opcionais para mídia, pagamento, comunicação e erros. A ausência de credenciais produz estado desativado explícito.

## Alternativas rejeitadas

- SPA pura: não atende HTML indexável e performance inicial.
- Next.js como único backend: contraria o requisito Flask e concentraria regras em duas camadas caso um BFF crescesse.
- JWT em `localStorage`: amplia impacto de XSS e dificulta invalidação de sessão.
- Microserviço por domínio: complexidade operacional desnecessária para a primeira versão.
- WebSocket obrigatório: polling condicional é suficiente enquanto o volume do leilão não justificar infraestrutura persistente.

## Consequências

Há dois builds e dois serviços no Render. O contrato OpenAPI e os testes de contrato evitam divergência. O PostgreSQL é obrigatório para testes de concorrência; SQLite fica limitado a testes unitários sem locks ou semântica específica.

## Versões

As versões iniciais foram verificadas nos registros oficiais de pacotes em 2026-08-12: Next 16.3, React 19.2, Flask 3.1 e SQLAlchemy 2.0. O TypeScript 7 estava publicado, mas ainda não era aceito pelo `openapi-typescript` 7; por isso o frontend fixa TypeScript 5.9.3, que mantém modo estrito sem forçar uma árvore incompatível. O projeto fixa versões no lockfile e atualiza dependências por PR com CI.
