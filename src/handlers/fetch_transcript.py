from __future__ import annotations

import json
import os

import boto3
from botocore.exceptions import ClientError

from src.shared.config import get_parameter
from src.shared.metrics import emit_count
from src.shared.state_store import StateStore, Status
from src.transcript.factory import build_provider


def _s3():
    return boto3.client("s3")


def _build_provider():
    return build_provider(get_parameter(os.environ["TRANSCRIPT_API_KEY_PARAM"]))


def _transcript_key(video_id: str) -> str:
    return f"transcripts/{video_id}.json"


# HEAD carries no response body, so botocore surfaces the bare status code rather
# than the modelled NoSuchKey. Accept both; anything else (AccessDenied, throttling)
# must propagate -- swallowing it here silently re-fetches and re-bills a transcript.
_NOT_FOUND_CODES = {"404", "NoSuchKey"}


def _existing_object(bucket: str, key: str) -> bool:
    try:
        _s3().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in _NOT_FOUND_CODES:
            return False
        raise
    return True


def handler(event: dict, context) -> dict:
    video_id = event["video_id"]
    bucket = os.environ["CONTENT_BUCKET"]
    store = StateStore(os.environ["STATE_TABLE"])
    key = _transcript_key(video_id)

    if _existing_object(bucket, key):
        store.set_status(video_id, Status.TRANSCRIBED, transcript_s3_key=key)
        return {"video_id": video_id, "transcript_s3_key": key, "has_transcript": True}

    provider = _build_provider()
    emit_count("TranscriptCalls", video_id=video_id)
    transcript = provider.fetch(video_id)

    if transcript is None:
        store.set_status(video_id, Status.NO_TRANSCRIPT)
        return {"video_id": video_id, "transcript_s3_key": None, "has_transcript": False}

    _s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(transcript.to_dict()).encode(),
        ContentType="application/json",
    )
    store.set_status(video_id, Status.TRANSCRIBED, transcript_s3_key=key)
    return {"video_id": video_id, "transcript_s3_key": key, "has_transcript": True}
