from __future__ import annotations

from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from src.shared.models import VideoMeta


class Status:
    QUEUED = "queued"
    TRANSCRIBED = "transcribed"
    SUMMARIZED = "summarized"
    DONE = "done"
    NO_TRANSCRIPT = "no_transcript"
    FAILED = "failed"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class StateStore:
    def __init__(self, table_name: str, client=None) -> None:
        self._table = client or boto3.resource("dynamodb").Table(table_name)

    def try_insert(self, meta: VideoMeta) -> bool:
        timestamp = _now()
        try:
            self._table.put_item(
                Item={
                    "video_id": meta.video_id,
                    "status": Status.QUEUED,
                    "title": meta.title,
                    "channel": meta.channel,
                    "published_at": meta.published_at,
                    "duration_seconds": meta.duration_seconds,
                    "attempts": 0,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
                ConditionExpression="attribute_not_exists(video_id)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def get(self, video_id: str) -> dict | None:
        response = self._table.get_item(Key={"video_id": video_id})
        item = response.get("Item")
        if item is None:
            return None
        if "duration_seconds" in item:
            item["duration_seconds"] = int(item["duration_seconds"])
        if "attempts" in item:
            item["attempts"] = int(item["attempts"])
        return item

    def set_status(self, video_id: str, status: str, **attrs) -> None:
        names = {"#s": "status", "#u": "updated_at"}
        values = {":s": status, ":u": _now()}
        assignments = ["#s = :s", "#u = :u"]

        for index, (key, value) in enumerate(attrs.items()):
            names[f"#a{index}"] = key
            values[f":a{index}"] = value
            assignments.append(f"#a{index} = :a{index}")

        self._table.update_item(
            Key={"video_id": video_id},
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def mark_failed(self, video_id: str, error: str) -> None:
        self._table.update_item(
            Key={"video_id": video_id},
            UpdateExpression=("SET #s = :s, #e = :e, #u = :u ADD #a :one"),
            ExpressionAttributeNames={
                "#s": "status",
                "#e": "error",
                "#u": "updated_at",
                "#a": "attempts",
            },
            ExpressionAttributeValues={
                ":s": Status.FAILED,
                ":e": error,
                ":u": _now(),
                ":one": 1,
            },
        )

    def list_by_status(self, status: str, older_than_iso: str | None = None) -> list[dict]:
        kwargs = {
            "FilterExpression": "#s = :s",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":s": status},
        }
        if older_than_iso is not None:
            kwargs["FilterExpression"] += " AND updated_at < :t"
            kwargs["ExpressionAttributeValues"][":t"] = older_than_iso

        items: list[dict] = []
        response = self._table.scan(**kwargs)
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = self._table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **kwargs)
            items.extend(response.get("Items", []))
        return items
