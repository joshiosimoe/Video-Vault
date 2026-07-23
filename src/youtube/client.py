from __future__ import annotations

import re

import httpx

from src.shared.models import VideoMeta

DEFAULT_BASE_URL = "https://www.googleapis.com/youtube/v3"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
BATCH_SIZE = 50

_DURATION = re.compile(
    r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def parse_iso_duration(value: str) -> int:
    match = _DURATION.fullmatch(value)
    if match is None:
        return 0
    parts = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


class YouTubeClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        base_url: str = DEFAULT_BASE_URL,
        token_url: str = DEFAULT_TOKEN_URL,
        timeout: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url
        self._timeout = timeout
        self._access_token: str | None = None

    def _token(self) -> str:
        if self._access_token is None:
            response = httpx.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            self._access_token = response.json()["access_token"]
        return self._access_token

    def _get(self, path: str, params: dict) -> dict:
        response = httpx.get(
            f"{self._base_url}/{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token()}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_playlist_video_ids(self, playlist_id: str) -> list[str]:
        video_ids: list[str] = []
        page_token: str | None = None

        while True:
            params = {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": BATCH_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token

            payload = self._get("playlistItems", params)
            video_ids += [item["contentDetails"]["videoId"] for item in payload.get("items", [])]

            page_token = payload.get("nextPageToken")
            if not page_token:
                return video_ids

    def get_video_metadata(self, video_ids: list[str]) -> list[VideoMeta]:
        results: list[VideoMeta] = []

        for start in range(0, len(video_ids), BATCH_SIZE):
            batch = video_ids[start : start + BATCH_SIZE]
            payload = self._get(
                "videos",
                {"part": "snippet,contentDetails", "id": ",".join(batch)},
            )
            for item in payload.get("items", []):
                snippet = item["snippet"]
                results.append(
                    VideoMeta(
                        video_id=item["id"],
                        title=snippet["title"],
                        channel=snippet["channelTitle"],
                        published_at=snippet["publishedAt"],
                        duration_seconds=parse_iso_duration(item["contentDetails"]["duration"]),
                    )
                )
        return results
