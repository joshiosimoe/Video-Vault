from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import boto3

from src.shared.config import get_parameter
from src.shared.state_store import StateStore, Status
from src.youtube.client import YouTubeClient

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(hours=1)


def _build_client() -> YouTubeClient:
    return YouTubeClient(
        client_id=get_parameter(os.environ["GOOGLE_CLIENT_ID_PARAM"]),
        client_secret=get_parameter(os.environ["GOOGLE_CLIENT_SECRET_PARAM"]),
        refresh_token=get_parameter(os.environ["GOOGLE_REFRESH_TOKEN_PARAM"]),
    )


def _stale_cutoff() -> str:
    return (datetime.now(UTC) - STALE_AFTER).isoformat()


def _enqueue(queue_url: str, video_id: str) -> None:
    boto3.client("sqs").send_message(
        QueueUrl=queue_url, MessageBody=json.dumps({"video_id": video_id})
    )


def handler(event: dict, context) -> dict:
    store = StateStore(os.environ["STATE_TABLE"])
    queue_url = os.environ["QUEUE_URL"]

    playlist_ids = _build_client().list_playlist_video_ids(os.environ["PLAYLIST_ID"])
    unknown = [vid for vid in playlist_ids if store.get(vid) is None]

    new_count = 0
    if unknown:
        for meta in _build_client().get_video_metadata(unknown):
            if store.try_insert(meta):
                _enqueue(queue_url, meta.video_id)
                new_count += 1

    cutoff = _stale_cutoff()
    requeued = 0

    for item in store.list_by_status(Status.QUEUED, older_than_iso=cutoff):
        _enqueue(queue_url, item["video_id"])
        requeued += 1

    for item in store.list_by_status(Status.FAILED, older_than_iso=cutoff):
        if int(item.get("attempts", 0)) < MAX_ATTEMPTS:
            _enqueue(queue_url, item["video_id"])
            requeued += 1

    return {"new": new_count, "requeued": requeued}
