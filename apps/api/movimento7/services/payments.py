from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentRequest:
    order_code: str
    amount_cents: int
    currency: str
    idempotency_key: str


@dataclass(frozen=True)
class PaymentResult:
    status: str
    provider_reference: str | None = None
    instructions: str | None = None


class PaymentProvider(ABC):
    @abstractmethod
    def create(self, request: PaymentRequest) -> PaymentResult:
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, body: bytes, signature: str) -> bool:
        raise NotImplementedError


class ManualPaymentProvider(PaymentProvider):
    """Modo honesto: registra pedido pendente, sem declarar pagamento aprovado."""

    def create(self, request: PaymentRequest) -> PaymentResult:
        return PaymentResult(
            status="pending_manual",
            instructions="A equipe confirmará disponibilidade e instruções de pagamento.",
        )

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return False
