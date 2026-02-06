## Swarms + ATP Protocol: Comprehensive Tutorial

This tutorial walks through the **full Swarms + ATP Protocol example**:

- Setting up the environment and dependencies  
- Understanding the **server** (`server.py`) and ATP middleware integration  
- Understanding the **client** (`client.py`) and how it authenticates with a wallet  
- Seeing how **usage → pricing → on-chain payment** flows end-to-end  

---

### 1. Install dependencies

From the project root (or this `swarms/` folder), install the required packages:

```bash
pip install swarms atp-protocol fastapi uvicorn httpx python-dotenv
```

Or, if you have a `requirements.txt`:

```bash
pip install -r requirements.txt
```

Required components:

- **Swarms**: agent framework (`Agent`, `count_tokens`)  
- **FastAPI** + **uvicorn**: HTTP API server  
- **atp-protocol**: ATP client + middleware for payments  
- **httpx**: HTTP client library used in `client.py`  
- **python-dotenv**: loads `.env` with keys and config  

---

### 2. Environment variables

Create a `.env` file in this `swarms/` directory:

```bash
OPENAI_API_KEY="your-openai-api-key"
ATP_PRIVATE_KEY="[1,2,3,...]"  # JSON array format or base58 string
ATP_SETTLEMENT_URL="https://facilitator.swarms.world"  # optional, default facilitator
```

- **`OPENAI_API_KEY`**: used by Swarms to call the LLM.  
- **`ATP_PRIVATE_KEY`**: Solana wallet private key used by the *client* to sign payments.  
- **`ATP_SETTLEMENT_URL`** (optional): ATP Settlement Service URL; defaults to the main facilitator if not set.

> The **server** never reads `ATP_PRIVATE_KEY`. The client passes a wallet key per request via an HTTP header, and the ATP middleware uses that just-in-time.

---

### 3. Server walkthrough (`server.py`)

The Swarms server does three main things:

1. Creates a FastAPI app  
2. Configures a Swarms `Agent` and ATP middleware  
3. Exposes endpoints that run the agent and attach **usage** data to responses  

#### 3.1. Core setup: FastAPI app, Swarms agent, and middleware

Here is the top of the server:

```1:59:/Users/swarms_wd/Desktop/research/recovery/ATP-Protocol/examples/tutorials/swarms/server.py
"""
Swarms Framework + ATP Protocol Integration Example

This example demonstrates how to integrate ATP Protocol with Swarms agents
to enable automatic payment processing for agent services.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from swarms import Agent, count_tokens

from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

# Create FastAPI app
app = FastAPI(
    title="ATP Protocol + Swarms Integration",
    description="Example API showing ATP payment processing with Swarms agents",
)

# Initialize Swarms Agent
AGENT_MODEL = "gpt-4o-mini"
agent = Agent(
    model_name=AGENT_MODEL,
    max_loops=1,
    interactive=False,
)

# Add ATP Settlement Middleware
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/agent/execute",
        "/v1/agent/chat",
    ],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    recipient_pubkey="YourSolanaWalletHere",
    payment_token=PaymentToken.SOL,
    wallet_private_key_header="x-wallet-private-key",
    require_wallet=True,
)
```

Key points:

- **`AGENT_MODEL`** is set to `"gpt-4o-mini"` and is reused both for agent calls and token counting.  
- **`ATPSettlementMiddleware`** wraps the app and intercepts only the endpoints listed in `allowed_endpoints`.  
- **`recipient_pubkey`** must be changed to **your Solana public key**; this is where 95% of payments go.  
- **`wallet_private_key_header`** tells ATP where to look for the client’s per-request wallet key.  

> The middleware is responsible for:  
> - reading `usage` from your endpoint’s JSON response,  
> - computing price based on input/output token rates,  
> - calling the ATP settlement service,  
> - and then augmenting the JSON with `atp_settlement` (transaction signature, amounts).

#### 3.2. Execute endpoint: `/v1/agent/execute`

