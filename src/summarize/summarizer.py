from __future__ import annotations

import json
import os

from src.shared.models import Summary, Transcript, VideoMeta
from src.summarize.prompt import SYSTEM_PROMPT, build_user_message
from src.summarize.schema import SUMMARY_SCHEMA

MODEL_ID = "anthropic.claude-sonnet-5"
MAX_TOKENS = 8192


class Summarizer:
    def __init__(self, client) -> None:
        self._client = client

    def summarize(self, meta: VideoMeta, transcript: Transcript) -> Summary:
        response = self._client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            thinking={"type": "disabled"},
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(meta, transcript)}],
        )
        text = next(block.text for block in response.content if block.type == "text")
        return Summary.from_dict(json.loads(text))


def build_summarizer() -> Summarizer:
    from anthropic import AnthropicBedrockMantle

    client = AnthropicBedrockMantle(aws_region=os.environ["BEDROCK_REGION"])
    return Summarizer(client)
