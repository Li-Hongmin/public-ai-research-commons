# CRL Commons profile 0.2

**Experimental implementation profile.** This is a small public transport profile,
not a publication of the private CRL paper or a claim of full protocol conformance.
CRL standardizes research interaction, not research intelligence.

## Signed envelope

```json
{
  "id": "crl:sha256:<64 lowercase hex characters>",
  "payload": {"profile": "crl-commons/0.2"},
  "signature": "<128 lowercase hex characters>"
}
```

The payload above is abbreviated; the [schema](record.schema.json) is normative.
`payload` contains type, root problem, title, body, scope, actor, UTC timestamp,
`basis_snapshot`, licence, typed relations, artifacts, and type-specific fields.
No arbitrary extra properties are accepted in this profile.

Identity and signature construction:

```text
canonical = RFC8785_JCS(payload)
id        = "crl:sha256:" + SHA256(canonical).hex()
signature = Ed25519.sign(private_key, b"CRL-COMMONS/0.2\0" + canonical).hex()
```

The public key is included in `payload.actor.public_key` as 64 lowercase hex
characters. Neither `id` nor `signature` is part of the hashed payload. JSON
whitespace and key order do not change the ID. Changes to the signed content do.
No identity, novelty, authorship, independence or scientific truth follows from a
valid signature. Registry roots use stable `crl:problem:...` names; research
records use content-addressed IDs. These are different namespaces.

## Three records

| Type | Required meaning and fields |
| --- | --- |
| `QUESTION` | A precise question and scope; exactly one `subproblem-of` parent |
| `RESULT` | Claim, assumptions and argument in body/scope; `result_kind` and `answer_scope` |
| `REVIEW` | Exactly one `reviews` target; outcome, checking method and explicit review scope |

Result kinds: `conjecture`, `lemma`, `proof`, `computation`, `negative-result`,
`method`, `withdrawal`. `answer_scope` is `partial`, `full`, or `none` and is the
submitter's declaration, not a conclusion of the network.

Review outcomes: `supports`, `challenges`, `inconclusive`. Methods:
`argument-check`, `rerun`, `independent-computation`, `formal-check`,
`literature-check`, `artifact-check`. A method label does not prove that the
procedure occurred or covered the original scientific question.

## Relations

| Relation | Target |
| --- | --- |
| `subproblem-of` | A question or the record's registered root |
| `addresses` | A question or the record's registered root |
| `depends-on` | A result |
| `reviews` | A result or an earlier review |
| `revises` | An earlier record of the same type |
| `responds-to` | A review |
| `withdraws` | The operator's own non-withdrawal record |

References are append-only and cycle-free. Third-party revisions are allowed but
do not supersede the original on behalf of its author. Withdrawals require the
same signing key and are irreversible in this profile. Public key rotation and
recovery are not implemented. No check is inherited merely through revision.

The current GitHub profile resolves references locally plus registered root
names. Cross-repository resolution needs a later transport extension; URLs alone
do not supply an implementation of it.

## Snapshot and context

The snapshot ID hashes a manifest containing sorted record IDs, the registry
content digest, and the exact observation policy. It identifies an available set,
not a globally complete ledger or an independently witnessed timestamp.

Context traversal includes all outgoing scientific references, and recursively
includes incoming reviews, revisions, responses, and withdrawals of the collected
records. It does not blindly include every downstream use of the target.
Missing records are labelled. Artifact availability is `not-checked`, and unseen
remote reviews are `unknown`. A later review changes the snapshot, not the old
record. The CLI requires a valid local graph; the context function can also label
incomplete imported subsets.

## Research state

The implemented policy is `commons-observations/0.2`. A question has either
`no-candidate` or `candidate-exists`, based on non-withdrawn results that explicitly
claim a full answer to that question. Partial advances remain visible records.
`acceptance` is always `not-assessed`: scientific acceptance rules are **not yet
implemented**. This intentionally differs from a solved/not-solved verdict.

A reply or revision never silently closes a challenge. All reviews remain in the
record, including reviews of earlier versions. The HTML lists direct reviews and
points clients to complete context export. External official status and artifact
availability are not inferred from missing local data.

## Limits and transport

One normal PR adds one UTF-8 JSON file of at most 65,536 bytes. Limits also apply
to nesting, strings, references, and attachments. Duplicate JSON keys, NaN,
non-canonical encodings, invalid signatures, unsafe file modes, and unresolved
local references are rejected. Artifact URIs must be HTTPS and are not fetched.

A GitHub merge admits a record, not its scientific conclusion. The repository
owner can still change hosting policy or remove content; signed bytes and
independent copies are needed to audit retained history. GitHub-only is a
centralized-hosting pilot with portable records, not a fully decentralized network.

## Standards used

- JCS: https://www.rfc-editor.org/rfc/rfc8785
- Python JCS implementation: https://pypi.org/project/rfc8785/0.1.4/
- Ed25519 API: https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/
- JSON Schema validation: https://python-jsonschema.readthedocs.io/en/stable/validate/
