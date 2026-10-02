# Maintainer setup

## Already supplied as code

`checks.yml` tests trusted code, validates current records, and examines a proposed
single record as data. `board.yml` builds a downloadable static board.
`admit.yml` is an optional independently revalidating merge lane.
No new paid service or model API key is required. GitHub limits still apply.

## Pages: one-time repository settings

In **Settings → Pages**, select **GitHub Actions** as the source. Then under
**Settings → Secrets and variables → Actions → Variables**, set
`CRL_PAGES` to `true`. Run **Research board** from the Actions tab once.
Use the deployment URL GitHub returns; do not assume the site is published merely
because these workflow files are present. Until then, download the
`crl-research-board` workflow artifact or build the board locally.

## Optional automatic record admission

Keep this disabled until a valid record, an invalid signature, a workflow-change
PR and a stale-head PR have been tested through GitHub itself, preferably including
an independently operated fork. Local unit tests are not that end-to-end test.

Configure branch/ruleset protections for `main`: disallow force-push/deletion and
require the intended validation check. Protect code, workflows, registry and
schema changes through your maintainer process. The record gate never
intentionally bypasses branch protection, required reviews, or GitHub policy.
Requiring a human review for every PR will also block unattended record merges.

Then set repository variable `CRL_AUTO_ADMIT` to `true`. The optional workflow
revalidates a completed PR check from trusted main, rechecks the live PR, and
merges only one new valid record using its exact head SHA. It does not rely on
an untrusted workflow's claim of success, run its code, or consume its artifacts.
Infrastructure/governance PRs are never auto-admitted.

This calls GitHub's merge endpoint directly; it does not require the separate
repository `allow_auto_merge` feature. The job needs repository-scoped
`contents: write`, `pull-requests: write` and `actions: write`. GitHub settings may
restrict those permissions. No owner PAT should be added to make it work.

After a bot merge, the workflow explicitly dispatches **Research board** because
`GITHUB_TOKEN`-generated pushes do not reliably trigger another workflow. A
missing PR association, changed base, permission failure or first-time fork
approval can require a rerun. The `workflow_dispatch` input accepts a PR number.
This is a small-pilot lane, not a high-throughput queue or a zero-maintenance claim.

## One-time versus recurring responsibilities

Ordinary record validity is checked by code. Scientific disputes are records,
not inbox requests to the founder. New root domains, protocol/security changes,
abuse reports and hosting incidents still need responsible maintainers.

Do not enable an untested write-capable workflow just to eliminate the final
setup step. Do not treat an automatic merge as permission for an agent to execute
someone else's code or disclose private data.
