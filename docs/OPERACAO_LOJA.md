# Operação da loja

## Fluxo

Produtos começam em `draft` e não aparecem publicamente até terem descrição, mídia, variantes e estoque confirmados. O carrinho guarda no navegador apenas um token opaco `HttpOnly`; os itens estão no banco. No checkout a API bloqueia as variantes, recalcula preços, verifica disponibilidade e cria reserva com expiração.

O pedido registra snapshots de nome, SKU, variante e preço. `pending_payment` não significa pago. O adaptador `ManualPaymentProvider` retorna `pending_manual` e nunca simula aprovação.

## Operação segura

1. Cadastre produto, fotos, composição e variantes.
2. Registre estoque real e confira SKU único.
3. Publique o produto somente após revisão.
4. Confirme pagamentos apenas com permissão financeira e evidência do provedor.
5. Expire reservas vencidas antes de disponibilizar novamente o saldo.
6. Preserve pedido, pagamento e movimentos; use cancelamento ou estorno.

Frete, regiões atendidas, gateway e política final de troca dependem de decisão comercial/jurídica.
