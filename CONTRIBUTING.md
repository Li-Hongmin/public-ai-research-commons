# Contributing

Public AI Research Commons is designed so that ordinary scientific contributions do **not** require a maintainer to judge whether the science is correct.

## Protocol validity vs scientific validity

A contribution may be:

1. **protocol-valid** — correctly structured and admissible to the public record; and
2. **scientifically valid** — supported after scrutiny, challenge, replication, or formal verification.

GitHub admission addresses the first question only.

## Durable research records

The minimal model uses three record types:

- `QUESTION` — a problem or subproblem;
- `RESULT` — a claimed result, proof, lemma, computation, negative result, or revision;
- `REVIEW` — a challenge, counterexample, reproduction, verification, or other inspection of a result.

Revisions should cite the earlier result instead of overwriting it.

## Temporary coordination

Temporary work declarations belong in GitHub Issues rather than the permanent research record.

Examples include checking a lemma, searching for a counterexample, attempting formalization, or independently reproducing a computation.

No work declaration grants ownership of a research direction.

## Scientific disagreement

If you believe a result is wrong, do not ask the maintainer to decide the dispute.

Submit a structured `REVIEW` describing the target, what was checked, the objection or finding, the evidence or artifact, and the scope and limitations of the check.

## Safety

The initial public Commons accepts mathematics-only root problems.

Research artifacts supplied by contributors are untrusted. Admission checks must never execute contributor-provided code merely because it is cited by a research record.

## Governance changes

Changes to the protocol, official root-problem admission, safety scope, or default research-state policies are governance changes rather than ordinary scientific contributions and may require maintainer review.
