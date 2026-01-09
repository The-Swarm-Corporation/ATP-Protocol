from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from swarms.schemas.mcp_schemas import (
    MCPConnection,
    MultipleMCPConnections,
)


class AgentSpec(BaseModel):
    agent_name: Optional[str] = Field(
        # default=None,
        description="The unique name assigned to the agent, which identifies its role and functionality within the swarm.",
    )
    description: Optional[str] = Field(
        default=None,
        description="A detailed explanation of the agent's purpose, capabilities, and any specific tasks it is designed to perform.",
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="The initial instruction or context provided to the agent, guiding its behavior and responses during execution.",
    )
    model_name: Optional[str] = Field(
        default="gpt-4.1",
        description="The name of the AI model that the agent will utilize for processing tasks and generating outputs. For example: gpt-4o, gpt-4o-mini, openai/o3-mini",
    )
    auto_generate_prompt: Optional[bool] = Field(
        default=False,
        description="A flag indicating whether the agent should automatically create prompts based on the task requirements.",
    )
    max_tokens: Optional[int] = Field(
        default=8192,
        description="The maximum number of tokens that the agent is allowed to generate in its responses, limiting output length.",
    )
    temperature: Optional[float] = Field(
        default=0.5,
        description="A parameter that controls the randomness of the agent's output; lower values result in more deterministic responses.",
    )
    role: Optional[str] = Field(
        default="worker",
        description="The designated role of the agent within the swarm, which influences its behavior and interaction with other agents.",
    )
    max_loops: Optional[int] = Field(
        default=1,
        description="The maximum number of times the agent is allowed to repeat its task, enabling iterative processing if necessary.",
    )
    tools_list_dictionary: Optional[List[Dict[Any, Any]]] = Field(
        default=None,
        description="A dictionary of tools that the agent can use to complete its task.",
    )
    mcp_url: Optional[str] = Field(
        default=None,
        description="The URL of the MCP server that the agent can use to complete its task.",
    )
    streaming_on: Optional[bool] = Field(
        default=False,
        description="A flag indicating whether the agent should stream its output.",
    )
    llm_args: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional arguments to pass to the LLM such as top_p, frequency_penalty, presence_penalty, etc.",
    )
    dynamic_temperature_enabled: Optional[bool] = Field(
        default=True,
        description="A flag indicating whether the agent should dynamically adjust its temperature based on the task.",
    )

    mcp_config: Optional[MCPConnection] = Field(
        default=None,
        description="The MCP connection to use for the agent.",
    )

    mcp_configs: Optional[MultipleMCPConnections] = Field(
        default=None,
        description="The MCP connections to use for the agent. This is a list of MCP connections. Includes multiple MCP connections.",
    )

    tool_call_summary: Optional[bool] = Field(
        default=True,
        description="A parameter enabling an agent to summarize tool calls.",
    )

    reasoning_effort: Optional[str] = Field(
        default=None,
        description="The effort to put into reasoning.",
    )

    thinking_tokens: Optional[int] = Field(
        default=None,
        description="The number of tokens to use for thinking.",
    )

    reasoning_enabled: Optional[bool] = Field(
        default=False,
        description="A parameter enabling an agent to use reasoning.",
    )

    class Config:
        arbitrary_types_allowed = True


class PaymentToken(str, Enum):
    """Supported payment tokens on Solana."""

    SOL = "SOL"
    USDC = "USDC"


class ATPSettlementMiddlewareConfig(BaseModel):
    """Configuration schema for ATP Settlement Middleware.
    
    This schema defines all configuration parameters for the ATPSettlementMiddleware.
    All parameters match the middleware's __init__ signature, making it easy to
    configure the middleware from a validated configuration object.
    """

    allowed_endpoints: List[str] = Field(
        ...,
        description=(
            "List of endpoint paths to apply settlement to (e.g., ['/v1/chat']). "
            "Supports path patterns - exact matches only."
        ),
    )
    input_cost_per_million_usd: float = Field(
        ...,
        description="Cost per million input tokens in USD.",
        gt=0.0,
    )
    output_cost_per_million_usd: float = Field(
        ...,
        description="Cost per million output tokens in USD.",
        gt=0.0,
    )
    wallet_private_key_header: str = Field(
        default="x-wallet-private-key",
        description=(
            "HTTP header name containing the wallet private key. "
            "The private key should be in JSON array format (e.g., '[1,2,3,...]') "
            "or base58 string format."
        ),
    )
    payment_token: PaymentToken = Field(
        default=PaymentToken.SOL,
        description="Token to use for payment (SOL or USDC).",
    )
    recipient_pubkey: Optional[str] = Field(
        default=None,
        description=(
            "Solana public key of the recipient wallet (the endpoint host). "
            "This wallet receives the main payment (after processing fee). "
            "Required when initializing the middleware."
        ),
    )
    skip_preflight: bool = Field(
        default=False,
        description="Whether to skip preflight simulation for Solana transactions.",
    )
    commitment: str = Field(
        default="confirmed",
        description="Solana commitment level (processed|confirmed|finalized).",
    )
    require_wallet: bool = Field(
        default=True,
        description=(
            "Whether to require wallet private key. "
            "If False, skips settlement when missing."
        ),
    )
    settlement_service_url: Optional[str] = Field(
        default=None,
        description=(
            "Base URL of the settlement service. If not provided, uses "
            "ATP_SETTLEMENT_URL environment variable (default: http://localhost:8001). "
            "The middleware always uses the settlement service for all settlement operations."
        ),
    )
    fail_on_settlement_error: bool = Field(
        default=False,
        description=(
            "If True, raises HTTPException when settlement fails (default: False). "
            "If False, returns the response with settlement error info instead of failing the request."
        ),
    )
    settlement_timeout: Optional[float] = Field(
        default=None,
        description=(
            "Timeout in seconds for settlement service requests. "
            "Default: from ATP_SETTLEMENT_TIMEOUT env var or 300.0 (5 minutes). "
            "Settlement operations may take longer due to blockchain confirmation times. "
            "Increase this value if you experience timeout errors even when payments are successfully sent."
        ),
        gt=0.0,
    )

    class Config:
        """Pydantic configuration."""

        use_enum_values = True