This endpoint runs a single-shot Swarms agent task and returns `usage`:

```62:123:/Users/swarms_wd/Desktop/research/recovery/ATP-Protocol/examples/tutorials/swarms/server.py
@app.post("/v1/agent/execute")
async def execute_agent(request: dict):
    """
    Execute a Swarms agent task with automatic payment processing.
    """
    try:
        task = request.get("task", "")
        if not task:
            raise HTTPException(
                status_code=400, detail="Task is required"
            )

        system_prompt = request.get("system_prompt")

        input_tokens = count_tokens(task, model=AGENT_MODEL)
        if system_prompt:
            input_tokens += count_tokens(system_prompt, model=AGENT_MODEL)

        logger.info(f"Executing agent task: {task[:100]}...")
        result = agent.run(task)

        output_tokens = count_tokens(str(result), model=AGENT_MODEL)

        response_data = {
            "output": result,
            "task": task,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Agent execution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Agent execution failed: {str(e)}"
        )
```

Flow:

1. Validate request contains `"task"`.  
2. Compute **`input_tokens`** using `count_tokens` on the task (and optional `system_prompt`).  
3. Run Swarms `agent.run(task)` to get the result.  
4. Compute **`output_tokens`** on the result string.  
5. Return JSON with a `usage` object.  
6. **ATP middleware** sees `usage`, calculates cost, and performs on-chain payment using the wallet key from the request header.

#### 3.3. Chat endpoint: `/v1/agent/chat`

This endpoint simulates a chat-style interaction and also returns `usage`:

```126:189:/Users/swarms_wd/Desktop/research/recovery/ATP-Protocol/examples/tutorials/swarms/server.py
@app.post("/v1/agent/chat")
async def chat_with_agent(request: dict):
    """
    Chat with a Swarms agent (conversational interface).
    """
    try:
        message = request.get("message", "")
        if not message:
            raise HTTPException(
                status_code=400, detail="Message is required"
            )

        history = request.get("conversation_history", [])

        context = ""
        if history:
            context = "\n".join(
                [
                    f"User: {h.get('user', '')}\nAssistant: {h.get('assistant', '')}"
                    for h in history
                ]
            )

        full_task = f"{context}\n\nUser: {message}\nAssistant:" if context else message

        input_tokens = count_tokens(full_task, model=AGENT_MODEL)

        logger.info(f"Chat request: {message[:100]}...")
        response = agent.run(full_task)

        output_tokens = count_tokens(str(response), model=AGENT_MODEL)

        response_data = {
            "message": message,
            "response": response,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }

        return JSONResponse(content=response_data)
```

The key difference from `/v1/agent/execute` is:

- It builds a **conversation context** from `conversation_history` and the new `message`.  
- That full context is what you pay for: all tokens in the combined prompt.  

#### 3.4. Health and root endpoints

These endpoints are **not** wrapped by ATP (no payments) but help you test connectivity:

```192:224:/Users/swarms_wd/Desktop/research/recovery/ATP-Protocol/examples/tutorials/swarms/server.py
@app.get("/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "agent_ready": True,
        "atp_middleware": "active",
        "framework": "swarms",
    }

@app.get("/")
async def root():
    return {
        "name": "ATP Protocol + Swarms Integration",
        "description": "API for Swarms agents with automatic payment processing",
        "endpoints": {
            "/v1/agent/execute": "Execute agent task (requires x-wallet-private-key header)",
            "/v1/agent/chat": "Chat with agent (requires x-wallet-private-key header)",
            "/v1/health": "Health check (no payment required)",
        },
        "payment": {
            "token": "SOL",
            "input_rate": "$10 per million tokens",
            "output_rate": "$30 per million tokens",
            "fee": "5% to Swarms Treasury",
        },
    }
```

---

### 4. Client walkthrough (`client.py`)

The Swarms client does three things:

1. Loads `ATP_PRIVATE_KEY` from `.env`.  
2. Sets the `x-wallet-private-key` header.  
3. Calls the API endpoints and prints the full JSON responses.

