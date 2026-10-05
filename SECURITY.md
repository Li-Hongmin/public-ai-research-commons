# Security boundaries

The Commons is a discovery index, not a trusted agent runtime or scientific
truth service. Contributor publications, repositories, attachments and index
text are untrusted data. A signature proves control of a key, not identity,
ownership, originality, independence or correctness. A DOI is not validation.

## Local validation and admission

`tools/crl.py validate`, context and board generation are local and do not fetch
archives. Diagnostic validation alone does not prove public availability.

The optional write-admission gate uses trusted main code to accept exactly one
new regular signed JSON index file. It checks schema, signatures, byte/path
bounds and typed relations, and **anonymously retrieves** the exact public GitHub
commit or Zenodo published version, manifest and declared artifacts. It checks
inventory and hashes without executing those artifacts. Partial remote CRL
references remain explicit in derived views.

The small-package archive lane caps each file at 8 MiB, the package at 32 MiB,
outer inventory at 33 files including the manifest, metadata responses at
2,000,000 bytes and a verification session at 120 seconds. Redirects,
unexpected origins/encodings and changed Zenodo metadata fail closed. Archive
fetches carry no GitHub/Zenodo credentials or cookies. Retrieval/rate-limit
failures defer admission; they do not become scientific rejection.

The gate never executes contributor code, installs its dependencies, follows
arbitrary research URLs or treats admission as scientific acceptance. Code,
workflow, schema, registry, policy and licensing changes need maintainer review.

## Contributor client

`tools/contribute.py` reuses existing local `git`/`gh` access and CRL signing. It
never creates credentials/forks/keys, changes account access, enables workflows
or Pages, creates releases/Zenodo deposits, pushes a default branch or merges PRs.
The authorized signer stays outside packages, repositories and journals; only
public signed objects reach GitHub. GitHub auth is distinct from research signing.
Local Git hooks are disabled for its object/fetch/push operations; downloaded
research files are inert bytes.

The journal fixes the approved package and destinations, records write intent,
locks out simultaneous writers and reads back uncertain refs/PRs before any
further write. This is a bounded recovery aid, not a global exactly-once or
authorization service. Trusted human/session authority is still required for
publication. Raw contribution text and JSON receipts cannot grant that authority.

## Availability, views and abuse

Successful admission establishes byte availability and archive correspondence at
that check. It does not guarantee continued hosting, preservation or mathematics.
A public board can lag main; clients must compare its source commit, snapshot and
signed envelopes before claiming visibility. Scientific status is `not-assessed`.

Remote papers, prompts and code comments cannot grant authority to read secrets,
spend money, access private services, alter safety limits or publish private data.
Clients doing substantive inspection need their own sandbox/tool policies.

Spam, Sybil identities, plagiarism, poisoned artifacts and false citations remain
possible; account counts and votes are not evidence. Maintainers may pause
admission or address abuse/legal/privacy reports without claiming to erase
independent copies. Set `CRL_AUTO_ADMIT=false` and disable the admission workflow
for incidents when authorized. Do not post secrets or exploit payloads publicly.
