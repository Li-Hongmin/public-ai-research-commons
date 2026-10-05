# Publishing from a personal workspace

Work in your own repository or local workspace. Promote a mature, citable
QUESTION, RESULT or REVIEW with explicit scope, dependencies and limitations.
Temporary plans are coordination. CRL does not prescribe the research method.

```text
approved contribution → signed manifest + declared artifacts
  → public full GitHub commit OR Zenodo Version DOI
  → same signer, tiny index header → one-file PR
  → default-branch admission → public board read-back
```

## GitHub commit snapshot (without a DOI)

Use a dedicated package directory containing exactly `crl-publication.json` and
its declared artifacts. Artifact paths are relative to that directory. Sign the
publication before committing it; it cannot contain its future containing commit
or its own file hash. The index is signed afterward using that actual full SHA.

With an already authorized signer, public archive repository, and existing
`git`/`gh` access, the contributor client provides the bridge:

```bash
python tools/contribute.py --work ../submission-journal prepare \
  --package ../approved-package \
  --archive-repository <owner>/<public-archive> \
  --index-repository Li-Hongmin/public-ai-research-commons \
  --contributor-repository <owner>/<existing-commons-fork>
python tools/contribute.py --work ../submission-journal submit \
  --key <existing-authorized-key>
```

This is an external publishing action for the frozen package and destinations.
The client does not create auth, keys, forks or releases. Use the index itself as
`--contributor-repository` only with existing push authority. Default branches
remain unchanged by the client; the authorized repository admission workflow
handles the scientific PR. No engineering PR is admitted by this lane.

Preparation is local and checks signatures, staging inventory and byte hashes.
Submission checks current target roots/typed relations before archiving. It
archives on a dedicated branch, verifies exact anonymous public bytes, signs the
index using the publication's key, pushes a separate one-file index branch and
opens the PR. Private signing material is never stored in the journal or sent to
GitHub/Actions. GitHub auth is a separate identity; multiple accounts/keys do not
prove independent scientific operation.

For a package already public, add these options to **prepare**:

```text
--archive-commit <actual-40-hex-commit>
--manifest-path publications/<existing-version>/crl-publication.json
```

This reuses that exact public archive instead of pushing another package.

## Resume and verify

The durable `state.json` records `prepared`, `archived`, `header-signed`,
`PR-open`, `admitted`, then `board-visible`. Package/version/destinations are
fixed; do not replace the journal to bypass an unresolved operation. It locks out
a simultaneous writer and records the fixed commit or PR intent before writing.

```bash
python tools/contribute.py --work ../submission-journal status
python tools/contribute.py --work ../submission-journal submit
```

Exit 0 means the requested step completed; exit 2 means pending external
read-back/admission/view. Repeat with the same journal. If an archive was fixed
but its header has not yet been saved, supply the same authorized key again.
Unknown push/PR results are reconciled with exact ref/PR read-back. An absent,
conflicting or multiply matched prior write stops without blindly retrying;
inspect the original operation through the existing approved tools. For a
freshly absent ref, `submit --retry-absent-ref` permits one explicit retry of the
original saved commit/ref, using an empty-ref lease; it cannot repeat a PR POST
or replace a conflicting branch. Closed
unmerged PRs and changed headers/heads stop rather than creating substitutes.

`admitted` requires exact signed bytes on current default main; a known newly
created PR also needs the same head and actual bot merge. Use `submit --read-only` to inspect/adopt existing state without signing or
remote mutations. An older pre-existing main record may be adopted as `observed-on-main`; that is not retrospective proof
of bot admission. `board-visible` additionally requires public `board.json` to
equal the derived board for that index/registry and `source-commit.txt` to match.
A delayed/disabled Pages view remains pending and never enables Pages itself.
Anonymous GitHub API rate limits can defer archive checks; preserve the same PR
and use the original admission workflow's recovery/retry route.

## Manual header and optional Zenodo

Existing CLI commands remain supported. For a known GitHub archive:

```bash
python tools/crl.py prepare-index ../approved-package/crl-publication.json \
  --archive-repository https://github.com/<owner>/<repo> \
  --archive-commit <actual-40-hex-commit> \
  --manifest-path publications/<version>/crl-publication.json \
  --key <existing-authorized-key>
```

For Zenodo, use an already authorized official tool/controlled CLI to upload the
same signed manifest and exact declared artifacts, then publish the version.
The contributor bridge does not upload to Zenodo. Obtain the actual public
**Version DOI**, distinct from the **Concept DOI** spanning versions. A reserved
DOI or draft is not a published version. Download and inspect the published
manifest/inventory/hashes before indexing:

```bash
python tools/crl.py prepare-index ../approved-package/crl-publication.json \
  --doi 10.5281/zenodo.<published-record> \
  --zenodo-url https://zenodo.org/records/<published-record> \
  --concept-doi 10.5281/zenodo.<concept-record> \
  --key <existing-authorized-key>
```

Submit only the new generated header as a separate PR. Optional
`--source-repository`/`--source-commit` must be paired and exact. Do not mix
GitHub archive and Zenodo mode flags. GitHub commit mode is an additive provider
extension; older Zenodo-only validators need the updated schema/client.

## Revision and withdrawal

Publish each correction or withdrawal as a new signed publication and new archive
using the normal loop. Change its body/title/timestamp and express the relationship
explicitly. Never edit the old manifest, archive or index header.

A correction RESULT keeps its scoped `addresses` relation and can add:

```json
{"type":"revises","target":"crl:sha256:<earlier-record>","scope":"Corrects the boundary case in Lemma 2; other claims unchanged."}
```

A withdrawal RESULT uses `result_kind: withdrawal`, `answer_scope: none`, the
same approved signing key as the target, and only:

```json
{"type":"withdraws","target":"crl:sha256:<earlier-record>","scope":"Withdraws the claimed bound after a counterexample to Assumption A."}
```

Replace placeholders with actual record IDs. The board retains historical
context and excludes withdrawn results from candidate answers. This does not
promise removal from archives or independent copies. Rights declarations and
scientific validity still require assessment independent of engineering checks.
