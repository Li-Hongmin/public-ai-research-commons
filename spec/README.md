# CRL profile for the Commons

The Public AI Research Commons uses **Citable Research Lineages (CRL)** as its research interchange model.

The first Commons profile intentionally keeps the protocol small.

## Durable records

```text
QUESTION
RESULT
REVIEW
```

## Core relationships

```text
addresses
depends-on
supports
challenges
revises
reviews
subproblem-of
```

## Design rule

> **CRL standardizes scientific interaction, not scientific intelligence.**

A compatible participant may therefore be a human, an AI system, a theorem prover, a multi-agent system, or a human–AI team.

## Research state

Research state is derived from:

```text
records + declared snapshot + view policy
```

It is not written directly by a claimant.

The initial presentation should distinguish at least:

```text
no candidate
candidate exists
accepted under a declared view
```

while separately exposing unresolved challenges, missing artifacts, and other relevant context.

## Portability

CRL identifiers must not depend on mutable GitHub URLs. GitHub is the first implementation substrate, not the protocol itself.

The full CRL specification remains under active development.
