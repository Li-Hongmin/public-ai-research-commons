# Contributing

The Commons stores discovery headers. Keep research bodies and exploratory work
in your own workspace; do not submit papers, proof code, datasets or notebooks
as scientific index PRs.

## Prepare an inspectable contribution

Read [RIGHTS.md](RIGHTS.md), the registered root in `registry/problems.json`, and
current board/index context. Before extending an entry, use:

```bash
python tools/crl.py context crl:sha256:<record>
```

Choose a bounded QUESTION, RESULT or REVIEW. Cite exact versions and the parts
actually used, including challenges and limitations. Record actual human/AI
contributions, author consent where needed, rights holders and deliberate
licences. A signature and index check do not establish these declarations.

Edit a publication draft outside staging, then sign with an existing authorized
identity whose private key stays outside every repository and package:

```bash
python tools/crl.py sign-publication ../publication.draft.json \
  --key <existing-authorized-key> \
  --out ../approved-package/crl-publication.json
python tools/crl.py validate-publication ../approved-package/crl-publication.json
```

Staging must contain exactly this manifest and its declared artifact paths.
Artifact hashes are byte SHA256. The signed manifest digest is JCS SHA256.
Missing identity, publication authority, author consent or reuse permission must
be resolved through the contributor's trusted human/account workflow; the client
cannot grant them. Missing registered roots require a separate registry review.
Preparation can continue locally while those prerequisites are unresolved.

## Publish first, index second

Use either a public full GitHub commit or a published Zenodo Version DOI. Zenodo
is optional. The [publishing guide](docs/PUBLISHING.md) contains the shortest
GitHub client commands and manual/Zenodo alternatives.

`tools/contribute.py` bridges existing `git`, `gh`, `crl.py` and the bounded public
archive verifier. Use your already authorized public archive repository and an
existing public fork of the index (or the index itself when already authorized).
It creates dedicated branches, signs with the same publication key and opens a
PR containing only `index/<2 hex>/<2 hex>/<64 hex>.json`. It never pushes a default
branch, creates accounts/forks/keys, enables admission/Pages or manually merges.
GitHub credentials control repository operations; the CRL key signs research.
The generic Git commit author is transport metadata, not research authorship.

The signed header declares an exact archive, root, scoped relations, creators,
rights and the narrow `crl-discovery/1.0` permission for the header. It does not
transfer research ownership. GitHub commit hosting does not promise DOI-style
preservation.

## Relations and changes

- QUESTION: exactly one `subproblem-of`.
- RESULT: at least one `addresses`; a correction can add `revises`.
- REVIEW: exactly one `reviews`.
- Withdrawal: RESULT with `result_kind: withdrawal`, `answer_scope: none`, and
  exactly one `withdraws` relation to the same signer's earlier publication.

Every relation needs a precise `scope`. A later REVIEW can criticize public work
without that author's permission. Joint authorship and reuse rights are separate.
[Revision and withdrawal examples](docs/PUBLISHING.md#revision-and-withdrawal)
show append-only updates; old objects are never silently replaced.

References to valid CRL IDs absent from this index are allowed; views expose
partial context rather than treating absence as nonexistence.

## Admission and read-back

The optional automatic lane accepts one new regular JSON index file. It never
auto-admits code, workflows, registry, policy or multiple files. Trusted base code
checks schema/signatures/typed relations and anonymously fetches the bounded exact
public archive and declared artifacts as data. It never executes artifacts or
assesses scientific truth.

A PR opening or green diagnostic check is not admission. Confirm the exact header
on the pinned default branch; public board/source/snapshot agreement is a separate
step and may lag. Scientific validity remains `not-assessed`. Follow
[maintainer setup](docs/SETUP.md) before enabling the lane; local mocked tests do
not establish an independently operated contributor or production fork E2E.
