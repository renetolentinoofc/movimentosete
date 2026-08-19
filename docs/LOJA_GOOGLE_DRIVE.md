# Imagens de produtos: Google Drive

## Arquitetura

1. O administrador autoriza o Drive uma única vez pelo painel (`drive.file` + PKCE).
2. A API criptografa o refresh token com `MEDIA_TOKEN_ENCRYPTION_KEY` e nunca o envia ao frontend.
3. O upload é feito pela API para a pasta definida em `GOOGLE_DRIVE_PRODUCT_FOLDER_ID`; a primeira imagem de cada produto cria automaticamente uma subpasta com o slug do produto, e uploads seguintes reutilizam essa pasta.
4. A API publica o arquivo como leitor público e grava em `product_media` o provider, a URL `uc?export=view&id=...`, o texto alternativo e as dimensões.
5. O frontend usa somente a URL registrada; o banco permanece como catálogo e índice, e o Drive como armazenamento de binários.

## Configuração

No Google Cloud, habilite a Drive API, crie um cliente OAuth Web e cadastre a URL de callback:

`https://SEU-DOMINIO/api/v1/admin/integrations/google-drive/callback`

Configure na API:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://SEU-DOMINIO/api/v1/admin/integrations/google-drive/callback
GOOGLE_DRIVE_PRODUCT_FOLDER_ID=ID_DA_PASTA
MEDIA_PROVIDER=google_drive
MEDIA_TOKEN_ENCRYPTION_KEY=chave-fernet
```

No primeiro uso, entre em Sistema, autorize o Drive e depois cadastre o produto. O produto começa como rascunho; adicione variantes, estoque e imagens antes de publicar.

## Operação e segurança

- Use uma pasta exclusiva para imagens de produtos.
- Não coloque refresh tokens, client secret ou IDs sensíveis no frontend.
- O texto alternativo é obrigatório para acessibilidade.
- O código atual não apaga arquivos do Drive automaticamente; exclusões devem ser reconciliadas antes de habilitar remoção automática.
- Em desenvolvimento, mantenha `MEDIA_PROVIDER=local`; o fluxo do Drive deve ser validado com uma conta/pasta de sandbox antes da produção.
