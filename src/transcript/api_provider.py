from __future__ import annotations

import httpx

from src.shared.models import Transcript, TranscriptSegment
from src.transcript.base import TranscriptProvider, TranscriptUnavailable

DEFAULT_BASE_URL = "https://api.supadata.ai/v1"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


class ApiTranscriptProvider(TranscriptProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def fetch(self, video_id: str) -> Transcript | None:
        try:
            response = httpx.get(
                f"{self._base_url}/transcript",
                params={
                    "url": WATCH_URL.format(video_id=video_id),
                    "mode": "native",
                    "text": "false",
                },
                headers={"x-api-key": self._api_key},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise TranscriptUnavailable(f"network error for {video_id}: {exc}") from exc

        # 206 (transcript-unavailable, no captions) and 202 (async job) are both
        # < 400 and must be handled before the >= 400 branch, or they fall
        # through and get parsed as a zero-segment Transcript.
        if response.status_code == 206:
            return None
        if response.status_code == 404:
            return None
        if response.status_code == 202:
            raise TranscriptUnavailable(
                f"provider returned async job for {video_id}, mode=native should preclude this"
            )
        if response.status_code >= 400:
            raise TranscriptUnavailable(f"provider returned {response.status_code} for {video_id}")

        # Anything else under 400 would fall through to _to_transcript, whose .get()
        # defaults would turn an unrecognised body into a zero-segment Transcript --
        # exactly the silent failure the 206 case caused. Fail loudly instead.
        if response.status_code != 200:
            raise TranscriptUnavailable(
                f"provider returned unexpected status {response.status_code} for {video_id}"
            )

        return self._to_transcript(video_id, response.json())

    @staticmethod
    def _to_transcript(video_id: str, payload: dict) -> Transcript:
        """Map the vendor payload to our model. Vendor offsets are milliseconds."""
        segments = [
            TranscriptSegment(
                start_seconds=int(item.get("offset", 0)) // 1000,
                text=item.get("text", ""),
            )
            for item in payload.get("content", [])
        ]
        return Transcript(
            video_id=video_id,
            segments=segments,
            language=payload.get("lang", "unknown"),
        )
