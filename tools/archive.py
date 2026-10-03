"""Bounded public GitHub/Zenodo archive verification; remote bytes never execute."""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request

from crl import (MAX_PUBLICATION_BYTES, digest, loads, make_github_index_payload, make_index_payload,
                 require, validate_index, validate_publication)

MAX_METADATA_BYTES = 2_000_000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_SECONDS = 120
DOI = re.compile(r"10\.5281/zenodo\.([1-9][0-9]*)\Z")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Zenodo redirect rejected; inspect provider contract")


def file_key(key):
    require(isinstance(key, str) and key and len(key) <= 1024 and not key.startswith("/")
            and ".." not in key and "\\" not in key and not any(ord(c) < 32 for c in key)
            and all(p not in {"", "."} for p in key.split("/")), "unsafe Zenodo file key")
    return key


def file_url(url, record, key):
    """Accept only exact same-origin record/file paths; never follow arbitrary links."""
    u = urllib.parse.urlsplit(url)
    require(u.scheme == "https" and u.netloc == "zenodo.org" and not u.fragment
            and not u.query, "unsafe Zenodo file origin/query")
    encoded = urllib.parse.quote(file_key(key), safe="")
    canonical = f"/api/records/{record}/files/{encoded}/content"
    # Legacy published-record files have provider-assigned bucket UUIDs.
    legacy = re.fullmatch(r"/api/files/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/(.+)", u.path)
    require(u.path == canonical or (legacy is not None and legacy[1] == encoded), "unexpected Zenodo file path")
    return url


class Zenodo:
    def __init__(self, github=False):
        self.opener = urllib.request.build_opener(NoRedirect())
        self.deadline = time.monotonic() + MAX_SECONDS
        # Both providers read two metadata responses. Package bytes remain
        # capped separately at 32 MiB; reserve one byte for a caller's EOF probe.
        self.remaining = MAX_TOTAL_BYTES + 2 * MAX_METADATA_BYTES + 1
        self.github = github

    def __call__(self, url, limit):
        u = urllib.parse.urlsplit(url)
        allowed = (u.netloc in {"api.github.com", "raw.githubusercontent.com"}) if self.github else (u.netloc == "zenodo.org")
        require(u.scheme == "https" and allowed and not u.fragment and not u.username
                and (not u.query or (self.github and u.netloc == "api.github.com" and u.query == "recursive=1")),
                "unsafe archive URL")
        require(time.monotonic() < self.deadline, "archive verification time budget exceeded")
        require(0 < limit <= self.remaining, "archive verification byte budget exceeded")
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json" if self.github else "application/vnd.zenodo.v1+json",
            "Accept-Encoding": "identity", "User-Agent": "CRL-archive-check/0.3",
        })  # No auth, cookies, GitHub token, or arbitrary metadata headers.
        with self.opener.open(req, timeout=min(20, max(1, self.deadline - time.monotonic()))) as response:
            require(response.status == 200 and response.geturl() == url, "unexpected archive response")
            require(response.headers.get("Content-Encoding", "identity") == "identity", "encoded response rejected")
            length = response.headers.get("Content-Length")
            require(length is None or (length.isdigit() and int(length) <= limit), "remote response oversize")
            parts, size = [], 0
            while True:
                require(time.monotonic() < self.deadline, "archive verification time budget exceeded")
                block = response.read(min(65536, limit + 1 - size))
                if not block:
                    break
                size += len(block)
                require(size <= limit, "remote response oversize")
                parts.append(block)
        self.remaining -= size
        return b"".join(parts)


def inventory(meta):
    files = meta["files"]
    if isinstance(files, list):  # Documented Zenodo v1 representation.
        result = {file_key(f["key"]): f for f in files}
        require(len(result) == len(files), "duplicate archived file key")
    else:  # Current InvenioRDM representation, fail closed on unknown shapes.
        require(files.get("enabled") is True and isinstance(files["entries"], dict), "files unavailable")
        result = {}
        for key, value in files["entries"].items():
            require(value.get("key", key) == key and value.get("status", "completed") == "completed",
                    "unfinished/mismatched archived file")
            result[file_key(key)] = value
    require(1 <= len(result) <= 33, "archive file count outside small-package lane")
    total = 0
    for value in result.values():
        size = value["size"]
        require(type(size) is int and 0 <= size <= MAX_FILE_BYTES, "archive file size outside small-package lane")
        total += size
    require(total <= MAX_TOTAL_BYTES, "archive total size outside small-package lane")
    return result


