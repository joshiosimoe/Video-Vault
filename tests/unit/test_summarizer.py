import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.shared.models import Transcript, TranscriptSegment, VideoMeta
from src.summarize.schema import SUMMARY_SCHEMA
from src.summarize.summarizer import SummarizationFailed, Summarizer

META = VideoMeta(
    video_id="abc123",
    title="A Title",
    channel="A Channel",
    published_at="2026-07-01T00:00:00Z",
    duration_seconds=600,
)
TRANSCRIPT = Transcript(
    video_id="abc123",
    segments=[TranscriptSegment(start_seconds=0, text="hello world")],
    language="en",
)

PAYLOAD = {
    "verdict": "Skim it.",
    "tldr": "Short summary.",
    "takeaways": ["one"],
    "sections": [{"start_seconds": 0, "title": "Intro", "summary": "Framing."}],
    "tags": ["python"],
}


def _fake_client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))]
    )
    return client


def _fake_client_with_no_text_block(stop_reason: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(content=[], stop_reason=stop_reason)
    return client


def test_summarize_parses_structured_output():
    summarizer = Summarizer(_fake_client(PAYLOAD))
    result = summarizer.summarize(META, TRANSCRIPT)
    assert result.verdict == "Skim it."
    assert result.sections[0].start_seconds == 0
    assert result.tags == ["python"]


def test_summarize_uses_correct_bedrock_model_id():
    client = _fake_client(PAYLOAD)
    Summarizer(client).summarize(META, TRANSCRIPT)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "anthropic.claude-sonnet-5"


def test_summarize_disables_thinking_and_omits_sampling_params():
    client = _fake_client(PAYLOAD)
    Summarizer(client).summarize(META, TRANSCRIPT)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "disabled"}
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


def test_summarize_requests_structured_output():
    client = _fake_client(PAYLOAD)
    Summarizer(client).summarize(META, TRANSCRIPT)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["output_config"]["format"]["schema"] == SUMMARY_SCHEMA
    assert kwargs["output_config"]["effort"] == "low"


def test_summarize_raises_when_response_has_no_text_block():
    client = _fake_client_with_no_text_block("refusal")
    with pytest.raises(SummarizationFailed) as exc_info:
        Summarizer(client).summarize(META, TRANSCRIPT)
    assert "abc123" in str(exc_info.value)
    assert "refusal" in str(exc_info.value)


def test_schema_satisfies_structured_output_constraints():
    def check(node: dict) -> None:
        for key in ("minLength", "maxLength", "minimum", "maximum"):
            assert key not in node, f"forbidden JSON Schema keyword {key!r} found in {node}"
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                check(child)
        if node.get("type") == "array":
            check(node["items"])

    check(SUMMARY_SCHEMA)
