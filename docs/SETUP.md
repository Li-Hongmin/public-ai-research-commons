# Maintainer setup

The reference implementation runs on GitHub Actions. No API server, database,
model API, or GPU is required.

`checks.yml` tests trusted code, validates the local index, and treats a proposed
scientific header as data. `board.yml` builds a static board from
`registry/problems.json + index/`. `admit.yml` is an optional write-capable
lane and should remain disabled until end-to-end fork testing is complete.

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

The lane revalidates only one new `index/<hash>.json` file against trusted main
and merges the exact checked head. It does not fetch Zenodo or verify scientific
content. Governance and infrastructure PRs never use this lane.

Do not add an owner PAT merely to bypass GitHub permission settings.

## Maintainer responsibilities

Ordinary scientific disagreement belongs in CRL publications, not the founder's
inbox. Maintainers remain responsible for root-domain admission, protocol and
security changes, abuse/legal reports, and hosting incidents.

Independent indexes and mirrors are encouraged.
