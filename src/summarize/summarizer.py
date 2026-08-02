from __future__ import annotations

import json
import os

from src.shared.models import Summary, Transcript, VideoMeta
from src.summarize.prompt import SYSTEM_PROMPT, build_user_message
from src.summarize.schema import SUMMARY_SCHEMA

# The spec chose Sonnet 5, but this AWS account is not entitled to it -- Bedrock
# reports AUTHORIZED while the inference endpoint returns "not available for this
# account". Sonnet 4.6 is entitled and serves an identical request shape, so it is
# the default. The `us.` prefix selects the cross-region inference profile, which
# is how Bedrock exposes this model for on-demand use.
#
# The model is configuration rather than a constant so that swapping back is a
# variable change and a redeploy. The classic AnthropicBedrock client serves both
# models; AnthropicBedrockMantle serves only Sonnet 5, which is why it is not used
# here despite being the newer surface.
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
MAX_TOKENS = 8192


class SummarizationFailed(Exception):
    """The model returned a response the summarizer cannot parse."""


class Summarizer:
    def __init__(self, client, model_id: str = DEFAULT_MODEL_ID) -> None:
        self._client = client
        self._model_id = model_id

    def summarize(self, meta: VideoMeta, transcript: Transcript) -> Summary:
        response = self._client.messages.create(
            model=self._model_id,
            max_tokens=MAX_TOKENS,
            thinking={"type": "disabled"},
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(meta, transcript)}],
        )
        text = next(
            (block.text for block in response.content if block.type == "text"),
            None,
        )
        if text is None:
            raise SummarizationFailed(
                f"no text block for {meta.video_id}; stop_reason={response.stop_reason}"
            )
        return Summary.from_dict(json.loads(text))


def build_summarizer() -> Summarizer:
    from anthropic import AnthropicBedrock

    client = AnthropicBedrock(aws_region=os.environ["BEDROCK_REGION"])
    return Summarizer(client, os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID))
