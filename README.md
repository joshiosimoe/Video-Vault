# Video Vault

Automatically summarizes YouTube videos saved to a playlist and files them into
an Obsidian vault as skimmable, timestamped notes.

Saving videos "for later" does not work when later never arrives. This turns a
saved video into a note you can skim in ninety seconds — with a verdict on
whether it is worth watching at all, and clickable timestamps to the parts that
are.

## How it works

See [docs/architecture.md](docs/architecture.md) for the full diagram.

A scheduled Lambda polls a YouTube playlist, diffs it against DynamoDB, and
enqueues new videos. EventBridge Pipes starts one Step Functions execution per
video: fetch the transcript into S3, summarize it with Claude Sonnet 5 on
Bedrock using structured outputs, render markdown, and commit to a private
GitHub repo that Obsidian syncs.

## Sample note

```markdown
---
title: "How Kubernetes Scheduling Actually Works"
channel: "Some Channel"
url: https://www.youtube.com/watch?v=VIDEO_ID
duration: "1:04:22"
tags: [video-vault, kubernetes, scheduling]
status: summarized
---

> **Verdict:** Worth watching 18:40–31:00 for the custom scheduler
> walkthrough; the rest is standard docs material.

## TL;DR
...

## Sections
- [18:40](https://www.youtube.com/watch?v=VIDEO_ID&t=1120) — Writing a custom scheduler
```

## Stack

Python 3.12 · AWS CDK · Lambda · Step Functions · DynamoDB · S3 · SQS ·
EventBridge Pipes · SSM Parameter Store · Amazon Bedrock · GitHub Actions (OIDC)

## Testing

```bash
pytest tests/unit    # handler and business logic
pytest tests/infra   # CDK assertions against the synthesized template
```

Infrastructure is unit-tested: the suite asserts least-privilege IAM, DLQ
wiring, alarm thresholds, and that every Lambda has its own role.

## Cost

Roughly $3–4/month at 80 videos, essentially all Bedrock inference. Every other
service stays inside the AWS free tier.

## Setup

1. Create a YouTube playlist; note its ID.
2. Create a Google Cloud project, enable YouTube Data API v3, create an OAuth client.
3. **Set the OAuth consent screen to "In production."** In "Testing" status Google
   expires refresh tokens after 7 days and the pipeline dies weekly.
4. Obtain a refresh token; store it in SSM at `/video-vault/google-refresh-token`.
5. Store the client ID and secret at `/video-vault/google-client-id` and
   `/video-vault/google-client-secret`.
6. Sign up for a transcript API; store the key at `/video-vault/transcript-api-key`.
7. Create the private vault repo and initialize it as an Obsidian vault.
8. Create a fine-grained GitHub PAT scoped to that repo with `Contents: read/write`;
   store it at `/video-vault/github-token`.
9. Enable Bedrock model access for `anthropic.claude-sonnet-5` in your region.
10. Deploy: `npx aws-cdk@2 deploy -c playlist_id=... -c vault_repo_owner=... -c vault_repo_name=... -c bedrock_region=...`
11. Install the Obsidian Git plugin and configure auto-pull.

All parameters must be created as `SecureString`.

### Continuous deployment (GitHub Actions)

`.github/workflows/deploy.yml` deploys the stack on every push to `main` via
OIDC, with no long-lived AWS credentials stored in the repo. To wire it up:

1. In IAM, create an OpenID Connect identity provider for
   `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`), unless
   the account already has one.
2. Create an IAM role that trusts that provider, with a trust policy condition
   scoping `token.actions.githubusercontent.com:sub` to this repository (e.g.
   `repo:<owner>/<repo>:ref:refs/heads/main`), and permissions to deploy the stack.
3. In the repo's Settings → Secrets and variables → Actions → Variables, add
   `AWS_DEPLOY_ROLE_ARN` (the role's ARN) and `AWS_REGION` (the deploy region).

Without both variables set, the deploy workflow fails at the credentials step.

## License

MIT
