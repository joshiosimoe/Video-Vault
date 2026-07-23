import json
from dataclasses import asdict

import boto3
import pytest
from moto import mock_aws

from src.handlers import render_commit
from src.shared.models import Section, Summary, VideoMeta
from src.shared.state_store import StateStore, Status

TABLE = "vv-state"
BUCKET = "vv-content"
META = VideoMeta("abc123", "A Title", "A Channel", "2026-07-01T00:00:00Z", 600)
SUMMARY = Summary(
    verdict="Worth it.",
    tldr="Short.",
    takeaways=["one"],
    sections=[Section(start_seconds=60, title="Part", summary="Detail.")],
    tags=["python"],
)


class FakeCommitter:
    def __init__(self):
        self.commits = []

    def commit_note(self, path, content, message):
        self.commits.append((path, content, message))


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
        monkeypatch.setenv("STATE_TABLE", TABLE)
        monkeypatch.setenv("CONTENT_BUCKET", BUCKET)
        StateStore(TABLE).try_insert(META)
        yield


def _artifact(video_id: str) -> dict:
    body = (
        boto3.client("s3", region_name="us-east-1")
        .get_object(Bucket=BUCKET, Key=f"summaries/{video_id}.json")["Body"]
        .read()
    )
    return json.loads(body)


def test_commits_rendered_note_and_marks_done(aws, monkeypatch):
    fake = FakeCommitter()
    monkeypatch.setattr(render_commit, "_build_committer", lambda: fake)

    result = render_commit.handler({"video_id": "abc123", "summary": asdict(SUMMARY)}, None)

    path, content, message = fake.commits[0]
    assert path == "Video Vault/2026/A Title-abc123.md"
    assert "> **Verdict:** Worth it." in content
    assert "&t=60" in content
    assert message.startswith("feat: add note")

    item = StateStore(TABLE).get("abc123")
    assert item["status"] == Status.DONE
    assert item["note_path"] == result["note_path"]


def test_writes_self_contained_summary_artifact_to_s3(aws, monkeypatch):
    monkeypatch.setattr(render_commit, "_build_committer", lambda: FakeCommitter())

    render_commit.handler({"video_id": "abc123", "summary": asdict(SUMMARY)}, None)

    artifact = _artifact("abc123")
    assert artifact["video_id"] == "abc123"
    assert artifact["title"] == "A Title"
    assert artifact["channel"] == "A Channel"
    assert artifact["url"] == "https://www.youtube.com/watch?v=abc123"
    assert artifact["duration_seconds"] == 600
    assert artifact["note_path"] == "Video Vault/2026/A Title-abc123.md"
    assert artifact["summary"]["verdict"] == "Worth it."
    assert artifact["summary"]["sections"][0]["start_seconds"] == 60


def test_writes_artifact_before_committing(aws, monkeypatch):
    """A GitHub failure must not cost the summary artifact."""

    class ExplodingCommitter:
        def commit_note(self, path, content, message):
            raise RuntimeError("github is down")

    monkeypatch.setattr(render_commit, "_build_committer", ExplodingCommitter)

    with pytest.raises(RuntimeError):
        render_commit.handler({"video_id": "abc123", "summary": asdict(SUMMARY)}, None)

    assert _artifact("abc123")["video_id"] == "abc123"


def test_stub_handler_commits_no_transcript_note(aws, monkeypatch):
    fake = FakeCommitter()
    monkeypatch.setattr(render_commit, "_build_committer", lambda: fake)

    render_commit.stub_handler({"video_id": "abc123"}, None)

    _, content, _ = fake.commits[0]
    assert "status: no-transcript" in content
    assert StateStore(TABLE).get("abc123")["status"] == Status.DONE


def test_stub_handler_writes_no_summary_artifact(aws, monkeypatch):
    monkeypatch.setattr(render_commit, "_build_committer", lambda: FakeCommitter())

    render_commit.stub_handler({"video_id": "abc123"}, None)

    listing = boto3.client("s3", region_name="us-east-1").list_objects_v2(
        Bucket=BUCKET, Prefix="summaries/"
    )
    assert listing.get("KeyCount", 0) == 0
