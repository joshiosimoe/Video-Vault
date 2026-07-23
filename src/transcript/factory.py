from __future__ import annotations

import os

from src.transcript.api_provider import ApiTranscriptProvider
from src.transcript.base import TranscriptProvider


def build_provider(api_key: str) -> TranscriptProvider:
    kind = os.environ.get("TRANSCRIPT_PROVIDER", "api")
    if kind == "api":
        return ApiTranscriptProvider(api_key=api_key)
    raise ValueError(f"unknown TRANSCRIPT_PROVIDER: {kind}")
