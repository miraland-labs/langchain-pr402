"""x402 Requests Wrapper for LangChain.

Provides ``X402RequestsWrapper``, a Pydantic v2 model that wraps Python
``requests`` and transparently handles HTTP 402 Payment Required challenges
using the x402 protocol on Solana.
"""

import base64
import json
import logging
from typing import Any, Dict, Optional

import requests
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import to_bytes_versioned

from langchain_pr402.exceptions import (
    X402FacilitatorError,
    X402PaymentError,
    X402SigningError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PR402_FACILITATOR_URL_PRODUCTION = "https://ipay.sh"
PR402_FACILITATOR_URL_PREVIEW = "https://preview.ipay.sh"

# USDC SPL token mint addresses
USDC_MINT_MAINNET = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_MINT_DEVNET = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

# ---------------------------------------------------------------------------
# Internal helpers  (ported from x402-buyer-starter/python/pr402_defaults.py)
# ---------------------------------------------------------------------------


def _facilitator_base_url(
    capabilities_url: Optional[str], fallback_base_url: str
) -> str:
    """Resolve the facilitator base URL from a capabilities URL or fallback."""
    raw = (capabilities_url or fallback_base_url or "").strip().rstrip("/")
    suffix = "/api/v1/facilitator/capabilities"
    if raw.endswith(suffix):
        raw = raw[: -len(suffix)].rstrip("/")
    elif raw.endswith(suffix + "/"):
        raw = raw[: -len(suffix) - 1].rstrip("/")
    return raw


def _is_exact_rail_scheme(scheme: Optional[Any]) -> bool:
    """Check whether a scheme string matches the x402 exact rail."""
    return scheme in ("exact", "v2:solana:exact")


def _canonical_accepted_for_build(accepted: dict) -> dict:
    """Normalise the ``scheme`` field for the facilitator build endpoint."""
    if accepted.get("scheme") == "v2:solana:exact":
        out = dict(accepted)
        out["scheme"] = "exact"
        return out
    return accepted


# ---------------------------------------------------------------------------
# Main wrapper
# ---------------------------------------------------------------------------


class X402RequestsWrapper(BaseModel):
    """Wrapper around ``requests`` that handles x402 Payment Required challenges.

    Initialise with a Solana keypair (as a list of byte-integers) and,
    optionally, a facilitator URL and RPC URL.  The wrapper intercepts
    HTTP 402 responses, negotiates payment via the pr402 facilitator,
    signs the Solana transaction locally, and retries the original request
    with the ``PAYMENT-SIGNATURE`` header attached.

    Example::

        wrapper = X402RequestsWrapper(
            keypair_bytes=[1, 2, 3, ...],  # 64-byte Solana keypair
            rpc_url="https://api.devnet.solana.com",
        )
        data = wrapper.get("https://preview.spl-token.signer-payer.me/...")
    """

    keypair_bytes: list[int] = Field(
        description="64-byte Solana keypair as a list of integers.",
        repr=False,
        exclude=True,
    )
    default_facilitator_url: str = Field(
        default=PR402_FACILITATOR_URL_PREVIEW,
        description="Default facilitator base URL.",
    )
    rpc_url: str = Field(
        default="https://api.devnet.solana.com",
        description="Solana JSON-RPC URL for balance queries.",
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Extra headers to include on every request.",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Cached keypair (not serialised)
    _cached_keypair: Optional[Keypair] = PrivateAttr(default=None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_keypair(self) -> Keypair:
        """Return the Solana keypair, caching after first construction."""
        if self._cached_keypair is None:
            self._cached_keypair = Keypair.from_bytes(bytes(self.keypair_bytes))
        return self._cached_keypair

    def __repr__(self) -> str:
        """Mask private key material in debug output."""
        pubkey = str(self._get_keypair().pubkey())
        return (
            f"X402RequestsWrapper(pubkey={pubkey}, "
            f"facilitator={self.default_facilitator_url!r})"
        )

    # ------------------------------------------------------------------
    # Balance checking
    # ------------------------------------------------------------------

    def check_balance(self) -> str:
        """Check the agent's SOL and USDC balance using the configured RPC URL.

        Returns a human-readable string containing the wallet address,
        SOL balance, and USDC balance.
        """
        pubkey = str(self._get_keypair().pubkey())

        # 1. Fetch SOL balance
        sol_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [pubkey],
        }
        try:
            sol_resp = requests.post(
                self.rpc_url, json=sol_payload, timeout=5.0
            ).json()
            lamports = sol_resp.get("result", {}).get("value", 0)
            sol_balance = lamports / 1e9
        except Exception as e:
            sol_balance = f"Error: {e}"

        # 2. Fetch USDC balance (checks both mainnet and devnet mints)
        usdc_mints = [USDC_MINT_MAINNET, USDC_MINT_DEVNET]
        usdc_balance = 0.0
        for mint in usdc_mints:
            usdc_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    pubkey,
                    {"mint": mint},
                    {"encoding": "jsonParsed"},
                ],
            }
            try:
                resp = requests.post(
                    self.rpc_url, json=usdc_payload, timeout=5.0
                ).json()
                accounts = resp.get("result", {}).get("value", [])
                for acc in accounts:
                    amount = (
                        acc.get("account", {})
                        .get("data", {})
                        .get("parsed", {})
                        .get("info", {})
                        .get("tokenAmount", {})
                        .get("uiAmount", 0.0)
                    )
                    usdc_balance += float(amount)
            except Exception:
                pass

        return (
            f"Agent Wallet Address: {pubkey}\n"
            f"SOL Balance: {sol_balance} SOL\n"
            f"USDC Balance: {usdc_balance} USDC"
        )

    # ------------------------------------------------------------------
    # 402 challenge handler
    # ------------------------------------------------------------------

    def _handle_402_challenge(
        self,
        response: requests.Response,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Handle an HTTP 402 Payment Required response.

        Parses the ``Payment-Required`` header, builds a settlement
        transaction via the facilitator, signs it locally, and retries
        the original request with a ``PAYMENT-SIGNATURE`` header.
        """
        logger.info("Received 402 Challenge for %s. Settling payment…", url)

        raw_hdr = response.headers.get("Payment-Required")
        if not raw_hdr:
            raise X402PaymentError(
                "Missing 'Payment-Required' header in 402 response."
            )

        requirements = json.loads(base64.b64decode(raw_hdr))

        accepted = next(
            (
                a
                for a in requirements.get("accepts", [])
                if _is_exact_rail_scheme(a.get("scheme"))
            ),
            None,
        )
        if not accepted:
            raise X402PaymentError("No supported exact rail in accepts[].")

        extra = accepted.get("extra") or {}
        cap_url = (
            extra.get("capabilitiesUrl") if isinstance(extra, dict) else None
        )
        facilitator_url = _facilitator_base_url(
            str(cap_url) if cap_url else None,
            self.default_facilitator_url,
        )
        build_accepted = _canonical_accepted_for_build(accepted)
        payer = self._get_keypair()

        build_req = {
            "payer": str(payer.pubkey()),
            "accepted": build_accepted,
            "resource": requirements.get("resource"),
        }

        logger.info("Building transaction via facilitator…")
        build_res = requests.post(
            f"{facilitator_url}/api/v1/facilitator/build-exact-payment-tx",
            json=build_req,
            timeout=10.0,
        )
        if build_res.status_code != 200:
            raise X402FacilitatorError(build_res.status_code, build_res.text)

        build_data = build_res.json()
        tx_bytes = base64.b64decode(build_data["transaction"])
        vtx = VersionedTransaction.from_bytes(tx_bytes)

        required_sigs = vtx.message.header.num_required_signatures
        payer_index = None
        for i, key in enumerate(vtx.message.account_keys[:required_sigs]):
            if str(key) == str(payer.pubkey()):
                payer_index = i
                break
        if payer_index is None:
            raise X402SigningError(
                "Payer pubkey not found among required signer slots."
            )

        message_bytes = to_bytes_versioned(vtx.message)
        payer_sig = payer.sign_message(message_bytes)
        signatures = list(vtx.signatures)
        signatures[payer_index] = payer_sig
        vtx = VersionedTransaction.populate(vtx.message, signatures)

        signed_tx_b64 = base64.b64encode(bytes(vtx)).decode("utf-8")
        verify_body = build_data["verifyBodyTemplate"]
        verify_body["paymentPayload"]["payload"]["transaction"] = signed_tx_b64
        final_proof = json.dumps(verify_body)

        logger.info("Resubmitting request with payment signature…")
        headers = kwargs.get("headers", {})
        headers["PAYMENT-SIGNATURE"] = final_proof
        kwargs["headers"] = headers

        return requests.request(method, url, **kwargs)

    # ------------------------------------------------------------------
    # Public HTTP methods
    # ------------------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> str:
        """Perform a GET request, handling 402 challenges transparently."""
        headers = kwargs.get("headers", {})
        if self.headers:
            headers.update(self.headers)
        kwargs["headers"] = headers

        response = requests.get(url, **kwargs)
        if response.status_code == 402:
            response = self._handle_402_challenge(
                response, "GET", url, **kwargs
            )

        response.raise_for_status()
        return response.text

    def post(self, url: str, data: Dict[str, Any], **kwargs: Any) -> str:
        """Perform a POST request, handling 402 challenges transparently."""
        headers = kwargs.get("headers", {})
        if self.headers:
            headers.update(self.headers)
        kwargs["headers"] = headers

        response = requests.post(url, json=data, **kwargs)
        if response.status_code == 402:
            kwargs["json"] = data
            response = self._handle_402_challenge(
                response, "POST", url, **kwargs
            )

        response.raise_for_status()
        return response.text
