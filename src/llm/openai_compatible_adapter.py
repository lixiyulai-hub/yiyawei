"""通用 OpenAI-compatible 本地服务适配器（llama.cpp server 等）。"""

from src.llm.lmstudio_adapter import LMStudioAdapter


class OpenAICompatibleAdapter(LMStudioAdapter):
    """与 LM Studio 相同 HTTP 协议，base_url 由用户配置。"""

    pass
