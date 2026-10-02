"""Data-only GitHub admission. Always run from a trusted base checkout.

A passing record is structurally admissible, not scientifically accepted.
No pull-request code, workflow, artifact URL, or install instruction is executed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from jsonschema import ValidationError

from crl import MAX_BYTES, load_records, loads, read_json, record_path, require, validate_graph

PATH = re.compile(r"records/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}\.json\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("unexpected API redirect")


class API:
    def __init__(self, token: str):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, path: str, method: str = "GET", data: dict | None = None):
        require(path.startswith("/repos/") and "://" not in path, "invalid API path")
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request("https://api.github.com" + path, data=body, method=method,
                                     headers={"Authorization": "Bearer " + self.token,
                                              "Accept": "application/vnd.github+json",
                                              "Content-Type": "application/json", "User-Agent": "CRL-admission/0.2"})
        with self.opener.open(req, timeout=30) as response:
            raw = response.read(2_000_001)
        return loads(raw, 2_000_000) if raw else None


def inspect(api, repo: str, number: int, root: Path, expected_head: str | None = None) -> dict:
    require(bool(REPO.fullmatch(repo)) and number > 0, "invalid repository or PR")
    prefix = "/repos/" + repo
    pr = api(f"{prefix}/pulls/{number}")
    require(pr["state"] == "open" and not pr["draft"], "PR is closed or draft")
    require(pr["base"]["ref"] == "main" and pr["base"]["repo"]["full_name"] == repo, "wrong base repository/branch")
    head = pr["head"]["sha"]
    require(bool(re.fullmatch(r"[0-9a-f]{40}", head)), "invalid head SHA")
    require(expected_head is None or head == expected_head, "PR changed; rerun validation")
    # The API changed_files total prevents truncation from hiding extra paths.
    if pr["changed_files"] != 1:
        return {"eligible": False, "reason": "governance-or-multi-file-change", "head": head}
    files = api(f"{prefix}/pulls/{number}/files?per_page=2")
    require(len(files) == 1, "file-list mismatch")
    f = files[0]
    if f["status"] != "added" or not PATH.fullmatch(f["filename"]):
        return {"eligible": False, "reason": "only-one-new-record-is-auto-admissible", "head": head}
    require(not (root / f["filename"]).exists(), "cannot replace an admitted record")
    head_repo = pr["head"]["repo"]["full_name"]
    require(bool(REPO.fullmatch(head_repo)), "invalid fork repository")
    remote = "/repos/" + head_repo
    tree = api(f"{remote}/git/trees/{head}?recursive=1")
    require(not tree.get("truncated", False), "head tree is truncated")
    entries = [e for e in tree["tree"] if e["path"] == f["filename"]]
    require(len(entries) == 1, "missing tree entry")
    entry = entries[0]
    require(entry["type"] == "blob" and entry["mode"] == "100644", "only regular non-executable files")
    require(entry["sha"] == f["sha"] and entry.get("size", MAX_BYTES + 1) <= MAX_BYTES, "blob mismatch or oversize")
    blob = api(f"{remote}/git/blobs/{entry['sha']}")
    require(blob["encoding"] == "base64" and blob["size"] <= MAX_BYTES, "invalid blob encoding or size")
    raw = base64.b64decode("".join(blob["content"].split()), validate=True)
    require(len(raw) == blob["size"], "blob length mismatch")
    record = loads(raw)
    require("records/" + record_path(record["id"]).as_posix() == f["filename"], "filename mismatch")
    records = load_records(root / "records")
    require(record["id"] not in records, "duplicate record")
    records[record["id"]] = record
    validate_graph(records, read_json(root / "registry/problems.json"))
    fresh = api(f"{prefix}/pulls/{number}")
    require(fresh["head"]["sha"] == head and fresh["base"]["ref"] == "main", "PR changed during validation")
    return {"eligible": True, "head": head, "record_id": record["id"], "scientific_validity": "not-assessed"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--head")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        repo = os.environ["GITHUB_REPOSITORY"]
        api = API(os.environ["GH_TOKEN"])
        report = inspect(api, repo, a.pr, root, a.head)
        print(json.dumps(report))
        if a.apply and report["eligible"]:
            require(os.environ.get("CRL_AUTO_ADMIT") == "true", "automatic admission is not enabled")
            local = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            live = api(f"/repos/{repo}/git/ref/heads/main")["object"]["sha"]
            require(local == live, "base changed; revalidate against the new main")
            merged = api(f"/repos/{repo}/pulls/{a.pr}/merge", "PUT",
                         {"sha": report["head"], "merge_method": "squash",
                          "commit_title": "Admit CRL record " + report["record_id"].split(":")[-1][:12]})
            require(merged.get("merged") is True, "GitHub declined the merge")
            print(json.dumps({"merged": True, "record_id": report["record_id"]}))
            # GITHUB_TOKEN merges do not reliably trigger push-based builds.
            api(f"/repos/{repo}/actions/workflows/board.yml/dispatches", "POST", {"ref": "main"})
        return 0
    except (KeyError, ValueError, OSError, ValidationError) as exc:
        print(json.dumps({"error": str(exc)[:1500]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
