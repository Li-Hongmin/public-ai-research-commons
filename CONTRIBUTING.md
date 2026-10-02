# Contributing

The Commons is an index, not a submission venue for research bodies.

## Keep research in your own workspace

Personal GitHub repositories are encouraged but not required. Internal notes,
code, prompts, computations, and manuscripts stay under your control.

Do **not** submit proof text, datasets, papers, notebooks, or research code to this
repository as CRL scientific submissions.

## Publish first, index second

A durable contribution has two steps:

1. publish a signed `crl-publication.json` plus inspectable artifacts to Zenodo;
2. submit one signed discovery header pointing to the exact Zenodo **Version DOI**.

The Commons stores only the second object.

### Sign the publication manifest

```bash
python tools/crl.py keygen --out ~/.crl/identity.key
cp examples/publication.draft.json ../my-publication.draft.json
python tools/crl.py sign-publication ../my-publication.draft.json \
  --key ~/.crl/identity.key --out ../crl-publication.json
python tools/crl.py validate-publication ../crl-publication.json
```

Keep the private key outside every repository.

### Publish to Zenodo

Upload `crl-publication.json` and the artifacts another researcher needs to
inspect the contribution. Choose the publication licence deliberately; the
Commons does not choose one for you.

### Prepare the discovery header

```bash
python tools/crl.py prepare-index ../crl-publication.json \
  --doi 10.5281/zenodo.<record> \
  --zenodo-url https://zenodo.org/records/<record> \
  --source-repository https://github.com/<owner>/<repo> \
  --source-commit <40-hex-commit> \
  --key ~/.crl/identity.key
```

The source flags are optional but, when used, must be supplied together and point
to an exact commit.

The command writes:

```text
index/<2 hex>/<2 hex>/<64 hex>.json
```

Open a PR containing **only that new file**.

## What the signed header means

It declares the CRL record ID, exact Zenodo Version DOI, root problem, creators,
rights statement, declared licence, optional pinned source repository, and
scoped scientific relations. It also explicitly grants `crl-discovery/1.0`,
which applies only to the discovery header.

Indexing does not transfer ownership of the research body to the Commons.

## Scientific relations

- `QUESTION`: exactly one `subproblem-of`.
- `RESULT`: at least one `addresses`; corrections use `revises`.
- `REVIEW`: exactly one `reviews`.

Every relation includes a required `scope`. A reference means no more than that
scope states.

A later REVIEW may criticize public work without the earlier author's permission.
Joint authorship, project-branded papers, reuse permissions, and commercial rights
are separate matters covered by [RIGHTS.md](RIGHTS.md).

## Partial federation

An entry may refer to a valid CRL ID absent from this particular index. That is
allowed. Clients must mark the context as partial rather than interpreting absence
from one index as nonexistence.

## Automatic admission

The optional lane accepts only one new regular JSON file at the exact
content-addressed `index/` path. It never auto-admits code, workflows, policy,
registry changes, or multiple files.

Admission checks structure and signatures using trusted base code. It does not
fetch Zenodo or decide scientific validity.
