"""Custom exceptions for the langchain-pr402 package."""


class X402PaymentError(Exception):
    """Raised when the x402 payment handshake fails."""

    pass


class X402FacilitatorError(X402PaymentError):
    """Raised when the facilitator returns a non-200 response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Facilitator returned {status_code}: {detail}")


class X402SigningError(X402PaymentError):
    """Raised when transaction signing fails (e.g. payer pubkey not found)."""

    pass
