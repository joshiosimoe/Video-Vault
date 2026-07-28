"""Re-run summarization over archived transcripts. No transcript API calls."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from src.notes.renderer import note_path, render_note
from src.shared.artifacts import build_summary_artifact, write_summary_artifact
from src.shared.config import get_parameter
from src.shared.models import Transcript, VideoMeta
from src.shared.state_store import StateStore, Status
from src.summarize.summarizer import build_summarizer
from src.vault_repo.committer import VaultCommitter


def _load_transcript(s3_client, bucket: str, video_id: str) -> Transcript | None:
    try:
        body = s3_client.get_object(Bucket=bucket, Key=f"transcripts/{video_id}.json")[
            "Body"
        ].read()
    except ClientError as exc:
        # GET returns a modelled error document, so a genuine miss is NoSuchKey.
        # Anything else (AccessDenied, SlowDown) is a real problem, not an absence.
        if exc.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise
    return Transcript.from_dict(json.loads(body))


def resummarize(
    video_ids: list[str],
    s3_client,
    store: StateStore,
    summarizer,
    committer,
    bucket: str,
) -> list[str]:
    today = datetime.now(UTC).date().isoformat()
    committed: list[str] = []

    for video_id in video_ids:
        transcript = _load_transcript(s3_client, bucket, video_id)
        if transcript is None:
            print(f"skip {video_id}: no archived transcript")
            continue

        item = store.get(video_id)
        if item is None:
            print(f"skip {video_id}: no state row")
            continue

        meta = VideoMeta(
            video_id=item["video_id"],
            title=item["title"],
            channel=item["channel"],
            published_at=item["published_at"],
            duration_seconds=int(item["duration_seconds"]),
        )
        summary = summarizer.summarize(meta, transcript)
        content = render_note(meta, summary, saved_at=today, summarized_at=today)
        path = note_path(meta)

        write_summary_artifact(
            build_summary_artifact(meta, summary, path, today),
            bucket=bucket,
            s3_client=s3_client,
        )
        committer.commit_note(path, content, f"chore: re-summarize {meta.title}")
        store.set_status(video_id, Status.DONE, note_path=path)
        committed.append(path)
        print(f"committed {path}")

    return committed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="re-summarize every video marked done")
    parser.add_argument("video_ids", nargs="*", help="specific video IDs")
    args = parser.parse_args()

    store = StateStore(os.environ["STATE_TABLE"])
    video_ids = args.video_ids
    if args.all:
        video_ids = [item["video_id"] for item in store.list_by_status(Status.DONE)]

    if not video_ids:
        parser.error("pass video IDs or --all")

    committer = VaultCommitter(
        token=get_parameter(os.environ["GITHUB_TOKEN_PARAM"]),
        owner=os.environ["VAULT_REPO_OWNER"],
        repo=os.environ["VAULT_REPO_NAME"],
    )
    resummarize(
        video_ids=video_ids,
        s3_client=boto3.client("s3"),
        store=store,
        summarizer=build_summarizer(),
        committer=committer,
        bucket=os.environ["CONTENT_BUCKET"],
    )


if __name__ == "__main__":
    main()
