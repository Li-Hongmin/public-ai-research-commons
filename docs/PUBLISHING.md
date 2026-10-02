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
