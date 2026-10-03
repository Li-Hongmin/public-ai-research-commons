# Maintainer setup

The reference implementation runs on GitHub Actions. No API server, database,
model API, or GPU is required.

`checks.yml` tests trusted code, validates the local index, and treats a proposed
scientific header as data. `board.yml` builds a static board from
`registry/problems.json + index/`. `admit.yml` is an optional write-capable
lane. Test in a disposable fork before enabling it on a live Commons; local
mocks do not establish a production end-to-end result.

## Pages

In **Settings → Pages**, choose **GitHub Actions**. Under
**Settings → Secrets and variables → Actions → Variables**, set:

```text
CRL_PAGES=true
```

Run **Research board** once. The board is derived output and is not committed to
`main`.

## Optional automatic index admission

Before enabling, test a valid forked index entry, invalid signature, wrong path,
stale head, multi-file PR, and code/workflow/schema change.

Then set:

```text
CRL_AUTO_ADMIT=true
```

The lane revalidates one new regular non-executable index JSON against trusted
main, verifies the exact public archive and merges the checked head. It never
decides scientific validity. Governance/infrastructure PRs require ordinary review.

### Trusted execution and recovery

The `pull_request_target` workflow and checkout come from trusted main. No
contributor head, code, workflow or workflow artifact is checked out or executed.
The admission job uses only ephemeral `GITHUB_TOKEN` contents/pull-requests write;
no owner PAT or repository auto-merge option is required. Honor repository rules.

Archive checks use anonymous HTTPS reads with no credential forwarding or
redirects. Caps: 2 MB metadata per response, 8 MiB per file, 32 MiB package, 33
files including manifest, 120 seconds. GitHub requires a public exact 40hex commit,
regular Git blobs, dedicated-directory inventory, signed manifest JCS hash and
all artifact byte hashes. Zenodo additionally checks public publication and
Version/Concept DOI semantics. Larger/unsupported packages need separate review.

Main is checked immediately before merging; afterward the exact admitted blob is
read at a pinned main commit. The merge API fixes PR head but lacks an expected-base
parameter: serialized admission jobs reduce races, but maintainers can still write
concurrently. Honor branch rules and inspect failures. A timed-out merge is read
back without repeating PUT. A matching already merged PR can be rerun read-only.

Hourly recovery rotates at most 20 inspections over up to 100 open PRs, merges at
most one, then relies on a fresh checkout for the next run. This covers missed
events/stale bases; more than 100 open PRs requires triage. Scheduling, queueing
and hosting failures can delay admission.

The board listens to completed `CRL index admission` runs even on failure after
a merge, reads current trusted main and deploys when Pages is enabled. This avoids
depending on a bot merge's suppressed push event or a separate fallible dispatch.
Admission needs no actions-write permission. Public `source-commit.txt` names the
actual built commit; compare it and `board.json` with main. Artifact upload alone
does not demonstrate public deployment.

Pages build needs contents-read; deploy needs pages-write and id-token-write in
`github-pages`. Creating Pages with `build_type=workflow`, setting CRL_PAGES and
CRL_AUTO_ADMIT, and confirming Actions policy are one-time owner-authorized admin
operations. All scientific/board acceptance remains `not-assessed`.

Do not add an owner PAT merely to bypass GitHub permission settings.

## Maintainer responsibilities

Ordinary scientific disagreement belongs in CRL publications, not the founder's
inbox. Maintainers remain responsible for root-domain admission, protocol and
security changes, abuse/legal reports, and hosting incidents.

Independent indexes and mirrors are encouraged.
