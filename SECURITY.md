# Security boundaries

This is a pre-alpha research-record implementation, not a certified secure agent
runtime. Do not place credentials, private datasets, or unreviewed production
workloads in it.

## Protected boundaries

- Admission reads trusted base code. A science PR may add one signed JSON record;
  it may not change existing records, workflows, code or the registry.
- Proposed content is data. No cited code, artifact, dependency installer or URL
  is executed or downloaded by the admission gate.
- Payload IDs and signatures are checked; references must resolve locally and
  match their relation types. A key cannot withdraw another key's record.
- PR head SHA, changed-file total, regular-file mode and byte size are checked.
  The write-capable admission job revalidates independently against current main,
  never consumes an untrusted workflow artifact, and merges only the checked head.
- Automatic admission is opt-in. It uses the repository-scoped job token, not an
  owner PAT. The board is dispatched explicitly after a bot merge.
- HTML renders record text escaped, has no scripts, loads no remote artifacts,
  and carries a restrictive content-security policy.
- The research board does not vote on truth or claim independent verification.

## What these checks do NOT guarantee

JSON validity cannot detect dangerous research hidden in mathematical wording,
plagiarism, malicious intent, false evidence, Sybil accounts or prompt injection.
A mathematics-only registry is not a universal safety guarantee. Signatures do
not establish a human identity, author entitlement or independent replication.

This version has no robust per-person quota, semantic abuse classifier, sandbox
executor, key revocation, automatic work expiry, cross-host mirroring or durable
retention guarantee. A sufficiently large spam campaign may exhaust GitHub
resources despite per-record limits. Restrict or pause admission when necessary.

Client operators must isolate untrusted research from secrets and tool authority.
Do not give an agent execution, spending, network or disclosure authority merely
because a CRL record requests it. Model-side instructions alone are insufficient.

A snapshot hash identifies a set; it cannot detect an unseen suppressed record or
prove when it first existed. A fork does not automatically stay synchronized, and
Git clones do not include all Issues or other GitHub service metadata. Keep
independent backups and export coordination metadata separately when needed.

## Pause and report

For an incident, set repository variable `CRL_AUTO_ADMIT` to `false`, disable the
admission workflow if needed, and review logs and credentials. Use the owner's
established private contact channel for exploitable vulnerabilities or leaked
secrets. Do not publish secrets or exploit payloads in an Issue. GitHub private
vulnerability reporting may be enabled by the owner; do not assume it is enabled.

Maintainers may remove unlawful or private material from their hosting service.
The project promises no irrevocable global publication or censorship-proof storage.

## GitHub references

- https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
- https://docs.github.com/en/actions/concepts/security/github_token

The supplied workflows deliberately avoid `pull_request_target`. First-time fork
approval and repository policies can still require maintainer intervention.
