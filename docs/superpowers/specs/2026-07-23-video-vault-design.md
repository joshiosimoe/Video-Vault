# Video Vault — Design

**Date:** 2026-07-23
**Status:** Approved for planning

## Problem

Videos saved on YouTube for later never get watched. Time is the constraint, not interest. Reading a structured summary is faster than watching, and skimming a summary answers the only question that matters: *is this worth my time, and if so, which part?*

## Goals

1. Any video saved to a designated YouTube playlist is automatically summarized and lands in Obsidian as a note, with no manual step.
2. The note is skimmable top-down and lets the reader bail at any depth.
3. The note makes it possible to watch only the minutes that matter, via clickable timestamps.
4. The project demonstrates AWS and AI engineering competence to recruiters. The public repo is a portfolio artifact.
5. Total running cost stays under $10/month.

## Non-goals

- No web UI or dashboard. Obsidian is the interface.
- No multi-user support. Single user, single vault.
- No video or audio download. Transcript text only.
- No search layer. Obsidian's own search and graph are sufficient.
- No re-summarization UI. Re-running the summarizer over the archive is a CLI script.

## Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Trigger | Custom YouTube playlist, polled | Watch Later is not readable via Data API v3 (Google removed `WL` access in 2016). A custom playlist is fully accessible with OAuth. One habit change, zero scraping. |
| Transcript source | Third-party API free tier, behind a `TranscriptProvider` interface | YouTube blocks datacenter IPs, so calling the caption endpoint directly from Lambda fails frequently. Free tier covers ~100/month against expected 80. The interface makes swapping to a residential proxy (~$6/month) a config change. |
| Delivery | Dedicated Obsidian vault backed by a private GitHub repo | Keeps the AWS path fully cloud-native. Obsidian Git plugin pulls. Personal notes never leave the machine; the private repo holds only video summaries. |
| Note format | Layered skim note with timestamped sections | Matches the actual use case: verdict → TL;DR → takeaways → timestamped outline. Bail at any level. |
| Model | `anthropic.claude-sonnet-5` on Bedrock | ~$0.04/video. 1M context handles any video length. The worth-watching verdict is a judgment call where Haiku 4.5 thins out; Opus 4.8 is 3× the cost for no visible gain on transcript summarization. |
| Orchestration | Step Functions Standard workflow | Per-step retry protects the scarce transcript budget. Visual execution trace. Free at this volume (~480 transitions/month vs 4,000 free). Accepted cost: ~2× the IaC and harder local testing. |
| Transcript storage | S3 archive, written once per video | Prompt iteration is certain. Re-summarizing 80 archived transcripts costs ~$3 of Bedrock and zero API calls; re-fetching would consume 80% of the monthly free tier. Also required — Step Functions has a 256KB inter-state payload limit and long transcripts exceed it, so states pass S3 keys. |
| Secrets | SSM Parameter Store `SecureString` | Functionally equivalent here and free. Secrets Manager costs $0.40/secret/month and only earns it when automatic rotation is needed, which this is not. |

## Architecture

```
EventBridge Scheduler (rate: 15 minutes)
  │
  └─> Poller Lambda
        ├─ SSM: read YouTube OAuth refresh token
        ├─ YouTube Data API v3: playlistItems.list(VAULT_PLAYLIST_ID)
        ├─ DynamoDB: conditional PutItem (attribute_not_exists) per video
        ├─ SQS: enqueue newly-inserted video IDs
        └─ Reconcile sweep: re-enqueue items stuck in `queued` > 1 hour
                  │
                  ▼
              SQS queue ──────────> DLQ (after 3 receives)
                  │
                  ▼
        Step Functions (one execution per video)
          1. FetchTranscript   → S3 transcripts/, returns S3 key
          2. Choice: has_transcript?
               ├─ no  → WriteStubNote
               └─ yes → 3. Summarize      → Bedrock, structured JSON output
                        4. RenderAndCommit → S3 summaries/ + markdown to GitHub
          5. MarkDone → DynamoDB status
          Catch (any state) → MarkFailed → DynamoDB status + error
                  │
                  ▼
        Private GitHub repo (the vault)
                  │
                  ▼
        Obsidian Git plugin auto-pull → note appears
```

