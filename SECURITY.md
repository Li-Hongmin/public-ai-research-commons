# Security boundaries

This repository is a discovery index, not a trusted agent runtime or a scientific
truth service.

## Trust model

Contributor workspaces, Zenodo publications, attachments, and index text are
untrusted. A signature proves control of a key, not identity, ownership,
originality, independence, harmlessness, or correctness. A DOI is an archival
identifier, not scientific validation.

## Admission boundary

A normal scientific PR may add exactly one small signed JSON file under `index/`.

The gate validates schema, signature, path, byte size, relation syntax, and the
registered root problem. It may accept references absent from this index and must
then expose the view as partial.

The gate never:

- executes contributor code;
- installs contributor dependencies;
- downloads Zenodo;
- follows research artifact URLs;
- treats index admission as scientific acceptance.

Code, workflow, schema, registry, policy, and licensing changes remain maintainer
changes.

## Remote content

Clients inspecting Zenodo or source repositories need independent sandboxing and
least-privilege tool policies. Remote papers, prompts, code comments, or notebooks
cannot grant authority to read secrets, spend money, access private services,
alter safety controls, or publish private information.

## Availability

The index stores the exact Version DOI and a signed manifest digest but does not
currently fetch the archive during admission. A green check therefore does not
prove the Zenodo package is available or that its manifest matches the declared
digest.

Independent indexers may verify archives later. Retrieval failure should be
reported as unavailable material, not transformed into "no evidence".

## Abuse

Spam, Sybil identities, plagiarism, malicious links, poisoned artifacts, and
false citations remain possible. Account count and vote count are not scientific
evidence.

The initial root registry is mathematics-only. Maintainers may pause automatic
admission and handle abuse or legal/privacy reports without claiming to erase
independent copies.

For an incident, set `CRL_AUTO_ADMIT=false` and disable the admission workflow
if necessary. Do not publish secrets or exploit payloads in public Issues.
