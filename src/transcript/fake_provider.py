from __future__ import annotations

from src.shared.models import Transcript
from src.transcript.base import TranscriptProvider, TranscriptUnavailable


class FakeTranscriptProvider(TranscriptProvider):
    def __init__(self, responses: dict[str, Transcript | None]) -> None:
        self._responses = responses

    def fetch(self, video_id: str) -> Transcript | None:
        if video_id not in self._responses:
            raise TranscriptUnavailable(f"no fake response configured for {video_id}")
        return self._responses[video_id]
