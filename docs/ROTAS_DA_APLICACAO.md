# Rotas da aplicação

## Web pública

| Rota | Renderização | Fonte |
|---|---|---|
| `/` | SSR com cache curto | conteúdo, edição, perfis, produtos, lotes, galeria e parceiros |
| `/quem-somos` | estática revalidável | CMS |
| `/participe` | SSR + formulário cliente | categorias/edição/API |
| `/movimento-7` | SSR + filtros/lightbox | galeria publicada |
| `/loja` e `/loja/[slug]` | SSR | catálogo/estoque público |
| `/carrinho` | dinâmica | carrinho em cookie opaco/servidor |
| `/checkout` | dinâmica/noindex | carrinho e pedido |
| `/pedido/[codigo]` | dinâmica/noindex | código + token assinado |
| `/leilao` e `/leilao/[slug]` | SSR/polling | lotes publicados |
| `/parceiros` | revalidável | parceiros ativos |
| `/contato` | SSR + formulário cliente | settings/API |
| legais e acessibilidade | revalidável | CMS versionado |
| `/saude` | dinâmica | proxy do liveness sem detalhes |

## API pública

| Método e rota | Observação |
|---|---|
| `GET /api/v1/site` | conteúdo público agregado |
| `GET /api/v1/editions/current` | edição publicada atual/próxima |
| `GET /api/v1/categories` | onze categorias ativas |
| `POST /api/v1/registrations` | honeypot, rate limit e protocolo |
| `POST /api/v1/registrations/{protocol}/files` | upload autorizado e limitado |
| `GET /api/v1/profiles[/{slug}]` | somente publicados |
| `GET /api/v1/gallery` | filtros/paginação |
| `GET /api/v1/partners` | período e visibilidade |
| `GET /api/v1/products[/{slug}]` | preços/estoque calculados no servidor |
| `POST /api/v1/carts` e mutações de itens | carrinho opaco persistente |
| `POST /api/v1/checkout` | idempotência e reserva de estoque |
| `GET /api/v1/orders/{code}` | exige token assinado |
| `GET /api/v1/auction-lots[/{slug}]` | publicação/exposição |
| `POST /api/v1/auction-lots/{id}/bids` | 404 funcional quando feature desligada |
| `POST /api/v1/contact` | consentimento, protocolo e antispam |
| `GET /api/v1/health/live` | processo, sem dependências |

## Administração

Todas as rotas abaixo exigem sessão, permissão e CSRF em mutações: `/api/v1/admin/auth/*`, `dashboard`, `editions`, `registrations`, `profiles`, `categories`, `products`, `inventory`, `orders`, `payments`, `fulfillments`, `artworks`, `auction-lots`, `bids`, `gallery`, `partners`, `content`, `settings`, `communications`, `users`, `roles`, `privacy`, `audit`, `system` e `health/ready`.

Listagens aceitam no máximo 100 itens. Campos de ordenação possuem allowlist. Recursos ausentes retornam 404; conflito de estado/idempotência retorna 409; validação retorna 422; limite retorna 429.