def verify_zenodo(entry, fetch=None):
    validate_index(entry)
    fetch = fetch or Zenodo()
    p = entry["payload"]
    archive = p["archive"]
    match = DOI.fullmatch(archive["doi"])
    require(match is not None, "specific Zenodo DOI required")
    record = match[1]
    raw_meta = fetch(f"https://zenodo.org/api/records/{record}", MAX_METADATA_BYTES)
    meta = loads(raw_meta, MAX_METADATA_BYTES)
    doi = meta.get("doi") or meta.get("pids", {}).get("doi", {}).get("identifier")
    concept = meta.get("conceptdoi") or meta.get("parent", {}).get("pids", {}).get("doi", {}).get("identifier")
    require(str(meta["id"]) == record and doi == archive["doi"], "provider version ID/DOI mismatch")
    require(isinstance(concept, str) and DOI.fullmatch(concept) and concept != doi,
            "provider Version/Concept DOI distinction unavailable")
    require(not archive.get("concept_doi") or archive["concept_doi"] == concept, "concept DOI mismatch")
    require(meta.get("is_published", True) is True and meta.get("submitted", True) is True,
            "draft is not a published archive")
    access = meta.get("access")
    if access is not None:
        require(access.get("record") == "public" and access.get("files") == "public", "archive not public")
    else:
        require(meta.get("metadata", {}).get("access_right") == "open", "archive not open access")
    files = inventory(meta)
    manifest_key = archive["manifest_path"]
    require(manifest_key == "crl-publication.json" and manifest_key in files, "archived manifest missing")

    def download(key, cap):
        item = files[key]
        require(item["size"] <= cap, "manifest/file too large")
        links = item.get("links", {})
        url = links.get("content") or links.get("self")
        require(isinstance(url, str), "file download link unavailable")
        raw = fetch(file_url(url, record, key), max(1, min(cap, item["size"] + 1)))
        require(len(raw) == item["size"], "archive file length mismatch")
        checksum = item.get("checksum", "")
        if checksum:
            algorithm, sep, expected = checksum.partition(":")
            require(sep and algorithm in {"md5", "sha256"}, "unsupported provider checksum")
            require(hashlib.new(algorithm, raw).hexdigest() == expected, "provider file checksum mismatch")
        return raw

    raw_manifest = download(manifest_key, MAX_PUBLICATION_BYTES)
    publication = loads(raw_manifest, MAX_PUBLICATION_BYTES)
    validate_publication(publication)
    require(publication["id"] == p["record_id"] and digest(publication) == archive["manifest_sha256"],
            "archive signed-manifest identity/hash mismatch")
    source = p.get("source") or {}
    expected = make_index_payload(publication, archive["doi"], archive["url"],
                                  source.get("repository"), source.get("commit"), archive.get("concept_doi"))
    require(p == expected, "header differs from archived signed publication")
    artifacts = publication["payload"]["artifacts"]
    keys = [file_key(a["path"]) for a in artifacts]
    require(len(keys) == len(set(keys)) and manifest_key not in keys, "duplicate/circular artifact path")
    require(set(files) == {manifest_key, *keys}, "archive inventory differs from manifest")
    for artifact in artifacts:
        raw = download(artifact["path"], MAX_FILE_BYTES)
        require(hashlib.sha256(raw).hexdigest() == artifact["sha256"], "archive artifact SHA256 mismatch")
    # Metadata may be mutable; re-read the same version and detect changes during this check.
    final_meta = loads(fetch(f"https://zenodo.org/api/records/{record}", MAX_METADATA_BYTES), MAX_METADATA_BYTES)
    require(final_meta == meta, "archive metadata changed during verification; retry by read-back")
    return {"zenodo_fetched": True, "archive_verified": True, "doi": doi,
            "concept_doi": concept, "manifest_sha256": digest(publication),
            "artifact_count": len(artifacts), "scientific_validity": "not-assessed"}


