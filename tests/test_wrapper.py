"""Unit tests for langchain_pr402.wrapper.X402RequestsWrapper."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest
from solders.keypair import Keypair

from langchain_pr402.exceptions import X402FacilitatorError, X402PaymentError
from langchain_pr402.wrapper import X402RequestsWrapper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def keypair_bytes():
    """Generate a fresh random keypair for each test."""
    return list(Keypair().to_bytes())


@pytest.fixture
def wrapper(keypair_bytes):
    """Create a wrapper instance with a random keypair."""
    return X402RequestsWrapper(keypair_bytes=keypair_bytes)


# ---------------------------------------------------------------------------
# Happy path: no payment required
# ---------------------------------------------------------------------------


def test_get_no_payment(wrapper):
    """A 200 response should be returned directly without payment logic."""
    with patch("langchain_pr402.wrapper.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "success"
        mock_get.return_value = mock_resp

        result = wrapper.get("http://example.com")

        assert result == "success"
        mock_get.assert_called_once_with("http://example.com", headers={})


def test_post_no_payment(wrapper):
    """A 200 POST response should be returned directly."""
    with patch("langchain_pr402.wrapper.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"ok": true}'
        mock_post.return_value = mock_resp

        result = wrapper.post("http://example.com/api", data={"key": "val"})

        assert result == '{"ok": true}'


# ---------------------------------------------------------------------------
# 402 challenge flow
# ---------------------------------------------------------------------------


def _build_402_response(wrapper_instance):
    """Helper: build a mocked 402 response with valid payment requirements."""
    challenge_payload = {
        "resource": "test_resource",
        "accepts": [
            {
                "scheme": "v2:solana:exact",
                "extra": {
                    "capabilitiesUrl": (
                        "http://mock-facilitator.com"
                        "/api/v1/facilitator/capabilities"
                    )
                },
            }
        ],
    }
    encoded = base64.b64encode(
        json.dumps(challenge_payload).encode()
    ).decode()

    mock_resp = MagicMock()
    mock_resp.status_code = 402
    mock_resp.headers = {"Payment-Required": encoded}
    return mock_resp


def test_handle_402_challenge(wrapper):
    """Full 402 flow: challenge → build tx → sign → retry with proof."""
    mock_402 = _build_402_response(wrapper)
    mock_200 = MagicMock(status_code=200, text="paid_success")

    with (
        patch("langchain_pr402.wrapper.requests.get") as mock_get,
        patch("langchain_pr402.wrapper.requests.post") as mock_post,
        patch("langchain_pr402.wrapper.requests.request") as mock_request,
        patch("langchain_pr402.wrapper.VersionedTransaction") as mock_vtx,
        patch("langchain_pr402.wrapper.to_bytes_versioned") as mock_to_bytes,
    ):
        mock_get.return_value = mock_402
        mock_request.return_value = mock_200
        mock_to_bytes.return_value = b"mock_message_bytes"

        # Mock transaction object
        mock_tx = MagicMock()
        mock_vtx.from_bytes.return_value = mock_tx
        mock_tx.message.header.num_required_signatures = 1
        mock_tx.message.account_keys = [wrapper._get_keypair().pubkey()]
        mock_tx.signatures = [b""]
        mock_vtx.populate.return_value = b"signed_tx_mock_bytes"

        # Mock facilitator build response
        mock_build_resp = MagicMock()
        mock_build_resp.status_code = 200
        mock_build_resp.json.return_value = {
            "transaction": base64.b64encode(b"mock_tx_bytes").decode(),
            "verifyBodyTemplate": {
                "paymentPayload": {"payload": {}}
            },
        }
        mock_post.return_value = mock_build_resp

        # Execute
        result = wrapper.get("http://example.com/paid-endpoint")

        # Assertions
        assert result == "paid_success"
        mock_post.assert_called_once()
        assert "build-exact-payment-tx" in mock_post.call_args[0][0]
        mock_request.assert_called_once()

        # Verify PAYMENT-SIGNATURE header was attached
        _, request_kwargs = mock_request.call_args
        assert "PAYMENT-SIGNATURE" in request_kwargs["headers"]


def test_402_missing_header_raises(wrapper):
    """A 402 without Payment-Required header should raise X402PaymentError."""
    mock_resp = MagicMock(status_code=402, headers={})

    with patch("langchain_pr402.wrapper.requests.get") as mock_get:
        mock_get.return_value = mock_resp

        with pytest.raises(X402PaymentError, match="Missing"):
            wrapper.get("http://example.com")


def test_402_no_exact_rail_raises(wrapper):
    """A 402 with no supported exact rail should raise X402PaymentError."""
    challenge = {
        "resource": "test",
        "accepts": [{"scheme": "unsupported_scheme"}],
    }
    encoded = base64.b64encode(json.dumps(challenge).encode()).decode()
    mock_resp = MagicMock(
        status_code=402,
        headers={"Payment-Required": encoded},
    )

    with patch("langchain_pr402.wrapper.requests.get") as mock_get:
        mock_get.return_value = mock_resp

        with pytest.raises(X402PaymentError, match="No supported exact rail"):
            wrapper.get("http://example.com")


# ---------------------------------------------------------------------------
# Balance checking
# ---------------------------------------------------------------------------


def test_check_balance(wrapper):
    """check_balance should return SOL and USDC balances."""
    sol_response = {"result": {"value": 500_000_000}}  # 0.5 SOL
    usdc_response = {
        "result": {
            "value": [
                {
                    "account": {
                        "data": {
                            "parsed": {
                                "info": {
                                    "tokenAmount": {"uiAmount": 10.5}
                                }
                            }
                        }
                    }
                }
            ]
        }
    }

    with patch("langchain_pr402.wrapper.requests.post") as mock_post:
        mock_sol = MagicMock()
        mock_sol.json.return_value = sol_response
        mock_usdc = MagicMock()
        mock_usdc.json.return_value = usdc_response
        mock_empty = MagicMock()
        mock_empty.json.return_value = {"result": {"value": []}}

        mock_post.side_effect = [mock_sol, mock_usdc, mock_empty]

        result = wrapper.check_balance()

        assert "0.5 SOL" in result
        assert "10.5 USDC" in result
        assert "Agent Wallet Address:" in result


def test_check_balance_empty_wallet(wrapper):
    """An empty wallet should report 0.0 for both SOL and USDC."""
    sol_response = {"result": {"value": 0}}
    empty_response = {"result": {"value": []}}

    with patch("langchain_pr402.wrapper.requests.post") as mock_post:
        mock_sol = MagicMock()
        mock_sol.json.return_value = sol_response
        mock_empty = MagicMock()
        mock_empty.json.return_value = empty_response

        mock_post.side_effect = [mock_sol, mock_empty, mock_empty]

        result = wrapper.check_balance()

        assert "0.0 SOL" in result
        assert "0.0 USDC" in result


# ---------------------------------------------------------------------------
# Keypair caching
# ---------------------------------------------------------------------------


def test_keypair_is_cached(wrapper):
    """_get_keypair should return the same object on repeated calls."""
    kp1 = wrapper._get_keypair()
    kp2 = wrapper._get_keypair()
    assert kp1 is kp2


# ---------------------------------------------------------------------------
# Repr masking
# ---------------------------------------------------------------------------


def test_repr_masks_private_key(wrapper):
    """repr should show the pubkey but never the private key bytes."""
    r = repr(wrapper)
    assert "pubkey=" in r
    assert "keypair_bytes" not in r
