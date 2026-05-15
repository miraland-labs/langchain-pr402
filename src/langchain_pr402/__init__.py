"""langchain-pr402 — LangChain tools for autonomous AI agent payments on Solana.

Give any LangChain agent a Solana wallet so it can autonomously pay for
HTTP services that use the x402 protocol (HTTP 402 Payment Required).

Quick start::

    from langchain_pr402 import X402RequestsWrapper, X402GetTool, X402BalanceTool

    wrapper = X402RequestsWrapper(keypair_bytes=[...])
    tools = [X402GetTool(requests_wrapper=wrapper),
             X402BalanceTool(requests_wrapper=wrapper)]
    # … pass tools to your LangChain agent
"""

from langchain_pr402.exceptions import (
    X402FacilitatorError,
    X402PaymentError,
    X402SigningError,
)
from langchain_pr402.tools import X402BalanceTool, X402GetTool, X402PostTool
from langchain_pr402.wrapper import X402RequestsWrapper

__all__ = [
    # Wrapper
    "X402RequestsWrapper",
    # Tools
    "X402GetTool",
    "X402PostTool",
    "X402BalanceTool",
    # Exceptions
    "X402PaymentError",
    "X402FacilitatorError",
    "X402SigningError",
]

__version__ = "0.1.0"
