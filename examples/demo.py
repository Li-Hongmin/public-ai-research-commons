"""Build a synthetic parity lineage outside the official research record.

The deliberately false first result is a test fixture, not research progress.
All actors are simulated by one script; keys do not establish independence.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tools.crl import sign, record_path, validate_graph, write_board


def make_demo():
    root = "crl:problem:demo-parity"
    registry = {"programs": [{"id": "synthetic-demo", "problems": [{"id": root, "title": "DEMO: parity of consecutive products"}]}]}
    keys = [Ed25519PrivateKey.generate() for _ in range(4)]
    records = {}
    def add(typ, title, body, relations, who=0, **extra):
        p = {"profile": "crl-commons/0.2", "type": typ, "problem": root, "title": title,
             "body": body, "scope": "Synthetic integer-arithmetic example; no new scientific result.",
             "actor": {"kind": "software", "name": f"Simulated participant {who}"},
             "created_at": "2026-10-03T00:00:00Z", "basis_snapshot": None,
             "license": "CC0-1.0", "relations": [{"type": k, "target": v} for k, v in relations],
             "artifacts": [], **extra}
        r = sign(p, keys[who]); records[r["id"]] = r; return r["id"]
    q = add("QUESTION", "Is n(n+1) even for every integer n?", "Find an argument for all integers.", [("subproblem-of", root)])
    r1 = add("RESULT", "Deliberately flawed argument", "Every integer n is even, so n(n+1) is even.", [("addresses", q)], result_kind="proof", answer_scope="full")
    c = add("REVIEW", "Counterexample to the premise", "n=1 is odd. The claimed premise fails; this does not refute the conclusion.", [("reviews", r1)], who=1,
            review={"outcome": "challenges", "method": "argument-check", "scope": "The premise that every integer is even."})
    r2 = add("RESULT", "Corrected parity argument", "If n is even the product is even. If n is odd, n+1 is even. These cases exhaust the integers.", [("addresses", q), ("revises", r1), ("responds-to", c)], who=2, result_kind="proof", answer_scope="full")
    add("REVIEW", "Simulated check of the two cases", "The even and odd cases cover all integers. This scripted review is not independent validation.", [("reviews", r2)], who=3,
        review={"outcome": "supports", "method": "argument-check", "scope": "The corrected argument, not an external proof-checker run."})
    validate_graph(records, registry)
    return records, registry


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--out", type=Path, required=True); a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    records, registry = make_demo()
    (a.out / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")
    for r in records.values():
        path = a.out / "records" / record_path(r["id"]); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(r, indent=2) + "\n")
    write_board(a.out / "site", records, registry)
    print(a.out / "site/index.html")
