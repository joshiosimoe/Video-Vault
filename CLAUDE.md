# Video Vault

Serverless pipeline that summarizes YouTube videos saved to a designated playlist
and commits the notes into a private Obsidian vault repo.

## Read first

- Design spec: `docs/superpowers/specs/2026-07-23-video-vault-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-23-video-vault.md`
- Downstream project brief: `docs/rag/BRIEF.md`

The spec records *why* each decision was made, including rejected alternatives.
Read it before proposing architecture changes — several obvious-looking
suggestions were already considered and ruled out for concrete reasons.

## Hard constraints

- **Total running cost stays under $10/month.** Currently ~$3–4. Any proposal that
  raises this materially needs to be flagged explicitly, with the number, before
  being built.
- **This is a portfolio project.** It demonstrates AWS and AI engineering to
  recruiters. When two approaches are close on merit, the one that reads better in
  an interview wins — but say so out loud rather than smuggling it in.
- Expected volume is ~80 videos/month.

## Conventions

- Python 3.12. AWS CDK (Python) for infrastructure.
- TDD: failing test first, minimal implementation, commit. One task per commit.
- `ruff check . && ruff format --check . && pytest` before every commit.
- Conventional commit prefixes (`feat:`, `fix:`, `test:`, `chore:`, `docs:`).
- Infrastructure is unit-tested via `aws-cdk-lib/assertions` in `tests/infra/`.
  New resources need matching assertions.

## Non-obvious facts that will bite you

- **Bedrock model ID is `anthropic.claude-sonnet-5`** — with the `anthropic.`
  prefix, no date suffix. Requests must set `thinking={"type": "disabled"}` and
  must NOT set `temperature`, `top_p`, or `top_k`; Sonnet 5 returns 400 on
  non-default sampling parameters.
- **YouTube Watch Later is not readable via the Data API.** Google removed `WL`
  access in 2016. This is why the trigger is a user-created playlist. Do not
  "fix" this.
- **Google's OAuth consent screen must be set to "In production."** In "Testing"
  status Google expires refresh tokens after 7 days and the pipeline dies weekly
  with no obvious cause. The `PollerErrors` alarm description says this.
- **EventBridge Pipes deletes the SQS message when the execution *starts*, not
  when it succeeds.** The DLQ therefore only catches start failures. Workflow
  failures surface via the `ExecutionsFailed` alarm and DynamoDB `status`.
- **Step Functions has a 256KB inter-state payload limit.** Long transcripts
  exceed it. States pass S3 keys, never transcript bodies.
- Secrets live only in SSM Parameter Store as `SecureString`. Never in env vars,
  never in code.

## Repository split

- This repo is **public** — code, IaC, docs. It is the portfolio artifact.
- The Obsidian vault is a **separate private repo**. Never commit vault content here.