## Components

### Poller Lambda

Runs every 15 minutes via EventBridge Scheduler.

1. Reads the YouTube OAuth refresh token from SSM, exchanges it for an access token.
2. Calls `playlistItems.list` with `part=snippet,contentDetails`, paginating.
3. For each item, attempts a DynamoDB `PutItem` with `ConditionExpression: attribute_not_exists(video_id)`. A conditional-check failure means the video is already known — skip it.
4. Newly-inserted videos are sent to SQS.
5. Reconcile sweep: re-enqueue items in `queued` status older than one hour. This covers the window where the DynamoDB write succeeded but the SQS send failed, which would otherwise orphan the video.
6. Retry sweep: re-enqueue items in `failed` status with `attempts < 3`. Gives automatic recovery from transient provider or Bedrock outages without manual intervention.

**Pagination optimization:** `playlistItems.list` returns items in playlist order, not date order, so new additions land at the end. Rather than paginating the entire playlist every poll, stop paginating once a full page contains no new videos. Quota is not a concern regardless — `playlistItems.list` costs 1 unit, so even full pagination of a 1,000-item playlist at 96 polls/day is ~1,920 units against a 10,000/day quota.

### DynamoDB — `video-vault-state`

Partition key `video_id` (S). No sort key. On-demand billing.

| Attribute | Type | Notes |
|---|---|---|
| `video_id` | S | PK, YouTube video ID |
| `status` | S | `queued` \| `transcribed` \| `summarized` \| `done` \| `no_transcript` \| `failed` |
| `title` | S | From playlist snippet |
| `channel` | S | From playlist snippet |
| `published_at` | S | ISO 8601 |
| `duration_seconds` | N | From `contentDetails` |
| `transcript_s3_key` | S | Nullable |
| `note_path` | S | Path in the vault repo, nullable |
| `attempts` | N | Incremented per Step Functions execution |
| `error` | S | Last failure message, nullable |
| `created_at` / `updated_at` | S | ISO 8601 |

Serves as both the dedupe table and the retry ledger.

### S3 — `video-vault-content`

Two prefixes:

| Key | Contents |
|---|---|
| `transcripts/{video_id}.json` | Raw provider response, unmodified. Written once. |
| `summaries/{video_id}.json` | Self-contained summary artifact — video metadata plus the validated summary object. Rewritten on every summarization. |

The summary artifact is deliberately self-contained (it repeats title, channel, URL, and duration rather than referencing DynamoDB) so a downstream consumer can ingest a single object without a second lookup:

```json
{
  "video_id": "dQw4w9WgXcQ",
  "title": "How Kubernetes Scheduling Actually Works",
  "channel": "Some Channel",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "published_at": "2026-07-01T12:00:00Z",
  "duration_seconds": 3862,
  "summarized_at": "2026-07-22",
  "note_path": "Video Vault/2026/How Kubernetes Scheduling Actually Works-dQw4w9WgXcQ.md",
  "summary": {
    "verdict": "...",
    "tldr": "...",
    "takeaways": ["..."],
    "sections": [{"start_seconds": 1120, "title": "...", "summary": "..."}],
    "tags": ["kubernetes"]
  }
}
```

**Why this exists:** a planned follow-on RAG project needs to ingest these summaries. Reading them out of the private GitHub repo would mean cloning or hammering the GitHub API; reading them from S3 means native event-driven ingestion via S3 notifications, with GitHub left as a pure delivery channel for Obsidian. Adding the write now costs four lines. Retrofitting it later means re-processing the entire back catalog.

The `sections` array doubles as a natural chunk boundary, and each section's `start_seconds` lets a downstream citation deep-link to the exact moment in the source video.

Lifecycle: none. Volume is ~6MB/month, ~70MB/year across both prefixes. Free tier is 5GB; beyond that, well under a cent per month.

