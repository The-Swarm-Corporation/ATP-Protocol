from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from swarms.schemas.mcp_schemas import MCPConnection, MultipleMCPConnections


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


