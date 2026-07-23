from __future__ import annotations

from abc import ABC, abstractmethod

from src.shared.models import Transcript


class TranscriptUnavailable(Exception):
    """Transient failure fetching a transcript. Safe to retry."""


class TranscriptProvider(ABC):
    @abstractmethod
    def fetch(self, video_id: str) -> Transcript | None:
        """Return the transcript, or None if the video has no captions.

        Raises TranscriptUnavailable on transient failures.
        """