Block all public access. Server-side encryption with S3-managed keys.

### Step Functions state machine

Standard workflow. One execution per video, started by **EventBridge Pipes** with the SQS queue as source and `StartExecution` as target. Pipes handles polling and message deletion with no glue code.

**Important consequence:** Pipes deletes the SQS message once the execution *starts*, not once it succeeds. The SQS DLQ therefore only catches failures to start an execution — it does **not** catch workflow failures. Workflow failures are caught by the state machine's `Catch` handler, which writes `status: failed` to DynamoDB. The authoritative failure signals are the `ExecutionsFailed` alarm and DynamoDB, not DLQ depth.

**States:**

1. **FetchTranscript** — Lambda. Calls the configured `TranscriptProvider`, writes the raw response to S3, updates DynamoDB to `transcribed`. Returns `{video_id, transcript_s3_key, has_transcript}`. Retry: 3 attempts, exponential backoff, 2s base, 2.0 multiplier.
2. **HasTranscript?** — Choice state on `has_transcript`.
3. **Summarize** — Lambda. Reads the transcript from S3, calls Bedrock, returns the validated summary object (~2KB, safely under the payload limit). Updates DynamoDB to `summarized`. Retry: 3 attempts on `ThrottlingException` and `ServiceUnavailable`, exponential backoff.
4. **RenderAndCommit** — Lambda. Writes the self-contained summary artifact to `summaries/{video_id}.json`, renders markdown from the summary object, and commits to the vault repo via the GitHub Contents API. Retry: 3 attempts; on 409 conflict, re-read the file SHA and retry. The S3 write happens before the commit so a GitHub outage does not cost the summary.
5. **WriteStubNote** — Lambda. For videos with no captions: commits a note with frontmatter, the link, and `status: no-transcript`. You still get a vault entry saying "this one needs watching."
6. **MarkDone** — DynamoDB SDK integration. Sets `status: done` and `note_path`.
7. **MarkFailed** — Catch target for every state. Sets `status: failed`, records the error, increments `attempts`.

### Summarization

Model `anthropic.claude-sonnet-5` via `AnthropicBedrockMantle(aws_region=...)`.

Request settings:
- `thinking: {"type": "disabled"}` — Sonnet 5 runs adaptive thinking by default when `thinking` is omitted, which is unnecessary spend for summarization.
- `output_config: {"effort": "low"}`
- `output_config.format` with a JSON schema (structured outputs are supported on Bedrock)
- No `temperature` / `top_p` / `top_k` — Sonnet 5 rejects non-default sampling parameters with a 400.

**Output schema:**

```json
{
  "type": "object",
  "properties": {
    "verdict":    { "type": "string" },
    "tldr":       { "type": "string" },
    "takeaways":  { "type": "array", "items": { "type": "string" } },
    "sections": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "start_seconds": { "type": "integer" },
          "title":         { "type": "string" },
          "summary":       { "type": "string" }
        },
        "required": ["start_seconds", "title", "summary"],
        "additionalProperties": false
      }
    },
    "tags": { "type": "array", "items": { "type": "string" } }
  },
  "required": ["verdict", "tldr", "takeaways", "sections", "tags"],
  "additionalProperties": false
}
```

The model emits `start_seconds` as an integer only. The renderer formats the display timestamp and builds the `&t=` URL. The model never writes frontmatter or markdown directly — this keeps formatting deterministic and testable.

### Note format

```markdown
---
title: "How Kubernetes Scheduling Actually Works"
channel: "Some Channel"
url: https://www.youtube.com/watch?v=VIDEO_ID
video_id: VIDEO_ID
duration: "1:04:22"
published: 2026-07-01
saved: 2026-07-22
summarized: 2026-07-22
tags: [video-vault, kubernetes, scheduling]
status: summarized
---

# How Kubernetes Scheduling Actually Works

> **Verdict:** Worth watching 18:40–31:00 for the custom scheduler walkthrough; the rest is standard docs material.

## TL;DR

Three sentences covering what the video argues and who it is for.

## Key takeaways

- Five to eight bullets.

## Sections

- [00:00](https://www.youtube.com/watch?v=VIDEO_ID&t=0) — Intro and framing
- [04:12](https://www.youtube.com/watch?v=VIDEO_ID&t=252) — Default scheduler behavior
- [18:40](https://www.youtube.com/watch?v=VIDEO_ID&t=1120) — Writing a custom scheduler
```

