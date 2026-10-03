# Publishing from a personal workspace

CRL does not prescribe how you do research.

Recommended flow:

```text
personal GitHub/local workspace
        ↓
mature citable contribution
        ↓
signed crl-publication.json
        ↓
Zenodo Version DOI
        ↓
signed discovery header
        ↓
Commons or another index
```

For mathematics, [math-research-system](https://github.com/Li-Hongmin/math-research-system)
is one agent-friendly workspace pattern: stable README/AGENTS boundaries,
permanent mathematical notes, disposable scratch work, and promotion only when a
result changes a mathematical judgment. It is optional.

## When to publish

Publish when a future researcher should reasonably need to cite or inspect the
contribution independently: a precise subproblem, theorem, lemma, counterexample,
corrected formulation, reusable reduction, load-bearing computation, failed
replication, scoped challenge, or independent verification.

Temporary plans and "I am working on this" messages are coordination, not durable
research records.

## Zenodo package

Include `crl-publication.json` plus the artifacts necessary to inspect the
contribution. The manifest records artifact hashes; hashes do not by themselves
prove availability or correctness.

Use the specific Zenodo Version DOI in the index.

If the conclusion changes, publish a new version/object and express the scientific
relationship explicitly with `revises`, `responds-to`, or another scoped
relation. Do not silently replace the earlier result.

Choose the publication licence deliberately. The Commons does not choose it.

## GitHub commit snapshot (without a DOI)

Place the signed `crl-publication.json` and exactly its declared artifacts in one
dedicated directory of an authorized public contributor repository. Artifact paths
are relative to that directory. Commit the approved public selection, then obtain
the full containing SHA. Sign publication before that commit and index afterward:
publication must not include its future containing commit or own file hash.

```bash
python tools/crl.py prepare-index ../crl-publication.json \
  --archive-repository https://github.com/<owner>/<repo> \
  --archive-commit <40-hex-commit> \
  --manifest-path publications/<version>/crl-publication.json \
  --key <existing-authorized-key>
```

Archive fields: provider `github-commit`, repository, commit, exact URL,
manifest_path, and manifest_sha256 (signed envelope JCS SHA256). Artifact hashes
remain byte SHA256; CRL ID/signature domains are unchanged. A commit is a pinned
public snapshot, not a DOI or a guarantee of permanent hosting. Submit only the
new generated header in a separate PR; root registration requires separate review.
Admission treats archive bytes as inert data and scientific validity as not-assessed.
Zenodo Version DOI mode remains compatible; do not mix mode flags.
This is an additive archive-provider extension in this reference implementation:
older v0.3 validators accept the existing Zenodo entries but need this schema/CLI
update to understand GitHub commit entries. Do not claim universal peer support.
