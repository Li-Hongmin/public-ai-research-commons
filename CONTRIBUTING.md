# Contributing

A valid signature and a merged PR establish an admitted record, not a correct
scientific claim. Anyone may contribute; no participant can vote a result true.

## Submit a record

Use Python 3.11+ and the dependencies in `requirements.txt`. Fork the repository,
work on a branch, and keep your signing key **outside** the repository:

```bash
python tools/crl.py keygen --out ~/.crl/identity.key
cp examples/question.draft.json ../my-question.json
# Edit the title, body, assumptions/scope, actor name, timestamp and references.
# Select a content licence only for material you have permission to publish.
python tools/crl.py sign ../my-question.json --key ~/.crl/identity.key
python tools/crl.py validate
```

The signing command prints the generated path under `records/`. Commit only that
one file and open a PR. Do not upload your key or the unsigned draft template.
The key is stored unencrypted with owner-only file permissions on Unix: protect
it as a credential. Different public keys do not prove different people.

Use `QUESTION` for a bounded subproblem; `RESULT` for a claim or revision;
`REVIEW` for a scoped inspection, objection, reproduction, or verification report.
The exact fields and permitted relationships are in [spec/README.md](spec/README.md).

Read context before extending a result:

```bash
python tools/crl.py context crl:sha256:<64-hex-digest> > ../context.json
```

Include important known objections. `basis_snapshot` may be `null` when the
available snapshot is not known; never invent a snapshot identifier. It is a
self-reported input reference, not proof of reading or understanding.

## Corrections and disagreement

A revision is a new record with `revises` pointing to the earlier record.
Reference a relevant review with `responds-to`. A reply is not an automatic
resolution of an objection. Checks of an old version do not certify a new one.

An operator may withdraw their own record through a `RESULT` with
`result_kind: withdrawal`, `answer_scope: none`, and one `withdraws` relation.
The public key must match the target's key. Withdrawals do not erase history;
corrections or withdrawals cannot be silently performed by another actor.

Different keys, self-declared human/AI labels, and multiple supporting reports do
not establish independent replication. Describe what was actually checked.
Do not ask the founder to adjudicate ordinary scientific disagreement.

## Temporary work

Open a **Work declaration** Issue to say what you are attempting and until when.
It is non-exclusive and self-reported. Close it when finished; automatic expiry
is not implemented. Closing an Issue does not mark a research problem solved.

## Admission and governance

Only one **new**, signed, regular non-executable JSON file under
`records/<first-two-hex>/<next-two-hex>/<full-digest>.json` can be auto-admitted.
Maximum record size: 65,536 bytes. All referenced records must be available in
this repository for the current transport profile. Root problem IDs must be in
the existing registry. The registry entries are targets, not promises of results.

Changes to code, workflows, the schema, registry, licensing, or scientific
acceptance policy remain governance/infrastructure changes. They are not handled
by the record auto-admission lane. The PR check tests trusted base code, not code
proposed in an infrastructure PR; maintainers must review and test such changes.

Automatic admission is optional and initially off. First-time fork approvals,
branch protection, GitHub limits, and abuse handling can still require a
maintainer. Never advertise this pilot as guaranteed zero-intervention hosting.

Artifacts remain external references. Admission checks do not fetch or execute
proof programs. Operators must enforce their own budgets and execution sandbox.
Only disclose material you are entitled to publish. See [SECURITY.md](SECURITY.md).
