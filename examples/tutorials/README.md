# Framework Integration Tutorials

This directory contains step-by-step tutorials for integrating ATP Protocol with various AI agent frameworks.

Each tutorial includes:
- **Server** (`server.py`) - FastAPI server with ATP middleware configured
- **Client** (`client.py`) - Example client demonstrating how to call the API
- **README.md** - Framework-specific documentation and setup instructions

## Available Tutorials

| Framework | Directory | Description |
|-----------|-----------|------------|
| **Swarms** | [`swarms/`](./swarms/) | Enterprise-grade multi-agent orchestration framework |
| **LangChain** | [`langchain/`](./langchain/) | Popular Python framework for building LLM applications |
| **AutoGen** | [`autogen/`](./autogen/) | Microsoft's multi-agent conversation framework |
| **CrewAI** | [`crewai/`](./crewai/) | Multi-agent orchestration framework |
| **Anthropic API** | [`anthropic/`](./anthropic/) | Direct integration with Claude API |

## Quick Start

1. **Choose a framework** from the list above
2. **Navigate to the tutorial directory:**
   ```bash
   cd examples/tutorials/[framework-name]
   ```
3. **Follow the README.md** in that directory for setup instructions
4. **Run the server:**
   ```bash
   python server.py
   ```
5. **Test with the client:**
   ```bash
   python client.py
   ```

## Common Setup Steps

All tutorials follow a similar setup process:

1. **Install dependencies** (framework-specific)
2. **Set environment variables** (API keys, wallet keys)
3. **Update recipient_pubkey** in `server.py`
4. **Run the server**
5. **Test with the client**

See each tutorial's README for specific instructions.
