import boto3
import pytest
from moto import mock_aws

from src.shared.models import VideoMeta
from src.shared.state_store import StateStore, Status

TABLE = "video-vault-state"

META = VideoMeta(
    video_id="abc123",
    title="A Title",
    channel="A Channel",
    published_at="2026-07-01T00:00:00Z",
    duration_seconds=600,
)


@pytest.fixture
def store():
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "video_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "video_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield StateStore(TABLE)


def test_try_insert_returns_true_for_new_video(store):
    assert store.try_insert(META) is True


def test_try_insert_returns_false_for_duplicate(store):
    store.try_insert(META)
    assert store.try_insert(META) is False


def test_insert_records_metadata_and_queued_status(store):
    store.try_insert(META)
    item = store.get("abc123")
    assert item["status"] == Status.QUEUED
    assert item["title"] == "A Title"
    assert item["duration_seconds"] == 600
    assert item["attempts"] == 0


def test_get_returns_none_for_unknown_video(store):
    assert store.get("nope") is None


def test_set_status_updates_status_and_extra_attributes(store):
    store.try_insert(META)
    store.set_status("abc123", Status.DONE, note_path="Video Vault/2026/x.md")
    item = store.get("abc123")
    assert item["status"] == Status.DONE
    assert item["note_path"] == "Video Vault/2026/x.md"


def test_mark_failed_records_error_and_increments_attempts(store):
    store.try_insert(META)
    store.mark_failed("abc123", "boom")
    store.mark_failed("abc123", "boom again")
    item = store.get("abc123")
    assert item["status"] == Status.FAILED
    assert item["error"] == "boom again"
    assert item["attempts"] == 2


def test_list_by_status_filters_correctly(store):
    store.try_insert(META)
    store.try_insert(VideoMeta("def456", "Other", "Chan", "2026-07-02T00:00:00Z", 120))
    store.set_status("def456", Status.DONE)

    queued = store.list_by_status(Status.QUEUED)
    assert [item["video_id"] for item in queued] == ["abc123"]


def test_list_by_status_respects_older_than(store):
    store.try_insert(META)
    assert store.list_by_status(Status.QUEUED, older_than_iso="2000-01-01T00:00:00Z") == []
    assert len(store.list_by_status(Status.QUEUED, older_than_iso="2999-01-01T00:00:00Z")) == 1
