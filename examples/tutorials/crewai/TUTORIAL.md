## Quick Tutorial: CrewAI + ATP Protocol

This is a minimal step-by-step guide to **start the server** and then **call it with the client**.

For full details, see the existing `README.md` in this folder.

### 1. Install dependencies

From the project root (or this folder), install the required packages:

```bash
pip install crewai atp-protocol fastapi uvicorn httpx python-dotenv
```

Or:

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

Create a `.env` file in this `crewai/` folder:

```bash
OPENAI_API_KEY="your-openai-api-key"
ATP_PRIVATE_KEY="[1,2,3,...]"  # JSON array format or base58 string
ATP_SETTLEMENT_URL="https://facilitator.swarms.world"  # optional
```

### 3. Configure the payment recipient

Open `server.py` in this folder and set your Solana wallet address:

```python
recipient_pubkey="YourSolanaWalletHere"
```

This is the wallet that will **receive payments**.

### 4. Run the CrewAI + ATP server

From this `crewai/` folder:

```bash
python server.py
```

You should see a FastAPI server listening on `http://localhost:8000`.

### 5. Call the server using the client

In a **separate terminal**, still in this `crewai/` folder:

```bash
python client.py
```

The client will:

- Read your `ATP_PRIVATE_KEY` from `.env`
- Send a request to the local server with the wallet key in `x-wallet-private-key`
- Trigger a CrewAI crew run behind the scenes
- Automatically settle payment on Solana via ATP

### 6. Inspect the response

The client should print a JSON response including:

- The model output from the CrewAI crew
- A `usage` section with token counts
- An `atp_settlement` section containing:
  - `status` (e.g. `"paid"`)
  - `transaction_signature`
  - Payment amounts sent to your wallet and the treasury

If you can see all three, your **CrewAI + ATP** tutorial is working end-to-end.

