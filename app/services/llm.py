"""Chat-model factory for the specialist agents.

DEMO_MODE=true returns ScriptedChatModel: a real LangChain chat model that plays
back a fixed list of tool calls, one per turn, then says it is done. The agent loop,
tool execution, retries and streaming all run exactly as they would with a real
model; only the model's choices are pre-written. That keeps tests and the default
demo free of GPUs and API keys.

The real model (vLLM through its OpenAI-compatible API) is wired in Phase 5.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.config import get_settings

DEMO_PROVIDER = "demo_scripted"


class ScriptedChatModel(BaseChatModel):
    """Plays back `script` as tool calls, one per model turn, then a final message."""

    script: list[dict[str, Any]] = Field(default_factory=list)
    final_text: str = "Finished gathering evidence."

    @property
    def _llm_type(self) -> str:
        return DEMO_PROVIDER

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        # The script already names the tools; nothing to bind.
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        done = sum(isinstance(m, ToolMessage) for m in messages)
        if done < len(self.script):
            step = self.script[done]
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": step["name"],
                        "args": step.get("args", {}),
                        "id": f"call_{done}_{step['name']}",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            message = AIMessage(content=self.final_text)
        return ChatResult(generations=[ChatGeneration(message=message)])


def provider_name() -> str:
    """Label stored on findings so the UI can show which model produced them."""
    return DEMO_PROVIDER if get_settings().demo_mode else get_settings().llm_model


def get_chat_model(*, demo_script: list[dict[str, Any]] | None = None) -> BaseChatModel:
    """Return the chat model specialists use. `demo_script` is only used in DEMO_MODE."""
    if get_settings().demo_mode:
        return ScriptedChatModel(script=list(demo_script or []))
    raise RuntimeError(
        "DEMO_MODE=false needs the vLLM provider, which is added in Phase 5. "
        "Set DEMO_MODE=true for now."
    )