Note path in the vault repo: `Video Vault/{YYYY}/{sanitized-title}-{video_id}.md`. Including the video ID guarantees uniqueness and makes re-commits idempotent.

### Transcript provider seam

```
src/fetch_transcript/providers/
├── base.py          # TranscriptProvider ABC: fetch(video_id) -> Transcript | None
├── api_provider.py  # third-party API, free tier
└── proxy_provider.py  # youtube-transcript-api via residential proxy (future)
```

Selected by an environment variable. Swapping providers is a config change and a redeploy, not a rewrite. At 80 videos against a ~100/month free tier, this seam is load-bearing rather than speculative.

## Failure handling

| Failure | Behavior |
|---|---|
| Video has no captions | `WriteStubNote` — vault entry with link and `status: no-transcript`. Marked done, not failed. |
| Transcript fetch fails | Step Functions retries 3× with backoff, then `Catch` → `MarkFailed` sets `status: failed`. Surfaced by the `ExecutionsFailed` alarm. |
| Bedrock throttled | Retry with backoff on `ThrottlingException`. Bedrock draws the account's shared ITPM/OTPM pool. |
| GitHub commit conflict (409) | Re-read file SHA, retry. |
| SQS send fails after DynamoDB write | Reconcile sweep in the next poll re-enqueues anything stuck in `queued` > 1 hour. |
| Video left in `failed` | Poller re-enqueues `failed` items with `attempts < 3` on each run, giving automatic recovery from transient outages across polls. Beyond 3 attempts it stays failed and requires manual requeue. |
| Pipes cannot start an execution | Message goes to the SQS DLQ. Alarm on DLQ depth covers this narrow case only. |
| Poller fails entirely | Next scheduled run picks up from DynamoDB state. Poller is idempotent. |

## Security

- **Google OAuth consent screen must be set to "In production."** While in "Testing" status, Google expires refresh tokens after 7 days and the pipeline dies silently every week. Publishing does not require verification for a single-user app using non-sensitive scopes, but it does stop the expiry.
- YouTube refresh token and GitHub PAT stored as SSM `SecureString` parameters, KMS-encrypted. Never in environment variables or code.
- GitHub PAT is fine-grained, scoped to the single vault repo, `Contents: read/write` only. Maximum expiry is 1 year — set a calendar reminder to rotate.
- Per-function IAM roles, least privilege. The poller cannot write to S3; the summarizer cannot commit to GitHub.
- Vault repo is private. Private is not encrypted — GitHub can technically read it. Acceptable because the vault holds only video summaries; the personal vault stays local.
- Git history is permanent. Anything committed remains recoverable after deletion.
- GitHub Actions deploys via OIDC role assumption. No long-lived AWS access keys in repository secrets.
- Public code repo must never contain vault content. Separate repositories, enforced by `.gitignore` and by them simply being different repos.

## Observability

CloudWatch alarms:
- Step Functions `ExecutionsFailed` > 0 — the primary failure signal
- DLQ `ApproximateNumberOfMessagesVisible` > 0 — covers only failure to start an execution
- Custom metric `TranscriptCallsThisMonth` > 80 — early warning before hitting the free-tier wall
- Bedrock throttle count > 0

Dashboard: videos processed per day, failure rate, transcript calls this month, estimated Bedrock spend.

Structured JSON logging from all Lambdas with `video_id` as a correlation key.

## Cost

