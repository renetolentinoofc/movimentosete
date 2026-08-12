# Plano de criação da plataforma Movimento 7

## Premissas e referências

A plataforma é nova: não existe schema, aplicação ou URL antiga a preservar. A criação começa em uma branch órfã. Foram lidos o manual técnico/visual, a apresentação institucional e a auditoria do painel. Foram localizadas as logos do Movimento 7 e dos quatro parceiros. `movimento7_site.html` e o arquivo com nome exato `Logotipo grafite colorido com MOVIMENTO 7.png` não estavam no workspace; a composição `header.png` e `logo_movimento7.png` disponíveis são as referências oficiais usadas sem redesenho.

## Rotas web planejadas

Públicas: `/`, `/quem-somos`, `/participe`, `/movimento-7`, `/loja`, `/loja/[slug]`, `/carrinho`, `/checkout`, `/pedido/[codigo]`, `/leilao`, `/leilao/[slug]`, `/parceiros`, `/contato`, `/privacidade`, `/termos-de-servico`, `/politica-de-troca-e-entrega`, `/regras-do-leilao`, `/acessibilidade`, `/saude`, `robots.txt` e `sitemap.xml`.

Administrativas: `/admin`, `/admin/entrar`, `/admin/inscricoes`, `/admin/perfis`, `/admin/edicoes`, `/admin/loja`, `/admin/pedidos`, `/admin/leilao`, `/admin/galeria`, `/admin/parceiros`, `/admin/conteudo`, `/admin/comunicacao`, `/admin/usuarios`, `/admin/auditoria`, `/admin/privacidade` e `/admin/sistema`.

## API planejada

Toda API usa `/api/v1`, envelope `data/meta/error`, códigos de erro estáveis, paginação limitada, ordenação por allowlist e `X-Request-ID`.

- Público: site, edição atual, categorias, inscrições/uploads, perfis publicados, galeria, parceiros, produtos, carrinho, checkout, pedido com token, lotes, lances sob feature flag, contato e liveness.
- Administração: autenticação/sessão/CSRF, dashboard e CRUDs dos domínios, publicações, estoque, pagamentos, entregas, auditoria, privacidade e readiness.
- Webhooks: pagamento autenticado e idempotente, criado somente quando um provedor real for configurado.

O inventário detalhado fica em `docs/ROTAS_DA_APLICACAO.md`; o contrato executável fica em `apps/api/openapi/openapi.yaml`.

## Módulos e dados

Os Blueprints são `auth`, `registrations`, `profiles`, `events`, `store`, `auctions`, `gallery`, `partners`, `content`, `communications`, `privacy`, `audit` e `health`. Serviços transacionais encapsulam checkout, estoque, publicação, lance, reconciliação de mídia e privacidade.

O schema inicial contém identidade/RBAC, edições, categorias, inscrições, perfis, mídia, loja completa, leilão, galeria, parceiros, CMS, contato, sessões, idempotência, rate limit e auditoria. Índices priorizam busca/status/data e chaves públicas. Constraints protegem valores monetários, quantidades, unicidade e integridade. O dicionário e o ER estão em `docs/BANCO_DE_DADOS.md`.

## Segurança e privacidade

- Cookies administrativos `HttpOnly`, `SameSite=Lax`, `Secure` em produção; sessão máxima de oito horas e `session_version`.
- CSRF double-submit vinculado à sessão e cabeçalho `X-CSRF-Token`.
- Hash Werkzeug, bootstrap único sem fallback, troca obrigatória, lockout progressivo e mensagens sem enumeração.
- RBAC normalizado por roles/permissões; frontend apenas reflete o que o servidor autoriza.
- Rate limit persistente, honeypot, limites de corpo/upload, MIME real, nomes UUID, headers de segurança e logs JSON redigidos.
- Consentimento versionado, finalidade, retenção, exportação e anonimização auditadas sem PII nos logs.

## Mídia e integrações

`MediaProvider` oferece armazenamento local de desenvolvimento e Google Drive opcional. Drive usa PKCE, `drive.file`, refresh token criptografado por chave versionada separada, derivados e compensação. `PaymentProvider` começa com pedido manual: ele nunca marca pagamento como aprovado. Comunicação automática e monitoramento externo também começam desativados.

## Desenvolvimento e testes

1. Fundação executável e primeira migration completa.
2. Design system e conteúdo institucional.
3. Inscrições/perfis.
4. Loja.
5. Arte, leilão, galeria e parceiros.
6. CMS e administração.
7. build, migração, E2E, performance, acessibilidade e documentação.

CI executa Ruff, mypy, pytest, migration smoke, OpenAPI validation, ESLint, TypeScript, Vitest, Next build e Playwright/axe. PostgreSQL em container cobre locks de estoque e lances. Fakes cobrem Drive e pagamento, sem internet ou credenciais reais.

## Deploy e rollback

O Blueprint cria frontend, API e um PostgreSQL novo. O pre-deploy da API executa `flask db upgrade` e seed idempotente. Health checks são separados. Rollback de código usa o commit anterior somente se compatível com schema; migrations futuras seguem expand/contract. Recriação automática só é permitida para bancos locais/teste. Recurso externo nunca é apagado sem autorização.

## Critério de corte

O lançamento exige migration em banco vazio, seed repetível, builds, testes backend/frontend/E2E, smoke test, validação mobile/teclado, ausência de segredo e comportamento honesto das features desativadas. Leilão monetário permanece desligado até validação jurídica/comercial.
