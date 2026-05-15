"""
Demo: LangChain Agent with x402 Payment Tools

This script demonstrates how a LangChain agent can autonomously:
1. Check its own wallet balance (SOL + USDC)
2. Make GET/POST requests to paid APIs behind x402 paywalls
3. Report back when funds are low

Setup:
  pip install langchain-pr402 langchain-openai

  export SOLANA_PRIVATE_KEY='[1,2,3,...,64]'   # JSON array of 64-byte keypair
  export SOLANA_RPC_URL='https://api.devnet.solana.com'
  export OPENAI_API_KEY='sk-...'
"""

import json
import os

from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from langchain_pr402 import X402BalanceTool, X402GetTool, X402PostTool, X402RequestsWrapper

load_dotenv()


def load_keypair_bytes() -> list[int]:
    """Load keypair bytes from environment variable or fallback to a local file."""
    raw = os.getenv("SOLANA_PRIVATE_KEY")
    if raw:
        return json.loads(raw)

    # Fallback: local keypair file (for local testing only, never commit this)
    fallback_path = os.getenv(
        "SOLANA_KEYPAIR_PATH", "../../demo-wallets/buyer-keypair.json"
    )
    if os.path.exists(fallback_path):
        with open(fallback_path, "r") as f:
            return json.load(f)

    raise RuntimeError(
        "No Solana keypair found. Set SOLANA_PRIVATE_KEY env var "
        "(JSON array of bytes) or SOLANA_KEYPAIR_PATH to a keypair file."
    )


def main():
    keypair_bytes = load_keypair_bytes()
    rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")

    wrapper = X402RequestsWrapper(
        keypair_bytes=keypair_bytes,
        rpc_url=rpc_url,
    )

    tools = [
        X402GetTool(requests_wrapper=wrapper),
        X402PostTool(requests_wrapper=wrapper),
        X402BalanceTool(requests_wrapper=wrapper),
    ]

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a helpful assistant with a Solana wallet. "
            "You can check your wallet balance and make paid API requests "
            "using the x402 protocol. If a request fails due to insufficient "
            "funds, check your balance and tell the user your wallet address "
            "so they can top it up.",
        ),
        ("user", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    # --- Demo 1: Check wallet balance ---
    print("\033[36m>>> DEMO 1: CHECK AGENT WALLET BALANCE <<<\033[0m")
    try:
        response = agent_executor.invoke(
            {"input": "What is my wallet address and current balance?"}
        )
        print(f"\033[32m[RESULT]\033[0m {response['output']}\n")
    except Exception as e:
        print(f"Demo 1 Failed: {e}\n")

    # --- Demo 2: Paid API request ---
    print("\033[36m>>> DEMO 2: PAID API REQUEST (SPL BALANCE) <<<\033[0m")
    try:
        response = agent_executor.invoke({
            "input": (
                "Please check the USDC balance for wallet "
                "'buyA5hR1Z9KtHQRBTmLkjsFfjAabDwdZtrRC6edqxAJ' "
                "using this GET endpoint: "
                "https://preview.spl-token.signer-payer.me/api/v1/check-balance"
                "?wallet=buyA5hR1Z9KtHQRBTmLkjsFfjAabDwdZtrRC6edqxAJ"
                "&spl-token=4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
            )
        })
        print(f"\033[32m[RESULT]\033[0m {response['output']}\n")
    except Exception as e:
        print(f"Demo 2 Failed: {e}\n")


if __name__ == "__main__":
    main()
