import json

import boto3
import pytest
from moto import mock_aws

from src.handlers import summarize as summarize_handler
from src.shared.models import Summary, Transcript, TranscriptSegment, VideoMeta
from src.shared.state_store import StateStore, Status

BUCKET = "vv-content"
TABLE = "vv-state"

META = VideoMeta("abc123", "T", "C", "2026-07-01T00:00:00Z", 600)
TRANSCRIPT = Transcript(
    video_id="abc123",
    segments=[TranscriptSegment(start_seconds=0, text="hello")],
    language="en",
)
SUMMARY = Summary(verdict="v", tldr="t", takeaways=["a"], sections=[], tags=["x"])


class FakeSummarizer:
    def __init__(self):
        self.calls = []

    def summarize(self, meta, transcript):
        self.calls.append((meta, transcript))
        return SUMMARY


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        s3.put_object(
            Bucket=BUCKET,
            Key="transcripts/abc123.json",
            Body=json.dumps(TRANSCRIPT.to_dict()).encode(),
        )
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "video_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "video_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("CONTENT_BUCKET", BUCKET)
        monkeypatch.setenv("STATE_TABLE", TABLE)
        StateStore(TABLE).try_insert(META)
        yield


def test_summarizes_transcript_and_marks_summarized(aws, monkeypatch):
    fake = FakeSummarizer()
    monkeypatch.setattr(summarize_handler, "_build_summarizer", lambda: fake)

    result = summarize_handler.handler(
        {"video_id": "abc123", "transcript_s3_key": "transcripts/abc123.json"}, None
    )

    assert result["summary"]["verdict"] == "v"
    assert StateStore(TABLE).get("abc123")["status"] == Status.SUMMARIZED


def test_passes_stored_metadata_to_summarizer(aws, monkeypatch):
    fake = FakeSummarizer()
    monkeypatch.setattr(summarize_handler, "_build_summarizer", lambda: fake)

    summarize_handler.handler(
        {"video_id": "abc123", "transcript_s3_key": "transcripts/abc123.json"}, None
    )

    meta, transcript = fake.calls[0]
    assert meta.title == "T"
    assert meta.duration_seconds == 600
    assert transcript == TRANSCRIPT
