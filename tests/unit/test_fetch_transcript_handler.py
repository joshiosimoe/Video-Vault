import json

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from src.handlers import fetch_transcript
from src.shared.models import Transcript, TranscriptSegment, VideoMeta
from src.shared.state_store import StateStore, Status
from src.transcript.fake_provider import FakeTranscriptProvider

BUCKET = "vv-content"
TABLE = "vv-state"

META = VideoMeta("abc123", "T", "C", "2026-07-01T00:00:00Z", 600)
TRANSCRIPT = Transcript(
    video_id="abc123",
    segments=[TranscriptSegment(start_seconds=0, text="hello")],
    language="en",
)


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
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


def test_writes_transcript_to_s3_and_marks_transcribed(aws, monkeypatch):
    monkeypatch.setattr(
        fetch_transcript,
        "_build_provider",
        lambda: FakeTranscriptProvider({"abc123": TRANSCRIPT}),
    )

    result = fetch_transcript.handler({"video_id": "abc123"}, None)

    assert result["has_transcript"] is True
    assert result["transcript_s3_key"] == "transcripts/abc123.json"

    body = (
        boto3.client("s3", region_name="us-east-1")
        .get_object(Bucket=BUCKET, Key="transcripts/abc123.json")["Body"]
        .read()
    )
    assert Transcript.from_dict(json.loads(body)) == TRANSCRIPT
    assert StateStore(TABLE).get("abc123")["status"] == Status.TRANSCRIBED


def test_reports_missing_captions_without_writing_s3(aws, monkeypatch):
    monkeypatch.setattr(
        fetch_transcript,
        "_build_provider",
        lambda: FakeTranscriptProvider({"abc123": None}),
    )

    result = fetch_transcript.handler({"video_id": "abc123"}, None)

    assert result["has_transcript"] is False
    assert result["transcript_s3_key"] is None
    assert StateStore(TABLE).get("abc123")["status"] == Status.NO_TRANSCRIPT


def test_reuses_existing_s3_object_without_calling_provider(aws, monkeypatch):
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=BUCKET,
        Key="transcripts/abc123.json",
        Body=json.dumps(TRANSCRIPT.to_dict()).encode(),
    )

    def explode():
        raise AssertionError("provider should not be called when S3 object exists")

    monkeypatch.setattr(fetch_transcript, "_build_provider", explode)

    result = fetch_transcript.handler({"video_id": "abc123"}, None)
    assert result["has_transcript"] is True


def test_non_404_head_object_error_propagates(aws, monkeypatch):
    # A permissions or throttling failure must not be read as "object absent":
    # that silently re-fetches and re-bills a paid transcript credit.
    class DeniedS3:
        def head_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "HeadObject"
            )

    def explode():
        raise AssertionError("provider must not be called when S3 access fails")

    monkeypatch.setattr(fetch_transcript, "_s3", lambda: DeniedS3())
    monkeypatch.setattr(fetch_transcript, "_build_provider", explode)

    with pytest.raises(ClientError):
        fetch_transcript.handler({"video_id": "abc123"}, None)


def _emitted_metrics(captured: str) -> list[dict]:
    records = []
    for line in captured.splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "_aws" in parsed:
            records.append(parsed)
    return records


def test_emits_transcript_call_metric_when_provider_is_used(aws, monkeypatch, capsys):
    monkeypatch.setattr(
        fetch_transcript,
        "_build_provider",
        lambda: FakeTranscriptProvider({"abc123": TRANSCRIPT}),
    )

    fetch_transcript.handler({"video_id": "abc123"}, None)

    [record] = _emitted_metrics(capsys.readouterr().out)
    assert record["TranscriptCalls"] == 1
    assert record["video_id"] == "abc123"
    assert record["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "VideoVault"


def test_does_not_emit_metric_on_s3_cache_hit(aws, monkeypatch, capsys):
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=BUCKET,
        Key="transcripts/abc123.json",
        Body=json.dumps(TRANSCRIPT.to_dict()).encode(),
    )
    monkeypatch.setattr(fetch_transcript, "_build_provider", lambda: None)

    fetch_transcript.handler({"video_id": "abc123"}, None)

    assert _emitted_metrics(capsys.readouterr().out) == []