class AgentTask(BaseModel):
    """Complete agent task request requiring full agent specification."""

    agent_config: AgentSpec = Field(
        ...,
        description="Complete agent configuration specification matching the Swarms API AgentSpec schema",
    )
    task: str = Field(
        ...,
        description="The task or query to execute",
        example="Analyze the latest SOL/USDC liquidity pool data and provide trading recommendations.",
    )
    user_wallet: str = Field(
        ...,
        description="The Solana public key of the sender for payment verification",
    )
    payment_token: PaymentToken = Field(
        default=PaymentToken.SOL,
        description="Payment token to use for settlement (SOL or USDC)",
    )
    history: Optional[Union[Dict[Any, Any], List[Dict[str, str]]]] = (
        Field(
            default=None,
            description="Optional conversation history for context",
        )
    )
    img: Optional[str] = Field(
        default=None,
        description="Optional image URL for vision tasks",
    )
    imgs: Optional[List[str]] = Field(
        default=None,
        description="Optional list of image URLs for vision tasks",
    )


class SettleTrade(BaseModel):
    """Settlement request that asks the facilitator to sign+send the payment tx.

    WARNING: This is custodial-like behavior. The private key is used in-memory only
    for the duration of this request and is not persisted.
    """

    job_id: str = Field(
        ..., description="Job ID from the trade creation response"
    )
    private_key: str = Field(
        ...,
        description=(
            "Payer private key encoded as a string. Supported formats:\n"
            "- Base58 keypair (common Solana secret key string)\n"
            "- JSON array of ints (e.g. '[12,34,...]')"
        ),
    )
    skip_preflight: bool = Field(
        default=False,
        description="Whether to skip preflight simulation",
    )
    commitment: str = Field(
        default="confirmed",
        description="Confirmation level to wait for (processed|confirmed|finalized)",
    )



class MarketplaceDiscovery(BaseModel):
    name: str = Field(
        ...,
        description="The name of the marketplace",
    )
    id: str = Field(
        ...,
        description="The id of the marketplace. Generated automatically by the server.",
    )
    url: str = Field(
        ...,
        description="The URL of the endpoint",
    )
    description: str = Field(
        ...,
        description="The description of the marketplace",
    )
    input_schema: Optional[Union[Dict[Any, Any], List[Dict[str, Any]]]] = Field(
        default=None,
        description="The input schema of the endpoint",
    )
    output_schema: Optional[Union[Dict[Any, Any], List[Dict[str, Any]]]] = Field(
        default=None,
        description="The output schema of the endpoint",
    )
    input_cost_per_million_usd: float = Field(
        ...,
        description="The cost per million tokens (USD) for input to this endpoint.",
    )
    output_cost_per_million_usd: float = Field(
        ...,
        description="The cost per million tokens (USD) for output from this endpoint.",
    )
    payment_token: PaymentToken = Field(
        default=PaymentToken.SOL,
        description="Payment token to use for settlement (e.g. SOL, USDC)."
    )
    recipient_pubkey: Optional[str] = Field(
        default=None,
        description="Solana recipient public key for settlement."
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="The tags of the marketplace.",
    )
    business_model: Optional[str] = Field(
        default="usage",
        description="The business model of the marketplace. Usage-based pricing is the default. one-time pricing is also supported.",
    )
    




class MarketplaceDiscoveryResponse(BaseModel):
    # Fetch the resources
    resources: List[MarketplaceDiscovery] = Field(
        ...,
        description="The resources of the marketplace",
    )
    limit: Optional[int] = Field(
        default=20,
        description="Number of resources to return (default: 20)",
    )
    offset: Optional[int] = Field(
        default=0,
        description="Offset for pagination (default: 0)",
    )
    timestamp: float = Field(
        ...,
        description="The timestamp of the response. Generated automatically by the server.",
    )
    
    
    
class MarketplaceIndividualDiscoveryQueryRequest(BaseModel):
    id: str = Field(
        ...,
        description="The id of the marketplace to query.",
    )
    name: Optional[str] = Field(
        default=None,
        description="The name of the marketplace to query.",
    )
    url: Optional[str] = Field(
        default=None,
        description="The URL of the endpoint to query.",
    )
    
    
    
