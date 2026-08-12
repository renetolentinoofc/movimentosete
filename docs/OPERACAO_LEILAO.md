# Operação do leilão

`AUCTION_BIDDING_ENABLED=false` é o estado obrigatório inicial. Obras e lotes publicados funcionam como exposição, sem CTA enganoso.

Quando habilitado, o serviço usa centavos inteiros, horário UTC, lock de linha PostgreSQL e chave de idempotência. O servidor calcula o mínimo, recusa lotes fora da janela e mantém histórico público anonimizado. Cancelamentos exigem permissão, justificativa e auditoria.

Antes de ativar: aprovar termos, elegibilidade, incremento, extensão ou não do encerramento, pagamento, retirada/entrega, inadimplência, cancelamento e revisão jurídica. Executar o teste concorrente em PostgreSQL e registrar a aprovação.
