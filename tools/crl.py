"""CRL Commons 0.3: Zenodo-backed publications and a minimal signed discovery index.

The Commons stores discovery headers, not research bodies. This module never downloads
Zenodo files, executes research artifacts, or decides scientific truth.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
MAX_INDEX_BYTES = 32768
MAX_PUBLICATION_BYTES = 131072
INDEX_DOMAIN = b"CRL-INDEX/0.3\x00"
PUBLICATION_DOMAIN = b"CRL-PUBLICATION/0.3\x00"
RID = re.compile(r"crl:sha256:[0-9a-f]{64}\Z")
POLICY = {
    "id": "commons-observations/0.3",
    "acceptance": "not-implemented",
    "votes_are_evidence": False,
    "archive_availability": "not-checked",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _pairs(pairs: list) -> dict:
    out = {}
    for k, v in pairs:
        require(k not in out, "duplicate JSON key")
        out[k] = v
    return out


def _constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def loads(raw: bytes, limit: int) -> Any:
    require(len(raw) <= limit, "input exceeds size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        stack = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            require(depth <= 24, "JSON nesting too deep")
            if isinstance(item, dict):
                stack.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                stack.extend((v, depth + 1) for v in item)
        return value
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc


def read_json(path: Path, limit: int) -> Any:
    require(not path.is_symlink(), "symlinks are not accepted")
    with path.open("rb") as f:
        return loads(f.read(limit + 1), limit)


def canonical(value: Any) -> bytes:
    return rfc8785.dumps(value)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def index_path(record_id: str) -> Path:
    require(bool(RID.fullmatch(record_id)), "invalid CRL record identifier")
    h = record_id.rsplit(":", 1)[1]
    return Path(h[:2], h[2:4], h + ".json")


def _validator(name: str) -> Draft202012Validator:
    schema = read_json(ROOT / "spec" / name, MAX_PUBLICATION_BYTES)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


INDEX_VALIDATOR = _validator("index-entry.schema.json")
PUBLICATION_VALIDATOR = _validator("publication.schema.json")


def _private_key(path: Path) -> Ed25519PrivateKey:
    raw = bytes.fromhex(path.read_text(encoding="ascii").strip())
    require(len(raw) == 32, "private key must contain 32 raw bytes as hex")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _sign_payload(payload: dict, key: Ed25519PrivateKey, domain: bytes) -> tuple[dict, bytes]:
    payload = copy.deepcopy(payload)
    public = key.public_key().public_bytes_raw().hex()
    actor = payload["actor"]
    old = actor.get("public_key")
    require(not old or old == public, "draft contains a different signing key")
    actor["public_key"] = public
    raw = canonical(payload)
    return payload, key.sign(domain + raw)


def _verify(payload: dict, signature: str, domain: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(payload["actor"]["public_key"])).verify(
            bytes.fromhex(signature), domain + canonical(payload)
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("invalid signature") from exc


def sign_publication(payload: dict, key: Ed25519PrivateKey) -> dict:
    payload, signature = _sign_payload(payload, key, PUBLICATION_DOMAIN)
    rid = "crl:sha256:" + hashlib.sha256(canonical(payload)).hexdigest()
    return {"id": rid, "payload": payload, "signature": signature.hex()}


def _validate_relations(kind: str, relations: list[dict], payload: dict) -> None:
    types = [r["type"] for r in relations]
    if kind == "QUESTION":
        require(types.count("subproblem-of") == 1, "QUESTION needs exactly one parent")
        require(set(types) <= {"subproblem-of", "depends-on", "revises"},
                "invalid QUESTION relation")
    elif kind == "REVIEW":
        require(types.count("reviews") == 1, "REVIEW needs exactly one target")
        require(set(types) <= {"reviews", "depends-on", "responds-to", "revises"},
                "invalid REVIEW relation")
    elif payload.get("result_kind") == "withdrawal":
        require(types == ["withdraws"] and payload.get("answer_scope") == "none",
                "withdrawal needs one target and no answer")
    else:
        require(types.count("addresses") >= 1, "RESULT needs a question target")
        require(set(types) <= {"addresses", "depends-on", "revises", "responds-to"},
                "invalid RESULT relation")
    require(types.count("revises") <= 1, "at most one revision predecessor")


def validate_publication(publication: dict) -> None:
    PUBLICATION_VALIDATOR.validate(publication)
    require(len(canonical(publication)) <= MAX_PUBLICATION_BYTES, "publication manifest too large")
    payload = publication["payload"]
    raw = canonical(payload)
    require(publication["id"] == "crl:sha256:" + hashlib.sha256(raw).hexdigest(),
            "publication content hash mismatch")
    _verify(payload, publication["signature"], PUBLICATION_DOMAIN)
    _validate_relations(payload["type"], payload["relations"], payload)


def sign_index(payload: dict, key: Ed25519PrivateKey) -> dict:
    payload, signature = _sign_payload(payload, key, INDEX_DOMAIN)
    return {"payload": payload, "signature": signature.hex()}


def validate_index(entry: dict) -> None:
    INDEX_VALIDATOR.validate(entry)
    require(len(canonical(entry)) <= MAX_INDEX_BYTES, "index entry too large")
    payload = entry["payload"]
    _verify(payload, entry["signature"], INDEX_DOMAIN)
    archive = payload["archive"]
    if archive["provider"] == "zenodo":
        suffix = archive["doi"].rsplit(".", 1)[-1]
        require(archive["url"] == "https://zenodo.org/records/" + suffix,
                "Zenodo DOI and record URL disagree")
    else:
        require(archive["url"] == archive["repository"] + "/tree/" + archive["commit"],
                "GitHub repository/commit URL disagree")
        path = archive["manifest_path"]
        require("\\" not in path and all(p not in {"", ".", ".."} for p in path.split("/"))
                and not any(ord(c) < 32 for c in path), "unsafe GitHub manifest path")
    _validate_relations(payload["record_type"], payload["relations"], payload)


def load_registry(path: Path | None = None) -> dict[str, dict]:
    path = path or ROOT / "registry" / "problems.json"
    data = read_json(path, MAX_INDEX_BYTES)
    roots = {
        problem["id"]: problem
        for program in data.get("programs", [])
        for problem in program.get("problems", [])
    }
    require(len(roots) == sum(len(p.get("problems", [])) for p in data.get("programs", [])),
            "duplicate root problem")
    return roots


def load_index(directory: Path | None = None) -> dict[str, dict]:
    directory = directory or ROOT / "index"
    out: dict[str, dict] = {}
    if not directory.exists():
        return out
    require(not directory.is_symlink(), "index directory cannot be a symlink")
    for current, dirs, files in os.walk(directory, followlinks=False):
        require(all(not (Path(current) / d).is_symlink() for d in dirs), "symlink directory")
        for name in files:
            path = Path(current) / name
            if name == ".gitkeep":
                continue
            require(name.endswith(".json"), "non-JSON file in index")
            entry = read_json(path, MAX_INDEX_BYTES)
            validate_index(entry)
            rid = entry["payload"]["record_id"]
            require(path.relative_to(directory) == index_path(rid), "index filename mismatch")
            require(rid not in out, "duplicate indexed record")
            out[rid] = entry
    return out


def validate_index_graph(index: dict[str, dict], registry: dict[str, dict]) -> None:
    for rid, entry in index.items():
        validate_index(entry)
        p = entry["payload"]
        require(rid == p["record_id"], "index map ID mismatch")
        require(p["problem"] in registry, "root problem not registered")
        for edge in p["relations"]:
            target, relation = edge["target"], edge["type"]
            require(target != rid, "self-reference")
            if target in registry:
                require(target == p["problem"] and relation in {"addresses", "subproblem-of"},
                        "invalid root relation")
                continue
            if target not in index:
                require(bool(RID.fullmatch(target)), "invalid remote CRL reference")
                continue
            q = index[target]["payload"]
            require(q["problem"] == p["problem"], "cross-problem record resolution is not supported")
            allowed = {
                "addresses": {"QUESTION"},
                "subproblem-of": {"QUESTION"},
                "depends-on": {"RESULT"},
                "reviews": {"RESULT", "REVIEW"},
                "responds-to": {"REVIEW"},
                "revises": {p["record_type"]},
                "withdraws": {"QUESTION", "RESULT", "REVIEW"},
            }
            require(q["record_type"] in allowed[relation], "relation target has wrong type")
            if relation == "withdraws":
                require(q["actor"]["public_key"] == p["actor"]["public_key"],
                        "cannot withdraw someone else's publication")
                require(q.get("result_kind") != "withdrawal", "withdrawal is final in this profile")

    done: set[str] = set()
    for start in index:
        stack = [(start, False)]
        visiting: set[str] = set()
        while stack:
            current, exiting = stack.pop()
            if exiting:
                visiting.remove(current)
                done.add(current)
            elif current not in done:
                require(current not in visiting, "cyclic local references")
                visiting.add(current)
                stack.append((current, True))
                stack.extend(
                    (edge["target"], False)
                    for edge in index[current]["payload"]["relations"]
                    if edge["target"] in index
                )


def snapshot(index: dict[str, dict], registry: dict[str, dict]) -> dict:
    entries = [{"record_id": rid, "entry_sha256": digest(index[rid])} for rid in sorted(index)]
    roots = [registry[rid] for rid in sorted(registry)]
    manifest = {"entries": entries, "registry_sha256": digest(roots), "policy": POLICY}
    return {"id": "sha256:" + digest(manifest), **manifest}


def context(record_id: str, index: dict[str, dict], registry: dict[str, dict]) -> dict:
    require(record_id in index, "record is not present in this index")
    incoming: dict[str, set[str]] = {}
    for rid, entry in index.items():
        for edge in entry["payload"]["relations"]:
            if edge["type"] in {"reviews", "revises", "responds-to", "withdraws"}:
                incoming.setdefault(edge["target"], set()).add(rid)
    pending = [record_id]
    seen: set[str] = set()
    missing: set[str] = set()
    while pending:
        rid = pending.pop()
        if rid in seen or rid in registry:
            continue
        if rid not in index:
            missing.add(rid)
            continue
        seen.add(rid)
        pending.extend(e["target"] for e in index[rid]["payload"]["relations"])
        pending.extend(incoming.get(rid, ()))
    return {
        "target": record_id,
        "snapshot": snapshot(index, registry),
        "coverage": "partial" if missing else "complete-relative-to-this-index",
        "missing_record_ids": sorted(missing),
        "zenodo_availability": "not-checked",
        "unseen_other_indexes": "unknown",
        "entries": [index[i] for i in sorted(seen)],
    }


def board(index: dict[str, dict], registry: dict[str, dict]) -> dict:
    validate_index_graph(index, registry)
    withdrawn = {
        edge["target"]
        for entry in index.values()
        for edge in entry["payload"]["relations"]
        if edge["type"] == "withdraws"
    }
    questions = [
        {"id": rid, "title": problem["title"], "problem": rid, "kind": "root"}
        for rid, problem in sorted(registry.items())
    ]
    questions += [
        {
            "id": rid,
            "title": entry["payload"]["title"],
            "problem": entry["payload"]["problem"],
            "kind": "subquestion",
        }
        for rid, entry in sorted(index.items())
        if entry["payload"]["record_type"] == "QUESTION"
    ]
    for q in questions:
        candidate_ids = []
        for rid, entry in index.items():
            p = entry["payload"]
            if rid in withdrawn or p["record_type"] != "RESULT" or p.get("answer_scope") != "full":
                continue
            if any(e["type"] == "addresses" and e["target"] == q["id"] for e in p["relations"]):
                candidate_ids.append(rid)
        challenges = 0
        for entry in index.values():
            p = entry["payload"]
            if p["record_type"] == "REVIEW" and p["review"]["outcome"] == "challenges":
                if any(e["type"] == "reviews" and e["target"] in candidate_ids for e in p["relations"]):
                    challenges += 1
        q.update(
            progress="candidate-exists" if candidate_ids else "no-candidate",
            candidate_ids=sorted(candidate_ids),
            direct_challenge_count=challenges,
            acceptance="not-assessed",
            withdrawn=q["id"] in withdrawn,
        )
    missing = sorted({
        edge["target"]
        for entry in index.values()
        for edge in entry["payload"]["relations"]
        if bool(RID.fullmatch(edge["target"])) and edge["target"] not in index
    })
    return {
        "snapshot": snapshot(index, registry),
        "index_count": len(index),
        "questions": questions,
        "entries": [index[i] for i in sorted(index)],
        "withdrawn_ids": sorted(withdrawn),
        "missing_record_ids": missing,
        "zenodo_availability": "not-checked",
        "activity": "see-work-issues",
        "warning": (
            "This is an index view, not a verdict. Support is not acceptance; different keys "
            "do not establish independence; remote Zenodo content is not fetched by this board."
        ),
    }


def write_board(output: Path, index: dict[str, dict], registry: dict[str, dict]) -> None:
    data = board(index, registry)
    output.mkdir(parents=True, exist_ok=True)
    (output / "board.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    esc = lambda v: html.escape(str(v), quote=True)
    rows = "".join(
        f'<tr><td>{esc(q["title"])}</td><td>{esc(q["progress"])}</td>'
        f'<td>{len(q["candidate_ids"])}</td><td>{q["direct_challenge_count"]}</td></tr>'
        for q in data["questions"]
    )
    cards = []
    for entry in data["entries"]:
        p = entry["payload"]
        links = "".join(
            f'<li>{esc(e["type"])}: <code>{esc(e["target"])}</code> — {esc(e["scope"])}</li>'
            for e in p["relations"]
        )
        archive = p["archive"]
        archive_link = (f'<p>Zenodo Version DOI: <a href="{esc(archive["url"])}">{esc(archive["doi"])}</a></p>'
                        if archive["provider"] == "zenodo" else
                        f'<p>GitHub commit snapshot: <a href="{esc(archive["url"])}">{esc(archive["commit"])}</a></p>')
        cards.append(
            f'<article id="{esc(p["record_id"])}">'
            f'<h2>{esc(p["record_type"])} · {esc(p["title"])}</h2>'
            f'<p><code>{esc(p["record_id"])}</code></p>'
            f'<p>{esc(p["scope"])}</p>'
            f'{archive_link}'
            f'<p>Licence declared: {esc(p["rights"]["license_declared"])}</p>'
            f'<ul>{links}</ul></article>'
        )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\';">'
        '<title>Public AI Research Commons</title>'
        '<style>body{font:17px system-ui;max-width:1050px;margin:3rem auto;padding:0 1.5rem;'
        'line-height:1.65}table{width:100%;border-collapse:collapse}td,th{text-align:left;'
        'padding:.8rem;border-bottom:1px solid}article{border-top:1px solid;margin-top:2rem;'
        'padding-top:1rem}code{overflow-wrap:anywhere}</style>'
        '<h1>Public AI Research Commons</h1>'
        '<p>Version-pinned discovery index · observed records, not a scientific verdict.</p>'
        '<p><a href="board.json">Machine-readable snapshot</a></p>'
        f'<p>{esc(data["warning"])}</p><small>Snapshot: {esc(data["snapshot"]["id"])}</small>'
        '<table><tr><th>Question</th><th>Observed progress</th><th>Candidate answers</th>'
        f'<th>Direct challenges</th></tr>{rows}</table>{"".join(cards)}</html>\n'
    )
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / ".nojekyll").touch()


def make_index_payload(publication: dict, doi: str, zenodo_url: str,
                       source_repository: str | None = None,
                       source_commit: str | None = None,
                       concept_doi: str | None = None) -> dict:
    validate_publication(publication)
    p = publication["payload"]
    archive = {
        "provider": "zenodo",
        "doi": doi,
        "url": zenodo_url,
        "manifest_path": "crl-publication.json",
        "manifest_sha256": digest(publication),
    }
    if concept_doi:
        archive["concept_doi"] = concept_doi
    source = None
    if source_repository or source_commit:
        require(bool(source_repository and source_commit),
                "source repository and commit must be supplied together")
        source = {"repository": source_repository, "commit": source_commit}
    payload = {
        "profile": "crl-index/0.3",
        "record_id": publication["id"],
        "record_type": p["type"],
        "problem": p["problem"],
        "title": p["title"],
        "scope": p["scope"],
        "creators": p["creators"],
        "actor": copy.deepcopy(p["actor"]),
        "created_at": p["created_at"],
        "basis_snapshot": p["basis_snapshot"],
        "archive": archive,
        "source": source,
        "rights": p["rights"],
        "relations": p["relations"],
        "discovery_permission": "crl-discovery/1.0",
    }
    for field in ("result_kind", "answer_scope", "review"):
        if field in p:
            payload[field] = p[field]
    return payload


def make_github_index_payload(publication: dict, repository: str, commit: str,
                              manifest_path: str = "crl-publication.json") -> dict:
    validate_publication(publication)
    # Reuse the shared header projection; replace only the archive declaration.
    payload = make_index_payload(publication, "", "")
    payload["archive"] = {"provider": "github-commit", "repository": repository,
                          "commit": commit, "url": repository + "/tree/" + commit,
                          "manifest_path": manifest_path, "manifest_sha256": digest(publication)}
    return payload


def _write_signed_index(entry: dict, directory: Path) -> Path:
    path = directory / index_path(entry["payload"]["record_id"])
    require(not path.exists(), "index entry already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("keygen")
    p.add_argument("--out", type=Path, required=True)

    p = sub.add_parser("sign-publication")
    p.add_argument("draft", type=Path)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)

    p = sub.add_parser("validate-publication")
    p.add_argument("publication", type=Path)

    p = sub.add_parser("prepare-index")
    p.add_argument("publication", type=Path)
    p.add_argument("--doi")
    p.add_argument("--zenodo-url")
    p.add_argument("--archive-repository")
    p.add_argument("--archive-commit")
    p.add_argument("--manifest-path", default="crl-publication.json")
    p.add_argument("--concept-doi")
    p.add_argument("--source-repository")
    p.add_argument("--source-commit")
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--index", type=Path, default=Path("index"))

    sub.add_parser("validate")

    p = sub.add_parser("context")
    p.add_argument("record_id")

    p = sub.add_parser("board")
    p.add_argument("--out", type=Path, default=Path("build/site"))

    sub.add_parser("snapshot")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "keygen":
            require(not args.out.exists(), "refusing to overwrite key")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            key = Ed25519PrivateKey.generate()
            args.out.write_text(key.private_bytes_raw().hex() + "\n", encoding="ascii")
            try:
                os.chmod(args.out, 0o600)
            except OSError:
                pass
            print(key.public_key().public_bytes_raw().hex())
            return 0

        if args.cmd == "sign-publication":
            draft = read_json(args.draft, MAX_PUBLICATION_BYTES)
            publication = sign_publication(draft, _private_key(args.key))
            validate_publication(publication)
            require(not args.out.exists(), "refusing to overwrite publication")
            args.out.write_text(
                json.dumps(publication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(publication["id"])
            return 0

        if args.cmd == "validate-publication":
            validate_publication(read_json(args.publication, MAX_PUBLICATION_BYTES))
            print(json.dumps({"valid": True, "scientific_validity": "not-assessed"}))
            return 0

        registry = load_registry()
        index = load_index()
        validate_index_graph(index, registry)

        if args.cmd == "prepare-index":
            publication = read_json(args.publication, MAX_PUBLICATION_BYTES)
            validate_publication(publication)
            key = _private_key(args.key)
            pubkey = key.public_key().public_bytes_raw().hex()
            require(publication["payload"]["actor"]["public_key"] == pubkey,
                    "index signer must match publication signer")
            if args.archive_repository or args.archive_commit:
                require(bool(args.archive_repository and args.archive_commit), "archive repository/commit are paired")
                require(not any((args.doi, args.zenodo_url, args.concept_doi,
                                 args.source_repository, args.source_commit)), "archive modes cannot be mixed")
                payload = make_github_index_payload(publication, args.archive_repository, args.archive_commit,
                                                   args.manifest_path)
            else:
                require(bool(args.doi and args.zenodo_url), "Zenodo DOI/URL or GitHub archive repository/commit required")
                require(args.manifest_path == "crl-publication.json", "Zenodo manifest path is fixed")
                payload = make_index_payload(
                    publication, args.doi, args.zenodo_url, args.source_repository,
                    args.source_commit, args.concept_doi
                )
            entry = sign_index(payload, key)
            validate_index(entry)
            test_index = dict(index)
            test_index[payload["record_id"]] = entry
            validate_index_graph(test_index, registry)
            path = _write_signed_index(entry, args.index)
            print(path)
            return 0

        if args.cmd == "validate":
            print(json.dumps({
                "valid_index_entries": len(index),
                "scientific_validity": "not-assessed",
                "remote_archives_fetched": False,
            }))
            return 0

        if args.cmd == "context":
            print(json.dumps(context(args.record_id, index, registry),
                             ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "board":
            write_board(args.out, index, registry)
            print(args.out)
            return 0

        if args.cmd == "snapshot":
            print(json.dumps(snapshot(index, registry), indent=2))
            return 0

        raise AssertionError("unreachable")
    except (KeyError, ValueError, OSError, ValidationError) as exc:
        print(json.dumps({"error": str(exc)[:1500]}), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
