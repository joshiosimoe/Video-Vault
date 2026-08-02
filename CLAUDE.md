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

- **The model is configuration, not a constant.** `BEDROCK_MODEL_ID` (repo
  variable → CDK context → Lambda env) currently defaults to
  `us.anthropic.claude-sonnet-4-6`. Requests must set
  `thinking={"type": "disabled"}` and must NOT set `temperature`, `top_p`, or
  `top_k` — these models return 400 on non-default sampling parameters.
- **This account is not entitled to Sonnet 5, despite AWS saying it is.**
  `get-foundation-model-availability` reports `AUTHORIZED` / `AVAILABLE` on all
  four fields while the inference endpoint returns *"anthropic.claude-sonnet-5 is
  not available for this account"* — verified for 2.5+ hours after accepting the
  model agreement, on both the classic and Mantle endpoints. Sonnet 4.6 works on
  the same account and credentials. Switching back is a `BEDROCK_MODEL_ID` change
  and a redeploy; do not change code for it.
- **Use the classic `AnthropicBedrock` client, not `AnthropicBedrockMantle`.**
  Mantle serves *only* Sonnet 5 (it 404s on 4.6) and is not served in `us-east-2`
  at all. Classic serves both models, which is why the swap above is config-only.
  Note the two clients need different IAM: classic wants `bedrock:InvokeModel`,
  Mantle wants `bedrock-mantle:CreateInference` on a `project/default` ARN.
- **A `us.`-prefixed model ID is a cross-region inference profile.** It needs
  `bedrock:InvokeModel` on the underlying foundation-model ARN in *every* member
  region (`us-east-1`, `us-east-2`, `us-west-2`), not just on the profile ARN —
  Bedrock routes across them and a profile-only grant fails intermittently.
- **Bedrock's Anthropic use-case form is per-region, and gates every Anthropic
  model.** Without it every call returns 404 *"Model use case details have not
  been submitted"*. Submitted for `us-east-1`; `us-east-2` is still ungated. One
  call can slip through before the gate applies, so never trust a single success.
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
