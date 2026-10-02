"""CRL Commons 0.2: signed records, local context, and a conservative board.

This module never downloads artifacts, runs research code, or evaluates truth.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 65536
DOMAIN = b"CRL-COMMONS/0.2\x00"
ID = re.compile(r"crl:sha256:[0-9a-f]{64}\Z")
POLICY = {"id": "commons-observations/0.2", "acceptance": "not-implemented", "votes_are_evidence": False}


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


def loads(raw: bytes, limit: int = MAX_BYTES) -> Any:
    require(len(raw) <= limit, "input exceeds size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        stack = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            require(depth <= 20, "JSON nesting too deep")
            if isinstance(item, dict):
                stack.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                stack.extend((v, depth + 1) for v in item)
        return value
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc


def read_json(path: Path, limit: int = MAX_BYTES) -> Any:
    require(not path.is_symlink(), "symlinks are not accepted")
    with path.open("rb") as f:
        return loads(f.read(limit + 1), limit)


def canonical(value: Any) -> bytes:
    return rfc8785.dumps(value)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def record_path(identifier: str) -> Path:
    require(bool(ID.fullmatch(identifier)), "invalid record identifier")
    h = identifier.rsplit(":", 1)[1]
    return Path(h[:2], h[2:4], h + ".json")


def sign(payload: dict, key: Ed25519PrivateKey) -> dict:
    payload = copy.deepcopy(payload)
    public = key.public_key().public_bytes_raw().hex()
    old = payload["actor"].get("public_key")
    require(not old or old == public, "draft contains a different signing key")
    payload["actor"]["public_key"] = public
    raw = canonical(payload)
    return {"id": "crl:sha256:" + hashlib.sha256(raw).hexdigest(), "payload": payload,
            "signature": key.sign(DOMAIN + raw).hex()}


def validator() -> Draft202012Validator:
    schema = read_json(ROOT / "spec/record.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


VALIDATOR = validator()


def validate_record(record: dict) -> None:
    VALIDATOR.validate(record)
    require(len(canonical(record)) <= MAX_BYTES, "record too large")
    p = record["payload"]
    raw = canonical(p)
    require(record["id"] == "crl:sha256:" + hashlib.sha256(raw).hexdigest(), "content hash mismatch")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(p["actor"]["public_key"])).verify(
            bytes.fromhex(record["signature"]), DOMAIN + raw)
    except InvalidSignature as exc:
        raise ValueError("invalid signature") from exc
    for a in p["artifacts"]:
        u = urlsplit(a["uri"])
        require(u.scheme == "https" and bool(u.hostname) and not u.username and not u.password,
                "artifact URI must be HTTPS without credentials")
    types = [r["type"] for r in p["relations"]]
    if p["type"] == "QUESTION":
        require(types.count("subproblem-of") == 1, "QUESTION needs one parent")
        require(set(types) <= {"subproblem-of", "depends-on", "revises"}, "invalid QUESTION relation")
    elif p["type"] == "REVIEW":
        require(types.count("reviews") == 1, "REVIEW needs exactly one target")
        require(set(types) <= {"reviews", "depends-on", "responds-to", "revises"}, "invalid REVIEW relation")
    elif p["result_kind"] == "withdrawal":
        require(types == ["withdraws"] and p["answer_scope"] == "none", "withdrawal needs one target and no answer")
    else:
        require(types.count("addresses") >= 1, "RESULT needs a question target")
        require(set(types) <= {"addresses", "depends-on", "revises", "responds-to"}, "invalid RESULT relation")
    require(types.count("revises") <= 1, "at most one revision predecessor")


def registry_roots(registry: dict) -> dict:
    return {p["id"]: p for program in registry["programs"] for p in program["problems"]}


def validate_graph(records: dict, registry: dict) -> None:
    roots = registry_roots(registry)
    for identifier, record in records.items():
        validate_record(record)
        require(identifier == record["id"], "map ID mismatch")
        p = record["payload"]
        require(p["problem"] in roots, "root problem not registered")
        for edge in p["relations"]:
            target, kind = edge["target"], edge["type"]
            require(target != identifier, "self-reference")
            if target in roots:
                require(target == p["problem"] and kind in {"addresses", "subproblem-of"}, "invalid root relation")
                continue
            require(target in records, "missing reference: " + target)
            q = records[target]["payload"]
            require(q["problem"] == p["problem"], "cross-problem record resolution is not supported in this profile")
            allowed = {"addresses": {"QUESTION"}, "subproblem-of": {"QUESTION"},
                       "depends-on": {"RESULT"}, "reviews": {"RESULT", "REVIEW"},
                       "responds-to": {"REVIEW"}, "revises": {p["type"]},
                       "withdraws": {"QUESTION", "RESULT", "REVIEW"}}
            require(q["type"] in allowed[kind], "relation target has wrong type")
            if kind == "withdraws":
                require(q["actor"]["public_key"] == p["actor"]["public_key"], "cannot withdraw someone else's record")
                require(q.get("result_kind") != "withdrawal", "withdrawal is final for this profile")
    # Iterative traversal avoids recursion failure on long legitimate lineages.
    done = set()
    for start in records:
        stack = [(start, False)]
        visiting = set()
        while stack:
            current, exiting = stack.pop()
            if exiting:
                visiting.remove(current)
                done.add(current)
            elif current not in done:
                require(current not in visiting, "cyclic references")
                visiting.add(current)
                stack.append((current, True))
                stack.extend((e["target"], False) for e in records[current]["payload"]["relations"]
                             if e["target"] in records)


def load_records(directory: Path) -> dict:
    out = {}
    if not directory.exists():
        return out
    require(not directory.is_symlink(), "record directory cannot be a symlink")
    for current, dirs, files in os.walk(directory, followlinks=False):
        require(all(not (Path(current) / d).is_symlink() for d in dirs), "symlink directory")
        for name in files:
            path = Path(current) / name
            if name == ".gitkeep":
                continue
            require(name.endswith(".json"), "non-JSON file in records")
            record = read_json(path)
            validate_record(record)
            require(path.relative_to(directory) == record_path(record["id"]), "record filename mismatch")
            require(record["id"] not in out, "duplicate record")
            out[record["id"]] = record
    return out


def snapshot(records: dict, registry: dict) -> dict:
    manifest = {"record_ids": sorted(records), "registry_sha256": digest(registry), "policy": POLICY}
    return {"id": "sha256:" + digest(manifest), **manifest}


def context(identifier: str, records: dict, registry: dict) -> dict:
    require(identifier in records, "unknown record")
    incoming = {}
    for rid, rec in records.items():
        for e in rec["payload"]["relations"]:
            if e["type"] in {"reviews", "revises", "responds-to", "withdraws"}:
                incoming.setdefault(e["target"], set()).add(rid)
    pending, seen, missing = [identifier], set(), set()
    roots = registry_roots(registry)
    while pending:
        rid = pending.pop()
        if rid in seen or rid in roots:
            continue
        if rid not in records:
            missing.add(rid)
            continue
        seen.add(rid)
        pending.extend(e["target"] for e in records[rid]["payload"]["relations"])
        pending.extend(incoming.get(rid, ()))
    return {"target": identifier, "snapshot": snapshot(records, registry),
            "coverage": "partial" if missing else "complete-relative-to-local-snapshot",
            "missing_record_ids": sorted(missing), "artifact_availability": "not-checked",
            "unseen_remote_reviews": "unknown", "records": [records[i] for i in sorted(seen)]}


def board(records: dict, registry: dict) -> dict:
    validate_graph(records, registry)
    withdrawn = {e["target"] for r in records.values() for e in r["payload"]["relations"] if e["type"] == "withdraws"}
    questions = [{"id": i, "title": p["title"], "problem": i} for i, p in registry_roots(registry).items()]
    questions += [{"id": i, "title": r["payload"]["title"], "problem": r["payload"]["problem"]}
                  for i, r in sorted(records.items()) if r["payload"]["type"] == "QUESTION"]
    for q in questions:
        candidates = [r for i, r in records.items() if i not in withdrawn and r["payload"]["type"] == "RESULT"
                      and r["payload"].get("answer_scope") == "full"
                      and any(e == {"type": "addresses", "target": q["id"]} for e in r["payload"]["relations"])]
        q.update({"progress": "candidate-exists" if candidates else "no-candidate",
                  "candidate_ids": sorted(r["id"] for r in candidates), "acceptance": "not-assessed",
                  "withdrawn": q["id"] in withdrawn})
    return {"snapshot": snapshot(records, registry), "record_count": len(records), "questions": questions,
            "records": [records[i] for i in sorted(records)], "withdrawn_ids": sorted(withdrawn),
            "artifact_availability": "not-checked", "activity": "see-work-issues",
            "warning": "Support is not acceptance. Different keys do not establish independence. External status is not checked."}


def write_board(output: Path, records: dict, registry: dict) -> None:
    data = board(records, registry)
    output.mkdir(parents=True, exist_ok=True)
    (output / "board.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    esc = lambda v: html.escape(str(v), quote=True)
    rows = "".join(f'<tr><td>{esc(q["title"])}</td><td>{esc(q["progress"])}</td><td>{len(q["candidate_ids"])}</td></tr>' for q in data["questions"])
    cards = []
    for rec in data["records"]:
        p = rec["payload"]
        links = "".join(f'<li>{esc(e["type"])}: <a href="#{esc(e["target"])}">{esc(e["target"])}</a></li>' for e in p["relations"])
        reviews = [r for r in data["records"] if any(e == {"type": "reviews", "target": rec["id"]} for e in r["payload"]["relations"])]
        incoming = "".join(f'<li><a href="#{esc(r["id"])}">{esc(r["payload"]["title"])}</a> — {esc(r["payload"]["review"]["outcome"])}</li>' for r in reviews)
        cards.append(f'<article id="{esc(rec["id"])}"><h2>{esc(p["type"])} · {esc(p["title"])}</h2><p><code>{esc(rec["id"])}</code></p><p>Scope: {esc(p["scope"])}</p><pre>{esc(p["body"])}</pre><ul>{links}</ul><h3>Known direct reviews (not votes)</h3><ul>{incoming}</ul><p>Use the context command for the complete local dispute context, including earlier versions.</p></article>')
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Public AI Research Commons</title><style>body{font:17px system-ui;max-width:1050px;margin:3rem auto;padding:0 1.5rem;line-height:1.65}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:.8rem;border-bottom:1px solid}article{border-top:1px solid;margin-top:2rem;padding-top:1rem}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}small{overflow-wrap:anywhere}</style><h1>Public AI Research Commons</h1><p>Experimental research board · observed records, not a verdict.</p><p><a href="board.json">Machine-readable snapshot</a> · <a href="https://github.com/Li-Hongmin/public-ai-research-commons/issues?q=is%3Aissue+is%3Aopen+%5BWORK%5D">Current work declarations</a></p><p>' + esc(data['warning']) + '</p><small>Snapshot: ' + esc(data['snapshot']['id']) + '</small><table><tr><th>Question</th><th>Observed progress</th><th>Candidate answers</th></tr>' + rows + '</table>' + ''.join(cards) + '</html>\n'
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / ".nojekyll").touch()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    keygen = sub.add_parser("keygen"); keygen.add_argument("--out", type=Path, required=True)
    signer = sub.add_parser("sign"); signer.add_argument("draft", type=Path); signer.add_argument("--key", type=Path, required=True); signer.add_argument("--records", type=Path, default=Path("records"))
    for name in ("validate", "board", "context"):
        p = sub.add_parser(name)
        p.add_argument("--records", type=Path, default=Path("records"))
        p.add_argument("--registry", type=Path, default=Path("registry/problems.json"))
        if name == "context": p.add_argument("id")
        if name == "board": p.add_argument("--out", type=Path, default=Path("build/site"))
    a = parser.parse_args(argv)
    try:
        if a.cmd == "keygen":
            require(not a.out.resolve().is_relative_to(ROOT), "store the private key outside the repository")
            a.out.parent.mkdir(parents=True, exist_ok=True)
            key = Ed25519PrivateKey.generate()
            fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f: f.write(key.private_bytes_raw().hex() + "\n")
            print("Public key:", key.public_key().public_bytes_raw().hex())
        elif a.cmd == "sign":
            key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(a.key.read_text().strip()))
            rec = sign(read_json(a.draft), key); validate_record(rec)
            dest = a.records / record_path(rec["id"]); dest.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(rec, ensure_ascii=False, indent=2) + "\n"
            require(len(raw.encode()) <= MAX_BYTES, "serialized record too large")
            with dest.open("x", encoding="utf-8") as f: f.write(raw)
            print(dest)
        else:
            records = load_records(a.records); registry = read_json(a.registry)
            validate_graph(records, registry)
            if a.cmd == "validate": print(json.dumps({"valid_records": len(records), "scientific_validity": "not-assessed"}))
            elif a.cmd == "context": print(json.dumps(context(a.id, records, registry), ensure_ascii=False, indent=2))
            else: write_board(a.out, records, registry); print(a.out / "index.html")
        return 0
    except (OSError, ValueError, ValidationError, KeyError) as exc:
        # Avoid echoing attacker-controlled values as GitHub workflow commands.
        print(json.dumps({"error": str(exc)[:2000]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
