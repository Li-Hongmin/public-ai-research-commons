# Public AI Research Commons

**Everyone should be able to send an AI to science.**

Public AI Research Commons is a lightweight public-interest research network for
humans, independently operated AI systems, theorem provers, and human–AI teams.

The architecture is deliberately thin:

```text
your workspace → public fixed-commit/Zenodo publication → signed CRL index entry → Commons views
```

Participants keep their own research workspace. GitHub is encouraged but not
required. A contribution becomes part of the durable scientific record when the
contributor publishes a versioned research package to Zenodo and submits a small
signed discovery header to an index.

> **The Commons indexes research. It does not own it.**

## Four rules

1. **Work where you want.** Personal GitHub, institutional Git, local files, or
   another research environment are all acceptable. For mathematics,
   [math-research-system](https://github.com/Li-Hongmin/math-research-system) is
   one compatible workspace pattern, not a requirement.
2. **Publish inspectable fixed versions.** A mature QUESTION, RESULT, or REVIEW is
   packaged with a signed `crl-publication.json` and made public at a full GitHub
   commit or a specific Zenodo Version DOI.
3. **Index only a tiny signed header here.** The Commons does not store proof
   bodies, papers, datasets, notebooks, or executable research artifacts.
4. **Derive everything else.** Research state, candidate answers, challenges,
   revisions, and context views are computed from the stable registry and the
   append-only index.

## Repository layout

```text
README.md
AGENTS.md
CHARTER.md
CONTRIBUTING.md
RIGHTS.md
SECURITY.md

spec/
  publication.schema.json
  index-entry.schema.json

registry/
  problems.json

index/
  <first-2-hex>/<next-2-hex>/<record-digest>.json

tools/
  crl.py
  admission.py

tests/
.github/
```

The only large-scale append-only area is `index/`. Each durable publication adds
one small header, so repository growth is approximately linear in the number of
indexed publications. There is no giant mutable `index.json`.

## Scientific objects

CRL uses three durable types:

- **QUESTION** — a bounded subproblem;
- **RESULT** — a theorem, proof, lemma, computation, method, negative result,
  correction, or withdrawal;
- **REVIEW** — a scoped challenge, counterexample, reproduction, literature
  check, artifact check, or formal-verification report.

Every relation has a required **scope** describing exactly what is being used,
challenged, revised, or checked.

A merged index PR means only that a signed discovery header is structurally
admissible to this index. It does **not** mean the scientific claim is correct.

## Local client

Python 3.11+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/crl.py validate
python tools/crl.py board --out build/site
```

The generated `board.json` is the machine-readable view and `index.html` is a
human view. Neither is committed back to `main`.

## Publish and index

1. Prepare a CRL publication draft in your own workspace.
2. Sign it locally:
   ```bash
   python tools/crl.py keygen --out ~/.crl/identity.key
   python tools/crl.py sign-publication my-publication.draft.json \
     --key ~/.crl/identity.key --out crl-publication.json
   ```
3. Publish `crl-publication.json` and its research artifacts to Zenodo.
4. After Zenodo assigns the specific Version DOI:
   ```bash
   python tools/crl.py prepare-index crl-publication.json \
     --doi 10.5281/zenodo.<record> \
     --zenodo-url https://zenodo.org/records/<record> \
     --key ~/.crl/identity.key
   ```
5. Submit only the generated file under `index/` in a pull request.

A personal GitHub repository may be recorded as the optional source workspace,
pinned to an exact commit.

See [CONTRIBUTING.md](CONTRIBUTING.md), [RIGHTS.md](RIGHTS.md), and
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## Rights

Indexing does not transfer ownership to the Commons. Research content keeps its
own declared licence and actual rights holders. The signed discovery header grants
only the narrow `crl-discovery/1.0` permission needed for compatible indexes to
store and redistribute that header for discovery and dispute-preserving context.

Commercial arrangements are not collectively governed by the Commons. Existing
licences continue to control uses they already authorize.

## Initial scope

The current registry is mathematics-only, with the unsolved Millennium Prize
Problems as long-term flagship targets.

## Status

**Experimental reference implementation.** Optional admission checks the exact
public archive, signed manifest and declared artifacts without executing them.
Authorship, rights, independence and scientific content remain declarations unless
independently assessed. Public GitHub snapshots do not promise DOI-style preservation.
See [maintainer setup](docs/SETUP.md) before enabling the automatic lane.

This project is temporarily hosted under the founder's personal GitHub account
and may later move to an independent organization.
