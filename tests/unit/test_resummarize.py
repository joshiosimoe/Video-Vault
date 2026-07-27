import json

import boto3
import pytest
from moto import mock_aws

from scripts.resummarize import resummarize
from src.shared.models import Summary, Transcript, TranscriptSegment, VideoMeta
from src.shared.state_store import StateStore

BUCKET = "vv-content"
TABLE = "vv-state"
META = VideoMeta("abc123", "A Title", "Chan", "2026-07-01T00:00:00Z", 600)
TRANSCRIPT = Transcript(
    video_id="abc123",
    segments=[TranscriptSegment(start_seconds=0, text="hi")],
    language="en",
)
SUMMARY = Summary(verdict="v", tldr="t", takeaways=["a"], sections=[], tags=["x"])


class FakeSummarizer:
    def summarize(self, meta, transcript):
        return SUMMARY


class FakeCommitter:
    def __init__(self):
        self.commits = []

    def commit_note(self, path, content, message):
        self.commits.append((path, content, message))


@pytest.fixture
def aws():
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
        StateStore(TABLE).try_insert(META)
        yield s3


def test_resummarize_commits_regenerated_note_without_refetching(aws):
    committer = FakeCommitter()
    paths = resummarize(
        video_ids=["abc123"],
        s3_client=aws,
        store=StateStore(TABLE),
        summarizer=FakeSummarizer(),
        committer=committer,
        bucket=BUCKET,
    )

    assert paths == ["Video Vault/2026/A Title-abc123.md"]
    _, content, message = committer.commits[0]
    assert "> **Verdict:** v" in content
    assert message.startswith("chore: re-summarize")


def test_resummarize_rewrites_the_summary_artifact(aws):
    resummarize(
        video_ids=["abc123"],
        s3_client=aws,
        store=StateStore(TABLE),
        summarizer=FakeSummarizer(),
        committer=FakeCommitter(),
        bucket=BUCKET,
    )

    body = aws.get_object(Bucket=BUCKET, Key="summaries/abc123.json")["Body"].read()
    artifact = json.loads(body)
    assert artifact["video_id"] == "abc123"
    assert artifact["summary"]["verdict"] == "v"


def test_resummarize_skips_videos_without_archived_transcript(aws):
    StateStore(TABLE).try_insert(VideoMeta("missing", "Gone", "Chan", "2026-07-01T00:00:00Z", 60))
    committer = FakeCommitter()

    paths = resummarize(
        video_ids=["missing"],
        s3_client=aws,
        store=StateStore(TABLE),
        summarizer=FakeSummarizer(),
        committer=committer,
        bucket=BUCKET,
    )

    assert paths == []
    assert committer.commits == []