def verify_github(entry, fetch=None):
    validate_index(entry)
    fetch = fetch or Zenodo(github=True)  # Anonymous reads: no GitHub/Zenodo credential forwarding.
    p, archive = entry["payload"], entry["payload"]["archive"]
    repo = archive["repository"].removeprefix("https://github.com/")
    commit, manifest_path = archive["commit"], file_key(archive["manifest_path"])
    prefix = "https://api.github.com/repos/" + repo
    meta = loads(fetch(prefix, MAX_METADATA_BYTES), MAX_METADATA_BYTES)
    require(meta.get("private") is False and meta.get("visibility", "public") == "public"
            and meta.get("full_name", "").lower() == repo.lower(), "GitHub archive must be the exact public repository")
    tree = loads(fetch(prefix + f"/git/trees/{commit}?recursive=1", MAX_METADATA_BYTES), MAX_METADATA_BYTES)
    require(not tree.get("truncated", False), "archive tree truncated; cannot verify package inventory")
    parent = manifest_path.rsplit("/", 1)[0] + "/" if "/" in manifest_path else ""
    files = {}
    for item in tree["tree"]:
        if not item["path"].startswith(parent) or item["type"] == "tree":
            continue
        require(item["type"] == "blob" and item["mode"] in {"100644", "100755"}, "archive symlink/submodule rejected")
        relative = file_key(item["path"][len(parent):])
        require(relative not in files, "duplicate Git tree path")
        require(type(item.get("size")) is int and 0 <= item["size"] <= MAX_FILE_BYTES,
                "archive file size outside small-package lane")
        require(bool(re.fullmatch(r"[0-9a-f]{40}", item["sha"])), "invalid Git blob SHA")
        files[relative] = item
    require("crl-publication.json" in files and files["crl-publication.json"]["mode"] == "100644",
            "signed manifest missing or executable")
    require(1 <= len(files) <= 33 and sum(i["size"] for i in files.values()) <= MAX_TOTAL_BYTES,
            "package outside small-package lane")

    def download(key, cap):
        item = files[key]
        require(item["size"] <= cap, "manifest/file too large")
        path = parent + key
        url = "https://raw.githubusercontent.com/" + repo + "/" + commit + "/" + urllib.parse.quote(path, safe="/")
        raw = fetch(url, max(1, min(cap, item["size"] + 1)))
        require(len(raw) == item["size"], "GitHub archive file length mismatch")
        blob_hash = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(blob_hash == item["sha"], "GitHub archive blob hash mismatch")
        return raw

    publication = loads(download("crl-publication.json", MAX_PUBLICATION_BYTES), MAX_PUBLICATION_BYTES)
    validate_publication(publication)
    require(publication["id"] == p["record_id"] and digest(publication) == archive["manifest_sha256"],
            "GitHub signed-manifest identity/hash mismatch")
    expected = make_github_index_payload(publication, archive["repository"], commit, manifest_path)
    expected["source"] = p.get("source")  # Optional earlier source provenance, not archive authority.
    require(p == expected, "header differs from archived signed publication")
    artifacts = publication["payload"]["artifacts"]
    keys = [file_key(a["path"]) for a in artifacts]
    require(len(keys) == len(set(keys)) and "crl-publication.json" not in keys, "duplicate/circular artifact path")
    require(set(files) == {"crl-publication.json", *keys}, "GitHub package inventory differs from manifest")
    for artifact in artifacts:
        require(hashlib.sha256(download(artifact["path"], MAX_FILE_BYTES)).hexdigest() == artifact["sha256"],
                "GitHub artifact SHA256 mismatch")
    return {"zenodo_fetched": False, "github_fetched": True, "archive_verified": True,
            "repository": archive["repository"], "commit": commit, "manifest_sha256": digest(publication),
            "artifact_count": len(artifacts), "scientific_validity": "not-assessed"}


def verify(entry, fetch=None):
    return verify_github(entry, fetch) if entry["payload"]["archive"]["provider"] == "github-commit" else verify_zenodo(entry, fetch)
