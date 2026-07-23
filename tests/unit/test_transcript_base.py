import pytest

from src.shared.models import Transcript, TranscriptSegment
from src.transcript.base import TranscriptProvider, TranscriptUnavailable
from src.transcript.fake_provider import FakeTranscriptProvider

TRANSCRIPT = Transcript(
    video_id="abc123",
    segments=[TranscriptSegment(start_seconds=0, text="hello")],
    language="en",
)


def test_fake_provider_returns_configured_transcript():
    provider = FakeTranscriptProvider({"abc123": TRANSCRIPT})
    assert provider.fetch("abc123") == TRANSCRIPT


def test_fake_provider_returns_none_for_missing_captions():
    provider = FakeTranscriptProvider({"abc123": None})
    assert provider.fetch("abc123") is None


def test_fake_provider_raises_for_unconfigured_video():
    provider = FakeTranscriptProvider({})
    with pytest.raises(TranscriptUnavailable):
        provider.fetch("unknown")


def test_provider_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TranscriptProvider()
