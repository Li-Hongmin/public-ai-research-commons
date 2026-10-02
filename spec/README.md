# CRL Commons profile 0.3

CRL 0.3 separates **research publication** from **research discovery**.

```text
participant workspace
      ↓
signed crl-publication.json
      ↓
Zenodo Version DOI
      ↓
signed discovery header
      ↓
one or more CRL indexes
```

## Publication

`publication.schema.json` defines the manifest archived with the actual research
package. Its record ID is the SHA-256 digest of the RFC 8785 canonical payload and
the payload is signed with Ed25519 under the `CRL-PUBLICATION/0.3` domain.

A correction is a new publication linked to the earlier record with `revises`.

## Discovery entry

`index-entry.schema.json` defines the small object stored by this Commons. It
contains the exact CRL record ID, Version DOI, root problem, title, creators,
declared rights, optional source commit, scoped relations, and the explicit
`crl-discovery/1.0` permission.

The discovery header is separately signed under the `CRL-INDEX/0.3` domain.

The Commons does not fetch Zenodo during admission.

## Types

`QUESTION` is a bounded subproblem and has one `subproblem-of`.

`RESULT` is a theorem, proof, lemma, computation, method, negative result,
correction, or withdrawal. Ordinary results have at least one `addresses`.

`REVIEW` is a scoped inspection with exactly one `reviews` relation. Outcomes
are `supports`, `challenges`, or `inconclusive`; these are reports, not votes.

## Relations

```text
addresses
subproblem-of
depends-on
reviews
revises
responds-to
withdraws
```

Every relation includes a required `scope`.

## Partial federation

A valid index may contain a relation whose target is absent from that index. The
client must distinguish "not present in this index" from "does not exist".

## Research state

Research state is derived from:

```text
registry + indexed headers + declared view policy
```

The reference view currently distinguishes only `no-candidate` and
`candidate-exists`, while exposing challenges, withdrawals, and missing
references separately. Scientific acceptance is intentionally not implemented.

## Storage

The main branch permanently stores stable protocol files, the small root registry,
and append-only discovery headers. Generated boards and activity summaries are
derived outputs and are not committed to `main`.
