# RAG Project — Handoff Brief

**Status:** not started. Video Vault ships first and produces the corpus.
**Written:** 2026-07-23, at the end of the Video Vault design session.

> **To the agent picking this up:** this brief is an *input to a design
> conversation*, not a spec. Sections marked **DECIDED** are settled — treat
> them as constraints and don't relitigate them without a concrete reason.
> Sections marked **OPEN** are deliberately unresolved: interview the user about
> them before writing any plan. Do not fill them in yourself. The user wants to
> be consulted on design, not handed a finished blueprint.
>
> Start with the `superpowers:brainstorming` skill. This brief is background
> reading, not a substitute for the interview.

---

## 1. What this project is

A retrieval system over two corpora:

1. **YouTube video summaries** produced by Video Vault (see §3 for the exact shape).
2. **Class materials** — docx, pptx, xlsx, pdf.

The goal is asking questions across a semester's worth of study material and
getting answers with citations back to the source — including, for videos,
a deep link to the exact timestamp.

## 2. Inherited constraints — DECIDED

- **Budget: under $10/month for both projects combined.** Video Vault already
  uses ~$3–4. The realistic ceiling for the RAG is therefore ~$5/month. This is
  the single hardest constraint and it eliminates most published AWS RAG
  architectures — see §5.
- **This is a portfolio project.** Both projects exist partly to demonstrate AWS
  and AI engineering to recruiters. A demoable URL is worth real money here.
- **Corpus is small.** ~1,000 video notes per year plus a few hundred class
  documents. Estimated 100k–200k chunks total. This is tiny by vector-database
  standards and it should drive every sizing decision. Do not design for scale
  that will not arrive.

## 3. Interface contract — DECIDED

Video Vault writes a self-contained artifact per video to S3. The bucket name is
published to SSM at **`/video-vault/content-bucket`** — read it with
`data "aws_ssm_parameter"` (Terraform) or an SDK call. Do not hardcode it, and do
not create a CloudFormation export dependency between the stacks.

Two prefixes:

| Key | Contents |
|---|---|
| `transcripts/{video_id}.json` | Raw transcript. Full text, for recall on details the summary drops. |
| `summaries/{video_id}.json` | The artifact below. |

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
    "sections": [
      {"start_seconds": 1120, "title": "Custom scheduler", "summary": "..."}
    ],
    "tags": ["kubernetes"]
  }
}
```

Two properties worth exploiting:

- **The artifact is self-contained by design.** It repeats title, channel, URL,
  and duration so an ingester processes one S3 object with no DynamoDB lookup.
- **`summary.sections` is a natural chunk boundary**, and each `start_seconds`
  lets a citation deep-link into the source video
  (`{url}&t={start_seconds}`). Most RAG demos cannot cite that precisely. Use it.

Both projects live in **one AWS account and region**, so this is IAM access,
not cross-account.

## 4. Build order — DECIDED

Video Vault first, RAG second. Reasons: the RAG needs a corpus to be testable at
all; Video Vault has a clear done state while RAG scope is open-ended; and by the
time this starts there will be months of real notes to tune retrieval against.

If Video Vault is not yet deployed and producing notes, say so and stop.

## 5. Cost analysis already done — DECIDED (the traps)

**Do not use OpenSearch Serverless.** It is the default in most Bedrock Knowledge
Bases tutorials and its minimum billable capacity runs to the **hundreds of dollars
per month while idle** — 50–100× the entire budget, for a corpus that would fit in
RAM. Any tutorial that starts there is written for enterprise scale.

**Aurora Serverless v2 with pgvector at a 0.5 ACU floor is ~$43/month** — also over
budget. A scale-to-zero configuration brings idle cost down to roughly storage,
which may be viable; verify current behavior and resume latency before committing.

Embeddings are a rounding error. Bedrock Titan Embed v2 is roughly $0.02 per
million tokens, so embedding the entire corpus once costs a couple of dollars.
**The vector store is the only real cost driver.** Size that decision first;
everything else is noise.

## 6. Hosting analysis already done — RECOMMENDED, not decided

The prior session recommended **AWS over local**, primarily because a local RAG is
nearly undemoable — there is no URL to send a recruiter, and the machine must be
on. Cost at this scale is roughly a wash (~$1–3/month either way).

The specific pattern suggested was: **build the index in batch, store it in S3,
load it into Lambda memory at query time.** ~200k chunks at 1024 dimensions is
about 800MB, which fits inside Lambda's 10GB ceiling. Cold start is a few seconds,
which is fine for a personal tool queried a handful of times a day, and idle cost
is effectively zero.

**Confirm this with the user before building on it.** It was reasoned from
estimates, not measured, and the corpus size assumption should be re-checked
against reality once Video Vault has been running.

**One flag raised and not resolved:** class materials may be covered by course or
institutional policy on redistribution. Storing lecture slides in a private S3
bucket is normally fine, but this was never confirmed. Ask. If it turns out cloud
storage is not acceptable, there is a clean split — run ingestion locally and store
only embeddings plus the user's own notes in AWS, since vectors are not reversible
to source text.

## 7. IaC — RECOMMENDED, not decided

Video Vault uses **AWS CDK (Python)**, chosen over SAM because CDK has real Lambda
bundling, typed Step Functions constructs, and in-memory infrastructure unit tests.

The prior session recommended **Terraform for this project** instead, so the
portfolio covers both tools, each used where it is genuinely the better fit —
Terraform suits a stack that is mostly managed data services rather than bundled
Lambdas. The interview value is in being able to explain *why* each was chosen.

Worth checking: Terraform's AWS provider sometimes lags on newly released services.
If this design depends on something recent, verify provider support before
committing to Terraform.

## 8. OPEN — interview the user on these

Do not decide these unilaterally.

1. **Vector store.** S3-index-in-Lambda, Aurora pgvector scaled to zero, LanceDB,
   or something else. Driven by the budget in §2 and the traps in §5.
2. **Chunking strategy.** Video sections are pre-chunked (§3). Class documents are
   not — and pptx, xlsx, and pdf each chunk differently. xlsx in particular may not
   belong in a text RAG at all.
3. **Whether transcripts get embedded, or only summaries.** Affects corpus size,
   cost, and recall. Real tradeoff, no obvious answer.
4. **Query interface.** Web UI, CLI, Obsidian plugin, Slack, API only. This
   determines the demoability the whole hosting argument in §6 rests on.
5. **Ingestion trigger for class files.** S3 upload, a watched folder, manual CLI.
6. **Whether Video Vault notes and class materials share one index or stay
   separate.** Affects retrieval quality and filtering.
7. **Evaluation.** How does the user judge whether retrieval is any good? Worth
   settling before building, not after.
8. **Generation model.** Video Vault uses Sonnet 5 on Bedrock. Reasonable default,
   but confirm — a cheaper model may suffice for grounded answering.

## 9. How the user prefers to work

Observed over the Video Vault design session:

- Asks for explicit tradeoff analysis and a recommendation — not a menu of options
  with no opinion. Lead with the recommendation, then justify it.
- Wants cost stated in real numbers, not adjectives. Free-tier limits and where
  they run out matter.
- Wants resume and portfolio impact called out explicitly when it affects a choice.
- Pushes back and asks follow-up questions on design decisions. Expect to defend
  reasoning; expect to change your answer when the priority shifts. (The SAM → CDK
  switch happened exactly this way.)
- Prefers free or near-free options, and wants the case made when paying is worth it.
