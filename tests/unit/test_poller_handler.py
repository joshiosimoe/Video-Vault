import json
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from src.handlers import poller
from src.shared.models import VideoMeta
from src.shared.state_store import StateStore, Status

TABLE = "vv-state"
QUEUE = "vv-queue"

META_1 = VideoMeta("v1", "One", "Chan", "2026-07-01T00:00:00Z", 100)
META_2 = VideoMeta("v2", "Two", "Chan", "2026-07-02T00:00:00Z", 200)


class FakeYouTube:
    def __init__(self, ids, metas):
        self._ids = ids
        self._metas = metas

    def list_playlist_video_ids(self, playlist_id):
        return self._ids

    def get_video_metadata(self, video_ids):
        return [m for m in self._metas if m.video_id in video_ids]


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "video_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "video_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        url = boto3.client("sqs", region_name="us-east-1").create_queue(QueueName=QUEUE)["QueueUrl"]
        monkeypatch.setenv("STATE_TABLE", TABLE)
        monkeypatch.setenv("QUEUE_URL", url)
        monkeypatch.setenv("PLAYLIST_ID", "PL123")
        yield url


def _messages(url):
    response = boto3.client("sqs", region_name="us-east-1").receive_message(
        QueueUrl=url, MaxNumberOfMessages=10
    )
    return [json.loads(m["Body"])["video_id"] for m in response.get("Messages", [])]


def test_enqueues_new_videos_only(aws, monkeypatch):
    monkeypatch.setattr(
        poller, "_build_client", lambda: FakeYouTube(["v1", "v2"], [META_1, META_2])
    )

    result = poller.handler({}, None)

    assert result["new"] == 2
    assert sorted(_messages(aws)) == ["v1", "v2"]


def test_skips_videos_already_known(aws, monkeypatch):
    StateStore(TABLE).try_insert(META_1)
    monkeypatch.setattr(
        poller, "_build_client", lambda: FakeYouTube(["v1", "v2"], [META_1, META_2])
    )

    result = poller.handler({}, None)

    assert result["new"] == 1
    assert _messages(aws) == ["v2"]


def test_requeues_stale_queued_and_retryable_failed(aws, monkeypatch):
    store = StateStore(TABLE)
    store.try_insert(META_1)
    store.try_insert(META_2)
    store.mark_failed("v2", "boom")
    monkeypatch.setattr(poller, "_build_client", lambda: FakeYouTube([], []))
    monkeypatch.setattr(poller, "_stale_cutoff", lambda: "2999-01-01T00:00:00Z")

    result = poller.handler({}, None)

    assert result["new"] == 0
    assert result["requeued"] == 2
    assert sorted(_messages(aws)) == ["v1", "v2"]


def test_does_not_requeue_failed_past_attempt_limit(aws, monkeypatch):
    store = StateStore(TABLE)
    store.try_insert(META_1)
    for _ in range(3):
        store.mark_failed("v1", "boom")
    monkeypatch.setattr(poller, "_build_client", lambda: FakeYouTube([], []))
    monkeypatch.setattr(poller, "_stale_cutoff", lambda: "2999-01-01T00:00:00Z")

    assert poller.handler({}, None)["requeued"] == 0
    assert _messages(aws) == []


def test_does_not_requeue_a_row_failed_moments_ago_by_step_functions(aws, monkeypatch):
    # Production writes `failed` rows from the Step Functions MarkFailed state, whose
    # $$.State.EnteredTime is RFC 3339 "Z" form -- not the "+00:00" form
    # state_store._now() produces. Every other requeue test monkeypatches
    # _stale_cutoff to 2999, so the real one is only exercised here: a row failed
    # just now must fall on the fresh side of the lexicographic cutoff.
    StateStore(TABLE).try_insert(META_1)
    boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE).update_item(
        Key={"video_id": "v1"},
        UpdateExpression="SET #s = :s, updated_at = :u, attempts = :a",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": Status.FAILED,
            ":u": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            ":a": 1,
        },
    )
    monkeypatch.setattr(poller, "_build_client", lambda: FakeYouTube([], []))

    assert poller.handler({}, None)["requeued"] == 0
    assert _messages(aws) == []