| Item | Monthly |
|---|---|
| Bedrock — 80 videos × ~$0.04 | ~$3.20 |
| Transcript API | $0 (80 of ~100 free tier) |
| Lambda, EventBridge, SQS, DynamoDB, Step Functions | $0 (free tier) |
| S3 (~6MB/month) | ~$0 |
| SSM Parameter Store (standard tier) | $0 |
| CloudWatch alarms and logs | ~$0–0.50 |
| **Total** | **~$3–4** |

Bedrock pricing on AWS is partner-operated and set by AWS; verify against the AWS Bedrock pricing page. Figures above use Anthropic first-party rates as a close proxy.

## Repository layout

**`video-vault`** (public — the portfolio artifact)

```
video-vault/
├── README.md                    # architecture diagram, setup guide, sample note
├── app.py                       # CDK app entrypoint
├── cdk.json
├── infra/                       # CDK stack and constructs
│   ├── pipeline_stack.py
│   └── constructs/
├── src/
│   ├── poller/
│   ├── fetch_transcript/
│   │   └── providers/
│   ├── summarize/
│   ├── render_commit/
│   └── shared/
├── scripts/
│   └── resummarize.py           # re-run summarization over the S3 archive
├── tests/
│   ├── unit/                    # handler logic
│   └── infra/                   # CDK assertions against synthesized template
├── docs/
│   └── superpowers/specs/
└── .github/workflows/deploy.yml # OIDC, no static AWS keys
```

**`my-video-vault`** (private — the Obsidian vault). Recruiters read the first repo and never see the second.

IaC tool: **AWS CDK (Python)**, matching the Lambda runtime for a single-language repo.

Chosen over SAM on portfolio grounds: CDK appears far more often in AWS job requirements, is real typed code rather than YAML templating, and supports **infrastructure unit tests** via `aws-cdk-lib/assertions` — asserting least-privilege IAM, DLQ wiring, and alarm thresholds against the synthesized CloudFormation. SAM has no native equivalent, and an infra test suite is an uncommon and defensible portfolio detail.

Accepted cost: the CDK app is more code than an equivalent SAM template, and `sam local invoke` is a smoother Lambda dev loop. The second is largely recovered — `cdk synth` emits CloudFormation that `sam local invoke -t cdk.out/<stack>.template.json` runs against, so local Lambda testing is preserved.

## Manual setup prerequisites

These cannot be automated and must be done once before first deploy:

1. Create a YouTube playlist named "Video Vault"; record its playlist ID.
2. Create a Google Cloud project, enable YouTube Data API v3, create an OAuth client.
3. **Set the OAuth consent screen to "In production"** (see Security).
4. Run a one-time local script to obtain the refresh token; store it in SSM.
5. Sign up for the transcript API; store the key in SSM.
6. Create the private vault repo, initialize it as an Obsidian vault.
7. Create a fine-grained GitHub PAT scoped to that repo; store it in SSM.
8. Enable Bedrock model access for `anthropic.claude-sonnet-5` in the target region. Verify availability — newer models typically reach `us-east-1` and `us-west-2` first.
9. Install the Obsidian Git community plugin; configure auto-pull interval.

## Forward compatibility with the planned RAG project

A follow-on project will index these summaries alongside class materials (docx, pptx, xlsx, pdf) into a retrieval system. Exactly one accommodation is made for it here — the `summaries/` S3 write described above. Everything else the RAG needs already falls out of decisions made on their own merits:

- The transcript archive gives the RAG full-text chunks for recall the summary drops.
- The `sections` array with `start_seconds` gives chunk boundaries and timestamp-deep-linked citations.
- Both projects live in one AWS account and region, so the RAG reads these buckets via IAM rather than cross-account roles.

If the RAG is built with Terraform rather than CDK, this stack publishes bucket names and ARNs to SSM Parameter Store so Terraform can consume them via `data "aws_ssm_parameter"` — a one-directional dependency with no CloudFormation export coupling.

**Explicitly out of scope now:** no chunking, no embeddings, no vector store, no retrieval. Building any of that before a corpus exists is speculative. This project ships first and produces the corpus.

## Open questions

None blocking.
