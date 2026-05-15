"""LangChain tools for making HTTP requests to x402-monetised services.

Provides three tools that any LangChain agent can use:

* ``X402GetTool``     — GET requests with automatic 402 payment handling
* ``X402PostTool``    — POST requests with automatic 402 payment handling
* ``X402BalanceTool`` — check the agent's Solana wallet address & balances
"""

from typing import Any, Dict, Optional, Type

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from langchain_pr402.wrapper import X402RequestsWrapper


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class _X402GetInput(BaseModel):
    """Input schema for X402GetTool."""

    url: str = Field(description="The URL to make a GET request to.")


class _X402PostInput(BaseModel):
    """Input schema for X402PostTool."""

    url: str = Field(description="The URL to make a POST request to.")
    data: Dict[str, Any] = Field(
        description="The JSON data to send in the request body."
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class X402GetTool(BaseTool):
    """Make a GET request to an API that may require x402 payment.

    If the target endpoint returns HTTP 402 Payment Required, the tool
    automatically negotiates payment via the x402 protocol, signs a
    Solana transaction, and retries the request — all transparently.
    """

    name: str = "x402_requests_get"
    description: str = (
        "Use this to perform a GET request to an API that may require "
        "x402 payment. Input should be the full URL."
    )
    args_schema: Type[BaseModel] = _X402GetInput
    requests_wrapper: X402RequestsWrapper

    def _run(
        self,
        url: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Execute the GET request."""
        try:
            return self.requests_wrapper.get(url)
        except Exception as e:
            return f"Error: {e}"


class X402PostTool(BaseTool):
    """Make a POST request to an API that may require x402 payment.

    If the target endpoint returns HTTP 402 Payment Required, the tool
    automatically negotiates payment via the x402 protocol, signs a
    Solana transaction, and retries the request — all transparently.
    """

    name: str = "x402_requests_post"
    description: str = (
        "Use this to perform a POST request to an API that may require "
        "x402 payment. Input should be the URL and a JSON data dictionary."
    )
    args_schema: Type[BaseModel] = _X402PostInput
    requests_wrapper: X402RequestsWrapper

    def _run(
        self,
        url: str,
        data: Dict[str, Any],
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Execute the POST request."""
        try:
            return self.requests_wrapper.post(url, data=data)
        except Exception as e:
            return f"Error: {e}"


class X402BalanceTool(BaseTool):
    """Check the agent's Solana wallet address and SOL/USDC balances.

    Returns the wallet's public address, SOL balance, and USDC balance.
    Useful for the agent to proactively report when funds are low or
    to tell the user which address to top up.
    """

    name: str = "x402_wallet_balance"
    description: str = (
        "Use this tool to get the agent's Solana wallet address and "
        "current SOL/USDC balance. No input required."
    )
    requests_wrapper: X402RequestsWrapper

    def _run(
        self,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Execute the balance check."""
        try:
            return self.requests_wrapper.check_balance()
        except Exception as e:
            return f"Error: {e}"
