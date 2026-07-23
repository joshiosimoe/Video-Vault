from __future__ import annotations

import json
from dataclasses import asdict

import boto3

from src.notes.renderer import WATCH_URL
from src.shared.models import Summary, VideoMeta


def build_summary_artifact(
    meta: VideoMeta, summary: Summary, note_path_value: str, summarized_at: str
) -> dict:
    """Self-contained record for downstream consumers (e.g. the planned RAG).

    Deliberately repeats video metadata so an ingester can process a single
    S3 object without a DynamoDB lookup. The sections array doubles as a
    chunk boundary, and each start_seconds supports timestamp-linked citations.
    """
    return {
        "video_id": meta.video_id,
        "title": meta.title,
        "channel": meta.channel,
        "url": WATCH_URL.format(video_id=meta.video_id),
        "published_at": meta.published_at,
        "duration_seconds": meta.duration_seconds,
        "summarized_at": summarized_at,
        "note_path": note_path_value,
        "summary": asdict(summary),
    }


def write_summary_artifact(artifact: dict, bucket: str, s3_client=None) -> None:
    client = s3_client or boto3.client("s3")
    client.put_object(
        Bucket=bucket,
        Key=f"summaries/{artifact['video_id']}.json",
        Body=json.dumps(artifact).encode(),
        ContentType="application/json",
    )