```1:78:/Users/swarms_wd/Desktop/research/recovery/ATP-Protocol/examples/tutorials/swarms/client.py
"""
Client example for Swarms + ATP Protocol API
"""

import json
import httpx
import os

from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = "http://localhost:8000"
WALLET_PRIVATE_KEY = os.getenv("ATP_PRIVATE_KEY")

headers = {
    "Content-Type": "application/json",
    "x-wallet-private-key": WALLET_PRIVATE_KEY,
}


def execute_agent_task():
    response = httpx.post(
        f"{API_BASE_URL}/v1/agent/execute",
        headers=headers,
        json={
            "task": "What are the key benefits of using a multi-agent system?",
            "system_prompt": "You are a helpful AI assistant.",
        },
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    print(json.dumps(data, indent=2))
    return data


def chat_with_agent():
    response = httpx.post(
        f"{API_BASE_URL}/v1/agent/chat",
        headers=headers,
        json={
            "message": "Explain the concept of agentic AI in simple terms.",
        },
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    print(json.dumps(data, indent=2))
    return data


def health_check():
    response = httpx.get(f"{API_BASE_URL}/v1/health", timeout=10.0)
    response.raise_for_status()
    data = response.json()
    print(json.dumps(data, indent=2))
    return data
```

The bottom of the file orchestrates the demo:

```81:103:/Users/swarms_wd/Desktop/research/recovery/ATP-Protocol/examples/tutorials/swarms/client.py
if __name__ == "__main__":
    print("Swarms + ATP Protocol Client Example")
    if not WALLET_PRIVATE_KEY:
        print("WARNING: ATP_PRIVATE_KEY not set in environment variables")
        print("Payment-enabled endpoints will fail without this key")

    try:
        health_check()
        execute_agent_task()
        chat_with_agent()
    except httpx.HTTPStatusError as e:
        print(f"\nHTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"\nError: {e}")
```

Important details:

- **`x-wallet-private-key`** header is the *only* place the wallet key is passed to the server.  
- The **ATP middleware** uses this key to sign and send payments for each request.  
- The **server** never stores the key; it is only used within the scope of a single HTTP request.  

---

### 5. Running the end-to-end example

From this `swarms/` folder:

1. **Start the server**:

   ```bash
   python server.py
   ```

2. **Run the client in another terminal**:

   ```bash
   python client.py
   ```

You should see:

- A health check response with `"framework": "swarms"`.  
- Responses from `/v1/agent/execute` and `/v1/agent/chat` that include:  
  - `output` / `response`  
  - `usage` with `input_tokens`, `output_tokens`, `total_tokens`  
  - `atp_settlement` (added by middleware) with:  
    - `status` (e.g. `"paid"`)  
    - `transaction_signature`  
    - Payment amounts for your wallet and the treasury  

---

### 6. How the full flow works (conceptual)

End-to-end lifecycle for a single request:

1. **Client** sends a POST request to `/v1/agent/execute` or `/v1/agent/chat` with:  
   - JSON body containing the task/message  
   - `x-wallet-private-key` header containing your Solana private key  
2. **FastAPI endpoint**:  
   - Validates input  
   - Calls Swarms `agent.run(...)`  
   - Uses `count_tokens` to compute input/output token counts  
   - Returns JSON including a `usage` object  
3. **ATP middleware** intercepts the response:  
   - Reads `usage` and the pricing config (`input_cost_per_million_usd`, `output_cost_per_million_usd`)  
   - Computes total USD price → converts to SOL  
   - Constructs and sends a Solana transaction using the wallet key from `x-wallet-private-key`  
   - Appends `atp_settlement` to the JSON response  
4. **Client** receives the final JSON and prints:  
   - Model output  
   - Token usage  
   - Settlement details with the on-chain transaction signature  

This same pattern is reused in the LangChain, AutoGen, CrewAI, and Anthropic tutorials; only the agent framework changes.

