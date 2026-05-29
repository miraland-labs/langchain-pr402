# langchain-pr402

LangChain tools for autonomous AI agent payments on Solana via the [pr402/x402 protocol](https://github.com/miraland-labs/x402).

Give any LangChain agent a Solana wallet so it can autonomously pay for HTTP services that return `402 Payment Required`.

## Installation

```bash
pip install langchain-pr402
```

## Quick Start

```python
from langchain_pr402 import X402RequestsWrapper, X402GetTool, X402BalanceTool

# 1. Create a wrapper with your agent's Solana keypair (defaults to Devnet)
wrapper = X402RequestsWrapper(
    keypair_bytes=[1, 2, 3, ...],  # 64-byte Solana keypair as list of ints
    # rpc_url defaults to "https://api.devnet.solana.com"
    # default_facilitator_url defaults to "https://preview.ipay.sh" (Devnet)
)

# 2. Create tools and give them to your agent
tools = [
    X402GetTool(requests_wrapper=wrapper),
    X402BalanceTool(requests_wrapper=wrapper),
]

# 3. Use with any LangChain agent (GPT-4, Claude, Llama, etc.)
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor

llm = ChatOpenAI(model="gpt-4o-mini")
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools)
executor.invoke({"input": "Check my wallet balance"})
```

## How It Works

1. Your agent calls `X402GetTool` to fetch a URL.
2. If the server responds with `HTTP 402 Payment Required`, the tool automatically:
   - Parses the payment terms from the `Payment-Required` header
   - Builds a Solana transaction via the [pr402 facilitator](https://preview.ipay.sh) (Devnet by default)
   - Signs the transaction locally with the agent's keypair
   - Retries the request with a `PAYMENT-SIGNATURE` header
3. The agent receives the paid content — the LLM never sees the payment complexity.

## Tools

| Tool | Description |
|---|---|
| `X402GetTool` | GET requests with automatic 402 payment handling |
| `X402PostTool` | POST requests with automatic 402 payment handling |
| `X402BalanceTool` | Check the agent's wallet address and SOL/USDC balance |

## Setting Up the Agent Wallet

AI agents don't create their own wallets. The developer provisions one:

1. **Create a wallet**: `solana-keygen new -o agent-keypair.json`
2. **Fund it**: Send USDC and a small amount of SOL for transaction fees
3. **Configure**: Pass the keypair bytes to `X402RequestsWrapper`

```bash
# Via environment variable (recommended for production)
export SOLANA_PRIVATE_KEY='[1,2,3,...,64]'
```

```python
import os, json
wrapper = X402RequestsWrapper(
    keypair_bytes=json.loads(os.environ["SOLANA_PRIVATE_KEY"])
)
```

## Networks

By default, the wrapper is configured for **Solana Devnet** (great for testing).
To switch to **Mainnet**, override both URLs:

```python
wrapper = X402RequestsWrapper(
    keypair_bytes=json.loads(os.environ["SOLANA_PRIVATE_KEY"]),
    rpc_url="https://api.mainnet-beta.solana.com",
    default_facilitator_url="https://ipay.sh",  # Mainnet facilitator
)
```

| Network | RPC URL | Facilitator URL |
|---|---|---|
| Devnet (default) | `https://api.devnet.solana.com` | `https://preview.ipay.sh` |
| Mainnet | `https://api.mainnet-beta.solana.com` | `https://ipay.sh` |

## Security

- Private key material is **never serialised** — `keypair_bytes` is excluded from `model_dump()`, `repr()`, and logging.
- The wrapper signs transactions **locally**. Private keys never leave the machine.
- The pr402 facilitator only receives the public key and returns an unsigned transaction.

## Links

- [pr402/x402 Protocol](https://github.com/miraland-labs/x402)
- [pr402 Facilitator](https://ipay.sh)
- [Documentation](https://docs.ipay.sh)
- **MCP hosts (Cursor, Claude Desktop):** [`@pr402/mcp-server`](https://www.npmjs.com/package/@pr402/mcp-server) — see [pr402 agent-tools.json](https://preview.ipay.sh/agent-tools.json)
