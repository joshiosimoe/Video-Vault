from __future__ import annotations

import json
import os
from dataclasses import asdict

import boto3

from src.shared.models import Transcript, VideoMeta
from src.shared.state_store import StateStore, Status
from src.summarize.summarizer import build_summarizer


def _build_summarizer():
    return build_summarizer()


def _load_meta(store: StateStore, video_id: str) -> VideoMeta:
    item = store.get(video_id)
    if item is None:
        raise KeyError(f"no state row for {video_id}")
    return VideoMeta(
        video_id=item["video_id"],
        title=item["title"],
        channel=item["channel"],
        published_at=item["published_at"],
        duration_seconds=int(item["duration_seconds"]),
    )


def handler(event: dict, context) -> dict:
    video_id = event["video_id"]
    store = StateStore(os.environ["STATE_TABLE"])

    body = (
        boto3.client("s3")
        .get_object(Bucket=os.environ["CONTENT_BUCKET"], Key=event["transcript_s3_key"])["Body"]
        .read()
    )
    transcript = Transcript.from_dict(json.loads(body))

    summary = _build_summarizer().summarize(_load_meta(store, video_id), transcript)
    store.set_status(video_id, Status.SUMMARIZED)

    return {"video_id": video_id, "summary": asdict(summary)}
