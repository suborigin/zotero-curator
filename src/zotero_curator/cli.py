from __future__ import annotations

import argparse
import base64
import http.client
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from getpass import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib import error, parse, request

DEFAULT_BASE_URL = "https://api.zotero.org"
API_VERSION = "3"
OAUTH_REQUEST_URL = "https://www.zotero.org/oauth/request"
OAUTH_ACCESS_URL = "https://www.zotero.org/oauth/access"
OAUTH_AUTHORIZE_URL = "https://www.zotero.org/oauth/authorize"
DEFAULT_CALLBACK_HOST = "127.0.0.1"
DEFAULT_CALLBACK_PORT = 8765
DEFAULT_OAUTH_TIMEOUT = 300
DEFAULT_OAUTH_KEY_NAME = "zotero-curator temporary key"
ZOTERO_REGISTERED_APPS_URL = "https://www.zotero.org/oauth/apps"


class ZoteroError(RuntimeError):
    pass


@dataclass
class PlanPaper:
    title: str
    target_collection: str
    item_type: str = "preprint"
    date: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    creators: list[dict[str, str]] | None = None
    tags: list[str] | None = None
    abstract: str | None = None


@dataclass
class OAuthAccess:
    user_id: str
    api_key: str
    username: str | None = None
    key_name: str | None = None


class ZoteroClient:
    def __init__(self, user_id: str, api_key: str, base_url: str = DEFAULT_BASE_URL):
        self.user_id = user_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.root = f"{self.base_url}/users/{self.user_id}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
        raw_body: bytes | None = None,
        full_url: bool = False,
    ) -> tuple[int, dict[str, str], Any]:
        url = path if full_url else f"{self.root}{path}"
        if params:
            q = parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            url = f"{url}?{q}"

        body = None
        req_headers = {
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": API_VERSION,
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        if raw_body is not None:
            body = raw_body
        elif data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

        req = request.Request(url=url, data=body, method=method, headers=req_headers)
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                with request.urlopen(req, timeout=120) as resp:
                    raw = resp.read()
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    payload = json.loads(raw.decode("utf-8")) if (expect_json and raw) else (raw if not expect_json else None)
                    return resp.status, resp_headers, payload
            except error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                if e.code >= 500 and attempt < max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise ZoteroError(f"{method} {url} failed: HTTP {e.code} {err_body}") from e
            except (error.URLError, http.client.IncompleteRead, http.client.RemoteDisconnected, ConnectionResetError, TimeoutError) as e:
                if attempt < max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise ZoteroError(f"Network error calling {method} {url}: {e}") from e
        raise ZoteroError(f"Unexpected retry loop exit for {method} {url}")

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        start = 0
        page_size = 100
        while True:
            page_params = dict(params or {})
            page_params.update({"limit": page_size, "start": start})
            _, _, payload = self._request("GET", path, params=page_params)
            rows = payload or []
            if not rows:
                break
            out.extend(rows)
            if len(rows) < page_size:
                break
            start += page_size
        return out

    def list_collections(self) -> list[dict[str, Any]]:
        return self._paginate("/collections")

    def create_collection(self, name: str, parent_key: str | None = None) -> str:
        payload = [{"name": name, **({"parentCollection": parent_key} if parent_key else {})}]
        _, _, out = self._request("POST", "/collections", data=payload)
        return out["successful"]["0"]["key"]

    def search_items(self, query: str, qmode: str = "titleCreatorYear") -> list[dict[str, Any]]:
        rows = self._paginate("/items", params={"q": query, "qmode": qmode})
        return [r for r in rows if (r.get("data", {}).get("itemType") or "").lower() not in {"attachment", "note", "annotation"}]

    def get_item(self, key: str) -> dict[str, Any]:
        _, _, out = self._request("GET", f"/items/{key}")
        return out

    def create_item(self, item_data: dict[str, Any]) -> str:
        _, _, out = self._request("POST", "/items", data=[item_data])
        return out["successful"]["0"]["key"]

    def patch_item(self, key: str, version: int, data: dict[str, Any]) -> None:
        self._request("PATCH", f"/items/{key}", data=data, headers={"If-Unmodified-Since-Version": str(version)}, expect_json=False)

    def delete_item(self, key: str, version: int) -> None:
        self._request("DELETE", f"/items/{key}", headers={"If-Unmodified-Since-Version": str(version)}, expect_json=False)

    def delete_key(self, key: str | None = None) -> None:
        self._request("DELETE", f"{self.base_url}/keys/{key or self.api_key}", expect_json=False, full_url=True)

    def get_item_children(self, key: str) -> list[dict[str, Any]]:
        return self._paginate(f"/items/{key}/children")

    def authorize_upload(self, attachment_key: str, file_path: Path) -> dict[str, Any]:
        raw = file_path.read_bytes()
        payload = parse.urlencode(
            {
                "md5": hashlib.md5(raw).hexdigest(),
                "filename": file_path.name,
                "filesize": file_path.stat().st_size,
                "mtime": int(file_path.stat().st_mtime * 1000),
            }
        ).encode("utf-8")
        _, _, out = self._request(
            "POST",
            f"/items/{attachment_key}/file",
            raw_body=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"},
        )
        return out

    def upload_binary(self, auth: dict[str, Any], data: bytes) -> None:
        body = auth["prefix"].encode("utf-8") + data + auth["suffix"].encode("utf-8")
        self._request("POST", auth["url"], raw_body=body, headers={"Content-Type": auth["contentType"]}, expect_json=False, full_url=True)

    def register_upload(self, attachment_key: str, upload_key: str) -> None:
        payload = parse.urlencode({"upload": upload_key}).encode("utf-8")
        self._request(
            "POST",
            f"/items/{attachment_key}/file",
            raw_body=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"},
            expect_json=False,
        )


def load_plan(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ZoteroError("YAML plan requires PyYAML. Install with: pip install pyyaml") from exc
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("papers"), list):
        raise ZoteroError("Plan must contain a top-level 'papers' list")
    return payload


def parse_arxiv_id(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if "arxiv.org" in raw:
        m = re.search(r"arxiv\.org/(abs|pdf)/([^/?#]+)", raw)
        if not m:
            return None
        return re.sub(r"\.pdf$", "", m.group(2))
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", raw):
        return raw
    return None


def strip_arxiv_version(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    return re.sub(r"v\d+$", "", arxiv_id.strip())


def normalize_title(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def clean_filename_part(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    s = s.replace("/", "-")
    s = re.sub(r"[\\:*?\"<>|]", "", s)
    return s


def year_from_date(s: str | None) -> str:
    m = re.search(r"(19|20)\d{2}", s or "")
    return m.group(0) if m else "n.d."


def choose_first_author(item_data: dict[str, Any]) -> str:
    creators = item_data.get("creators") or []
    if not creators:
        return "Unknown"
    c0 = creators[0]
    return c0.get("lastName") or c0.get("name") or c0.get("firstName") or "Unknown"


def build_attachment_name(parent_data: dict[str, Any]) -> str:
    author = clean_filename_part(choose_first_author(parent_data))
    year = year_from_date(parent_data.get("date"))
    title = clean_filename_part(parent_data.get("title") or "Untitled")
    fn = f"{author} - {year} - {title}.pdf"
    return fn[:176] + ".pdf" if len(fn) > 180 else fn


def fetch_arxiv_metadata(arxiv_id: str) -> dict[str, Any]:
    base_id = strip_arxiv_version(arxiv_id)
    if not base_id:
        raise ZoteroError(f"Invalid arXiv id for metadata fetch: {arxiv_id}")

    url = f"http://export.arxiv.org/api/query?id_list={parse.quote(base_id)}"
    req = request.Request(url, headers={"User-Agent": "zotero-curator/1.0"})
    with request.urlopen(req, timeout=60) as resp:
        xml_blob = resp.read()

    root = ET.fromstring(xml_blob)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        raise ZoteroError(f"arXiv metadata not found for {base_id}")

    title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
    date = (entry.findtext("a:published", default="", namespaces=ns) or "")[:10]
    abstract = " ".join((entry.findtext("a:summary", default="", namespaces=ns) or "").split())

    creators: list[dict[str, str]] = []
    for au in entry.findall("a:author", ns):
        name = (au.findtext("a:name", default="", namespaces=ns) or "").strip()
        if not name:
            continue
        parts = name.split()
        if len(parts) >= 2:
            creators.append({"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]})
        else:
            creators.append({"creatorType": "author", "name": name})

    return {"title": title, "date": date, "abstract": abstract, "creators": creators, "arxiv_id": base_id}


def enrich_paper_from_arxiv(p: PlanPaper) -> PlanPaper:
    arxiv_id = parse_arxiv_id(p.arxiv_id) or parse_arxiv_id(p.url)
    if not arxiv_id:
        return p

    meta = fetch_arxiv_metadata(arxiv_id)
    return PlanPaper(
        title=meta["title"] or p.title,
        target_collection=p.target_collection,
        item_type=p.item_type,
        date=meta["date"] or p.date,
        doi=p.doi,
        arxiv_id=meta["arxiv_id"],
        url=f"https://arxiv.org/abs/{meta['arxiv_id']}",
        creators=meta["creators"] or p.creators,
        tags=p.tags,
        abstract=meta["abstract"] or p.abstract,
    )


def paper_to_item_data(p: PlanPaper, collection_key: str, global_tags: list[str]) -> dict[str, Any]:
    url = p.url
    arxiv_id = strip_arxiv_version(parse_arxiv_id(p.arxiv_id))
    if not url and arxiv_id:
        url = f"https://arxiv.org/abs/{arxiv_id}"
    out: dict[str, Any] = {"itemType": p.item_type, "title": p.title, "collections": [collection_key], "creators": p.creators or []}
    if p.date:
        out["date"] = p.date
    if p.doi:
        out["DOI"] = p.doi
    if url:
        out["url"] = url
    if arxiv_id:
        out["archive"] = "arXiv"
        out["archiveLocation"] = arxiv_id
    if p.abstract:
        out["abstractNote"] = p.abstract
    tags = sorted(set([*(global_tags or []), *(p.tags or [])]))
    if tags:
        out["tags"] = [{"tag": t} for t in tags]
    return out


def resolve_paper(row: dict[str, Any]) -> PlanPaper:
    return PlanPaper(
        title=row["title"],
        target_collection=row["target_collection"],
        item_type=row.get("item_type", "preprint"),
        date=row.get("date"),
        doi=row.get("doi"),
        arxiv_id=row.get("arxiv_id"),
        url=row.get("url"),
        creators=row.get("creators"),
        tags=row.get("tags"),
        abstract=row.get("abstract"),
    )


def build_collection_cache(collections: list[dict[str, Any]]) -> dict[tuple[str | None, str], str]:
    ranked: dict[tuple[str | None, str], tuple[int, str]] = {}
    for row in collections:
        d = row.get("data", {})
        key = d.get("key")
        name = d.get("name")
        parent = d.get("parentCollection") or None
        version = int(d.get("version") or 0)
        if not key or not name:
            continue
        slot = (parent, name)
        prev = ranked.get(slot)
        if prev is None or version < prev[0]:
            ranked[slot] = (version, key)
    return {k: v[1] for k, v in ranked.items()}


def index_collections(collections: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[tuple[str | None, str], list[str]], dict[str | None, list[str]]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_slot: dict[tuple[str | None, str], list[str]] = {}
    children: dict[str | None, list[str]] = {}
    for row in collections:
        d = row.get("data", {})
        key = d.get("key")
        name = d.get("name")
        parent = d.get("parentCollection") or None
        if not key or not name:
            continue
        by_key[key] = d
        by_slot.setdefault((parent, name), []).append(key)
        children.setdefault(parent, []).append(key)
    return by_key, by_slot, children


def collection_path_from_key(key: str, by_key: dict[str, dict[str, Any]]) -> str:
    parts: list[str] = []
    cur: str | None = key
    seen: set[str] = set()
    while cur and cur in by_key and cur not in seen:
        seen.add(cur)
        d = by_key[cur]
        name = d.get("name")
        if name:
            parts.append(str(name))
        cur = d.get("parentCollection") or None
    return "/".join(reversed(parts))


def _rank_collection_candidates(keys: list[str], by_key: dict[str, dict[str, Any]]) -> list[str]:
    def sort_key(k: str) -> tuple[int, int, str]:
        d = by_key.get(k, {})
        version = int(d.get("version") or 0)
        parent = d.get("parentCollection")
        has_parent = 1 if parent else 0
        return (has_parent, version, k)

    return sorted(keys, key=sort_key)


def resolve_collection_path_existing(
    *,
    path_segments: list[str],
    by_key: dict[str, dict[str, Any]],
    by_slot: dict[tuple[str | None, str], list[str]],
) -> tuple[list[str], str | None]:
    if not path_segments:
        return [], None

    states: list[tuple[str | None, list[str], int]] = [(None, [], 0)]
    for seg in path_segments:
        next_states: list[tuple[str | None, list[str], int]] = []
        for parent, matched, depth in states:
            candidates = _rank_collection_candidates(by_slot.get((parent, seg), []), by_key)
            if not candidates:
                next_states.append((parent, matched, depth))
                continue
            for c in candidates:
                next_states.append((c, matched + [c], depth + 1))
        states = next_states

    best = max(states, key=lambda s: (s[2], -int(by_key.get(s[0] or "", {}).get("version") or 0) if s[0] else 0)) if states else (None, [], 0)
    return best[1], best[0]


def canonicalize_item_collections(
    current: list[str],
    preferred_key: str | None,
    by_key: dict[str, dict[str, Any]],
    *,
    exclusive_target: bool = False,
) -> list[str]:
    if exclusive_target and preferred_key:
        return [preferred_key]

    chosen_by_path: dict[str, str] = {}
    for key in current:
        if key not in by_key:
            chosen_by_path[f"__missing__/{key}"] = key
            continue
        path = collection_path_from_key(key, by_key)
        prev = chosen_by_path.get(path)
        if prev is None:
            chosen_by_path[path] = key
            continue
        if preferred_key and (key == preferred_key or prev == preferred_key):
            chosen_by_path[path] = preferred_key
            continue
        winner = _rank_collection_candidates([prev, key], by_key)[0]
        chosen_by_path[path] = winner
    out = list(chosen_by_path.values())
    if preferred_key and preferred_key not in out:
        out.append(preferred_key)
    return sorted(set(out))


def ensure_collection_path(client: ZoteroClient, cache: dict[tuple[str | None, str], str], collections: list[dict[str, Any]], path: str, dry_run: bool) -> str:
    segments = [s.strip() for s in path.split("/") if s.strip()]
    if not segments:
        raise ZoteroError(f"Invalid target_collection path: {path}")

    by_key, by_slot, _ = index_collections(collections)
    matched_chain, parent = resolve_collection_path_existing(path_segments=segments, by_key=by_key, by_slot=by_slot)
    matched_count = len(matched_chain)
    if matched_count == len(segments) and parent:
        return parent

    # Fallback to cache-based traversal for remaining segments; create only the missing tail.
    # parent can be None (root) when no prefix exists.
    for seg in segments[matched_count:]:
        slot = (parent, seg)
        key = cache.get(slot)
        if not key:
            key = f"DRYRUN_{seg.upper().replace(' ', '_')}" if dry_run else client.create_collection(seg, parent)
            cache[slot] = key
            if not dry_run:
                collections.append({"data": {"key": key, "name": seg, "parentCollection": parent, "version": 10**9}})
        parent = key
    if not parent:
        raise ZoteroError(f"Invalid target_collection path: {path}")
    return parent


def find_existing_item(client: ZoteroClient, paper: PlanPaper) -> dict[str, Any] | None:
    if paper.doi:
        for row in client.search_items(paper.doi, qmode="everything"):
            if (row.get("data", {}).get("DOI") or "").strip().lower() == paper.doi.strip().lower():
                return row
    arxiv_id = strip_arxiv_version(parse_arxiv_id(paper.arxiv_id))
    if arxiv_id:
        for row in client.search_items(arxiv_id, qmode="everything"):
            d = row.get("data", {})
            archive_loc = strip_arxiv_version(parse_arxiv_id(d.get("archiveLocation")) or d.get("archiveLocation"))
            if d.get("archive") == "arXiv" and archive_loc == arxiv_id:
                return row
            if arxiv_id in (d.get("url") or ""):
                return row
    target = normalize_title(paper.title)
    for row in client.search_items(paper.title, qmode="titleCreatorYear"):
        if normalize_title(row.get("data", {}).get("title", "")) == target:
            return row
    return None


def pick_existing_pdf_attachment(children: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in children:
        d = row.get("data", {})
        if d.get("itemType") == "attachment" and d.get("linkMode") == "imported_file" and (d.get("contentType") or "").lower() == "application/pdf":
            return d
    return None


def pdf_url_from_paper(paper: PlanPaper, parent_data: dict[str, Any]) -> str | None:
    arxiv = (
        strip_arxiv_version(parse_arxiv_id(paper.arxiv_id))
        or strip_arxiv_version(parse_arxiv_id(parent_data.get("archiveLocation")))
        or strip_arxiv_version(parse_arxiv_id(parent_data.get("url")))
    )
    return f"https://arxiv.org/pdf/{arxiv}.pdf" if arxiv else None


def ensure_pdf_download(url: str, cache_dir: Path, filename: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / filename
    if target.exists() and target.stat().st_size > 10_000:
        return target
    req = request.Request(url, headers={"User-Agent": "zotero-curator/1.0"})
    with request.urlopen(req, timeout=120) as r:
        blob = r.read()
    if len(blob) < 10_000:
        raise ZoteroError(f"Downloaded file too small from {url}")
    target.write_bytes(blob)
    return target


def ensure_local_storage_copy(data_dir: Path, attachment_key: str, source_pdf: Path) -> None:
    d = data_dir / "storage" / attachment_key
    d.mkdir(parents=True, exist_ok=True)
    target = d / source_pdf.name
    if not target.exists() or target.stat().st_size != source_pdf.stat().st_size:
        target.write_bytes(source_pdf.read_bytes())


def upload_imported_file(client: ZoteroClient, attachment_key: str, local_pdf: Path) -> str:
    try:
        auth = client.authorize_upload(attachment_key, local_pdf)
    except ZoteroError as exc:
        if "HTTP 412" in str(exc):
            return "exists"
        raise
    if auth.get("exists") == 1:
        return "exists"
    raw = local_pdf.read_bytes()
    client.upload_binary(auth, raw)
    client.register_upload(attachment_key, auth["uploadKey"])
    return "uploaded"


def prune_noncanonical_pdf_attachments(client: ZoteroClient, children: list[dict[str, Any]], keep_key: str) -> int:
    removed = 0
    for row in children:
        d = row.get("data", {})
        if d.get("itemType") != "attachment" or d.get("key") == keep_key:
            continue
        if (d.get("contentType") or "").lower() != "application/pdf":
            continue
        if d.get("linkMode") in {"linked_file", "linked_url", "imported_url"}:
            client.delete_item(d["key"], int(d.get("version") or 0))
            removed += 1
    return removed


def ensure_attachment(
    client: ZoteroClient,
    paper: PlanPaper,
    parent_key: str,
    parent_data: dict[str, Any],
    *,
    data_dir: Path,
    cache_dir: Path,
    dry_run: bool,
    prune: bool,
) -> dict[str, Any] | None:
    pdf_url = pdf_url_from_paper(paper, parent_data)
    if not pdf_url:
        return None
    desired_name = build_attachment_name(parent_data)
    if dry_run:
        return {"parent": parent_key, "filename": desired_name, "status": "dry_run"}

    local_pdf = ensure_pdf_download(pdf_url, cache_dir, desired_name)
    children = client.get_item_children(parent_key)
    att = pick_existing_pdf_attachment(children)
    if att is None:
        att_key = client.create_item(
            {
                "itemType": "attachment",
                "parentItem": parent_key,
                "linkMode": "imported_file",
                "title": desired_name.removesuffix(".pdf"),
                "contentType": "application/pdf",
                "filename": desired_name,
            }
        )
        att = client.get_item(att_key)["data"]
    else:
        att_key = att["key"]

    patch: dict[str, Any] = {}
    if (att.get("filename") or "") != desired_name:
        patch["filename"] = desired_name
    desired_title = desired_name.removesuffix(".pdf")
    if (att.get("title") or "") != desired_title:
        patch["title"] = desired_title
    if patch:
        client.patch_item(att_key, int(att.get("version") or 0), patch)

    upload_status = upload_imported_file(client, att_key, local_pdf)
    ensure_local_storage_copy(data_dir, att_key, local_pdf)

    removed = 0
    if prune:
        children_now = client.get_item_children(parent_key)
        removed = prune_noncanonical_pdf_attachments(client, children_now, att_key)

    return {
        "parent": parent_key,
        "attachment": att_key,
        "filename": desired_name,
        "source": pdf_url,
        "upload": upload_status,
        "pruned": removed,
    }


def _oauth_percent_encode(value: str) -> str:
    return parse.quote(value, safe="~-._")


def _oauth_signature(
    method: str,
    url: str,
    params: list[tuple[str, str]],
    consumer_secret: str,
    token_secret: str | None = None,
) -> str:
    normalized = "&".join(
        f"{_oauth_percent_encode(k)}={_oauth_percent_encode(v)}"
        for k, v in sorted(params)
    )
    parts = parse.urlsplit(url)
    normalized_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    base_string = "&".join(
        [
            _oauth_percent_encode(method.upper()),
            _oauth_percent_encode(normalized_url),
            _oauth_percent_encode(normalized),
        ]
    )
    signing_key = f"{_oauth_percent_encode(consumer_secret)}&{_oauth_percent_encode(token_secret or '')}"
    digest = hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _oauth_header(params: dict[str, str]) -> str:
    parts = [f'{_oauth_percent_encode(k)}="{_oauth_percent_encode(v)}"' for k, v in sorted(params.items())]
    return "OAuth " + ", ".join(parts)


def _oauth_base_params(consumer_key: str, token: str | None = None) -> dict[str, str]:
    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    if token:
        params["oauth_token"] = token
    return params


def _parse_form_encoded(payload: bytes) -> dict[str, str]:
    data = parse.parse_qs(payload.decode("utf-8"), keep_blank_values=True)
    return {k: values[0] for k, values in data.items()}


def prompt_for_oauth_client_credentials(
    client_key: str | None,
    client_secret: str | None,
    *,
    open_apps_page: bool = True,
) -> tuple[str, str]:
    if client_key and client_secret:
        return client_key, client_secret
    if not sys.stdin.isatty():
        raise ZoteroError(
            "Missing OAuth client credentials. Set ZOTERO_OAUTH_CLIENT_KEY and "
            "ZOTERO_OAUTH_CLIENT_SECRET, pass them as flags, or run from an interactive terminal "
            "so zotero-curator can prompt for them."
        )

    if open_apps_page:
        print(
            f"Opening Zotero registered applications page: {ZOTERO_REGISTERED_APPS_URL}",
            file=sys.stderr,
        )
        webbrowser.open(ZOTERO_REGISTERED_APPS_URL)

    if not client_key:
        client_key = input("Enter Zotero OAuth client key: ").strip()
    if not client_secret:
        client_secret = getpass("Enter Zotero OAuth client secret: ").strip()
    if not client_key or not client_secret:
        raise ZoteroError("OAuth client key and secret are required.")
    return client_key, client_secret


def _signed_oauth_post(
    url: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    token: str | None = None,
    token_secret: str | None = None,
    callback_url: str | None = None,
    verifier: str | None = None,
) -> dict[str, str]:
    oauth_params = _oauth_base_params(consumer_key, token=token)
    if callback_url:
        oauth_params["oauth_callback"] = callback_url
    if verifier:
        oauth_params["oauth_verifier"] = verifier

    query_params = parse.parse_qsl(parse.urlsplit(url).query, keep_blank_values=True)
    oauth_params["oauth_signature"] = _oauth_signature(
        "POST",
        url,
        [*query_params, *oauth_params.items()],
        consumer_secret,
        token_secret=token_secret,
    )
    req = request.Request(
        url,
        method="POST",
        headers={
            "Authorization": _oauth_header(oauth_params),
            "Content-Length": "0",
            "User-Agent": "zotero-curator/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            return _parse_form_encoded(resp.read())
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise ZoteroError(f"OAuth POST {url} failed: HTTP {exc.code} {body}") from exc


def build_oauth_authorize_url(
    request_token: str,
    *,
    key_name: str,
    library_access: bool,
    notes_access: bool,
    write_access: bool,
    all_groups: str,
) -> str:
    params = {
        "oauth_token": request_token,
        "name": key_name,
        "library_access": "1" if library_access else "0",
        "notes_access": "1" if notes_access else "0",
        "write_access": "1" if write_access else "0",
        "all_groups": all_groups,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{parse.urlencode(params)}"


def _wait_for_oauth_callback(host: str, port: int, timeout: int) -> dict[str, str]:
    state: dict[str, dict[str, str] | threading.Event] = {
        "params": {},
        "event": threading.Event(),
    }

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse.parse_qs(parse.urlsplit(self.path).query, keep_blank_values=True)
            state["params"] = {k: values[0] for k, values in query.items()}
            body = b"zotero-curator OAuth authorization complete. You can return to the terminal.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            state["event"].set()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer((host, port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not state["event"].wait(timeout):
            raise ZoteroError(
                f"Timed out waiting for Zotero OAuth callback on http://{host}:{port} after {timeout}s"
            )
        return state["params"]  # type: ignore[return-value]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def perform_oauth_key_exchange(args: argparse.Namespace) -> OAuthAccess:
    consumer_key, consumer_secret = prompt_for_oauth_client_credentials(
        args.oauth_client_key or os.getenv("ZOTERO_OAUTH_CLIENT_KEY"),
        args.oauth_client_secret or os.getenv("ZOTERO_OAUTH_CLIENT_SECRET"),
        open_apps_page=args.oauth_open_registered_apps_page,
    )

    callback_url = f"http://{args.oauth_callback_host}:{args.oauth_callback_port}/oauth/callback"
    request_token_info = _signed_oauth_post(
        OAUTH_REQUEST_URL,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        callback_url=callback_url,
    )
    request_token = request_token_info.get("oauth_token")
    request_token_secret = request_token_info.get("oauth_token_secret")
    if not request_token or not request_token_secret:
        raise ZoteroError("OAuth request token response did not include oauth_token and oauth_token_secret.")

    authorize_url = build_oauth_authorize_url(
        request_token,
        key_name=args.oauth_key_name,
        library_access=args.oauth_library_access,
        notes_access=args.oauth_notes_access,
        write_access=args.oauth_write_access,
        all_groups=args.oauth_all_groups,
    )
    print(f"Open Zotero authorization URL: {authorize_url}", file=sys.stderr)
    if args.oauth_open_browser:
        webbrowser.open(authorize_url)

    callback_params = _wait_for_oauth_callback(
        args.oauth_callback_host,
        args.oauth_callback_port,
        args.oauth_timeout,
    )
    if callback_params.get("oauth_token") != request_token:
        raise ZoteroError("OAuth callback token did not match the original request token.")
    verifier = callback_params.get("oauth_verifier")
    if not verifier:
        raise ZoteroError("OAuth callback did not include oauth_verifier.")

    access_info = _signed_oauth_post(
        OAUTH_ACCESS_URL,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        token=request_token,
        token_secret=request_token_secret,
        verifier=verifier,
    )
    api_key = access_info.get("oauth_token_secret")
    user_id = access_info.get("userID")
    if not api_key or not user_id:
        raise ZoteroError("OAuth access token response did not include userID and oauth_token_secret.")

    return OAuthAccess(
        user_id=user_id,
        api_key=api_key,
        username=access_info.get("username"),
        key_name=args.oauth_key_name,
    )


def render_env_exports(access: OAuthAccess, shell: str) -> str:
    shell = shell.lower()
    if shell == "json":
        return json.dumps(
            {
                "ZOTERO_USER_ID": access.user_id,
                "ZOTERO_API_KEY": access.api_key,
                "ZOTERO_USERNAME": access.username,
            },
            ensure_ascii=False,
            indent=2,
        )
    if shell == "powershell":
        lines = [
            f"$env:ZOTERO_USER_ID='{access.user_id}'",
            f"$env:ZOTERO_API_KEY='{access.api_key}'",
        ]
        if access.username:
            lines.append(f"$env:ZOTERO_USERNAME='{access.username}'")
        return "\n".join(lines)
    if shell == "cmd":
        lines = [
            f"set ZOTERO_USER_ID={access.user_id}",
            f"set ZOTERO_API_KEY={access.api_key}",
        ]
        if access.username:
            lines.append(f"set ZOTERO_USERNAME={access.username}")
        return "\n".join(lines)
    if shell == "bash":
        lines = [
            f"export ZOTERO_USER_ID='{access.user_id}'",
            f"export ZOTERO_API_KEY='{access.api_key}'",
        ]
        if access.username:
            lines.append(f"export ZOTERO_USERNAME='{access.username}'")
        return "\n".join(lines)
    raise ZoteroError(f"Unsupported shell format: {shell}")


def clear_env_exports(shell: str) -> str:
    shell = shell.lower()
    if shell == "powershell":
        return "\n".join(
            [
                "Remove-Item Env:ZOTERO_USER_ID -ErrorAction SilentlyContinue",
                "Remove-Item Env:ZOTERO_API_KEY -ErrorAction SilentlyContinue",
                "Remove-Item Env:ZOTERO_USERNAME -ErrorAction SilentlyContinue",
            ]
        )
    if shell == "cmd":
        return "\n".join(["set ZOTERO_USER_ID=", "set ZOTERO_API_KEY=", "set ZOTERO_USERNAME="])
    if shell == "bash":
        return "unset ZOTERO_USER_ID ZOTERO_API_KEY ZOTERO_USERNAME"
    if shell == "json":
        return json.dumps({"unset": ["ZOTERO_USER_ID", "ZOTERO_API_KEY", "ZOTERO_USERNAME"]}, indent=2)
    raise ZoteroError(f"Unsupported shell format: {shell}")


def resolve_sync_credentials(args: argparse.Namespace) -> tuple[str, str, OAuthAccess | None]:
    user_id = args.user_id or os.getenv("ZOTERO_USER_ID")
    api_key = args.api_key or os.getenv("ZOTERO_API_KEY")
    oauth_access: OAuthAccess | None = None

    if not args.dry_run and (not user_id or not api_key):
        if not args.oauth_authorize:
            raise ZoteroError(
                "Missing credentials. Set ZOTERO_USER_ID and ZOTERO_API_KEY, "
                "pass --user-id/--api-key, or use --oauth-authorize."
            )
        oauth_access = perform_oauth_key_exchange(args)
        user_id = oauth_access.user_id
        api_key = oauth_access.api_key
        if args.print_env_after_oauth:
            print(render_env_exports(oauth_access, args.env_output_shell))

    if args.dry_run:
        user_id = user_id or "0"
        api_key = api_key or "DRY_RUN"

    return user_id, api_key, oauth_access


def run_sync_with_client(args: argparse.Namespace, client: ZoteroClient) -> int:
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)

    global_tags = sorted(set([*(plan.get("global_tags") or []), *(args.tag or [])]))
    collections = [] if args.dry_run else client.list_collections()
    cache = build_collection_cache(collections)

    data_dir = Path(args.data_dir).expanduser().resolve()
    cache_dir = Path(args.download_cache_dir).expanduser().resolve()

    report: dict[str, Any] = {
        "created_collections": [],
        "items_created": [],
        "items_updated": [],
        "attachments": [],
        "skipped": [],
        "errors": [],
    }

    for row in plan["papers"]:
        try:
            paper = resolve_paper(row)
            if args.enrich_arxiv_metadata:
                try:
                    paper = enrich_paper_from_arxiv(paper)
                except Exception as exc:  # pylint: disable=broad-except
                    report["errors"].append({"paper": row.get("title"), "error": f"metadata_enrich_failed: {exc}"})
                    continue

            target_key = ensure_collection_path(client, cache, collections, paper.target_collection, args.dry_run)
            if target_key.startswith("DRYRUN_"):
                report["created_collections"].append(paper.target_collection)

            existing = None if args.dry_run else find_existing_item(client, paper)
            if existing is None:
                item_key = f"DRYRUN_{re.sub(r'[^A-Z0-9]+', '_', paper.title.upper())[:30]}" if args.dry_run else client.create_item(
                    paper_to_item_data(paper, target_key, global_tags)
                )
                parent_data = paper_to_item_data(paper, target_key, global_tags)
                parent_data["key"] = item_key
                report["items_created"].append({"title": paper.title, "key": item_key, "collection": paper.target_collection})
            else:
                parent_data = existing.get("data", {})
                item_key = parent_data["key"]
                by_key, _, _ = index_collections(collections)
                current = list(parent_data.get("collections", []))
                desired = canonicalize_item_collections(
                    current + [target_key],
                    target_key,
                    by_key,
                    exclusive_target=args.exclusive_target_collection,
                )
                patch_data: dict[str, Any] = {}
                if desired != sorted(current):
                    patch_data["collections"] = desired
                # Backfill key metadata when existing items are sparse or imported as URL shells.
                if args.enrich_arxiv_metadata:
                    if not (parent_data.get("creators") or []):
                        patch_data["creators"] = paper.creators or []
                    if not (parent_data.get("date") or "") and paper.date:
                        patch_data["date"] = paper.date
                    if paper.arxiv_id:
                        patch_data["archive"] = "arXiv"
                        patch_data["archiveLocation"] = strip_arxiv_version(parse_arxiv_id(paper.arxiv_id))
                        patch_data["url"] = f"https://arxiv.org/abs/{strip_arxiv_version(parse_arxiv_id(paper.arxiv_id))}"
                    if not (parent_data.get("abstractNote") or "") and paper.abstract:
                        patch_data["abstractNote"] = paper.abstract
                    if normalize_title(parent_data.get("title", "")) != normalize_title(paper.title):
                        patch_data["title"] = paper.title

                if patch_data:
                    if not args.dry_run:
                        client.patch_item(item_key, int(parent_data.get("version") or 0), patch_data)
                        parent_data = client.get_item(item_key)["data"]
                    report["items_updated"].append({"title": parent_data.get("title"), "key": item_key, "collections": parent_data.get("collections", [])})
                else:
                    report["skipped"].append({"title": paper.title, "reason": "already_exists_in_collection", "key": item_key})

            attach_info = ensure_attachment(
                client,
                paper,
                item_key,
                parent_data,
                data_dir=data_dir,
                cache_dir=cache_dir,
                dry_run=args.dry_run,
                prune=args.prune_pdf_attachments,
            )
            if attach_info:
                report["attachments"].append(attach_info)

            time.sleep(args.sleep)
        except Exception as exc:  # pylint: disable=broad-except
            report["errors"].append({"paper": row.get("title"), "error": str(exc)})

    report_path = Path(args.report).resolve() if args.report else plan_path.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Plan: {plan_path}")
    print(f"Report: {report_path}")
    print(
        "Summary: "
        f"created_collections={len(report['created_collections'])}, "
        f"items_created={len(report['items_created'])}, "
        f"items_updated={len(report['items_updated'])}, "
        f"attachments={len(report['attachments'])}, "
        f"errors={len(report['errors'])}"
    )
    if report["errors"]:
        for err in report["errors"]:
            print(f"ERROR: {err['paper']}: {err['error']}", file=sys.stderr)
        return 2
    return 0


def run_sync(args: argparse.Namespace) -> int:
    user_id, api_key, oauth_access = resolve_sync_credentials(args)
    client = ZoteroClient(user_id=user_id, api_key=api_key, base_url=args.base_url)
    try:
        return run_sync_with_client(args, client)
    finally:
        if oauth_access and args.delete_api_key_after:
            try:
                client.delete_key(oauth_access.api_key)
                print("Revoked temporary Zotero API key after sync.", file=sys.stderr)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"WARNING: Failed to revoke temporary Zotero API key: {exc}", file=sys.stderr)


def run_auth_login(args: argparse.Namespace) -> int:
    access = perform_oauth_key_exchange(args)
    print(render_env_exports(access, args.env_output_shell))
    return 0


def run_auth_revoke(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.getenv("ZOTERO_API_KEY")
    user_id = args.user_id or os.getenv("ZOTERO_USER_ID") or "0"
    if not api_key:
        raise ZoteroError("Missing API key to revoke. Pass --api-key or set ZOTERO_API_KEY.")
    ZoteroClient(user_id=user_id, api_key=api_key, base_url=args.base_url).delete_key(api_key)
    if args.print_env_cleanup:
        print(clear_env_exports(args.env_output_shell))
    return 0


def add_oauth_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--oauth-client-key", help="Zotero OAuth client key (or ZOTERO_OAUTH_CLIENT_KEY)")
    parser.add_argument("--oauth-client-secret", help="Zotero OAuth client secret (or ZOTERO_OAUTH_CLIENT_SECRET)")
    parser.add_argument("--oauth-callback-host", default=DEFAULT_CALLBACK_HOST, help="Local callback host for OAuth browser flow")
    parser.add_argument("--oauth-callback-port", type=int, default=DEFAULT_CALLBACK_PORT, help="Local callback port for OAuth browser flow")
    parser.add_argument("--oauth-timeout", type=int, default=DEFAULT_OAUTH_TIMEOUT, help="Seconds to wait for the OAuth callback")
    parser.add_argument("--oauth-key-name", default=DEFAULT_OAUTH_KEY_NAME, help="Label shown on the temporary Zotero key")
    parser.add_argument(
        "--oauth-library-access",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Request personal library read access during OAuth (default: enabled)",
    )
    parser.add_argument(
        "--oauth-notes-access",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Request personal notes read access during OAuth (default: disabled)",
    )
    parser.add_argument(
        "--oauth-write-access",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Request personal library write access during OAuth (default: enabled)",
    )
    parser.add_argument(
        "--oauth-all-groups",
        choices=["none", "read", "write"],
        default="none",
        help="Requested access level for all current and future groups (default: none)",
    )
    parser.add_argument(
        "--oauth-open-browser",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Open the Zotero authorization URL in a browser automatically (default: enabled)",
    )
    parser.add_argument(
        "--oauth-open-registered-apps-page",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Open Zotero's registered-applications page before prompting for OAuth client credentials (default: enabled)",
    )
    parser.add_argument(
        "--env-output-shell",
        choices=["powershell", "bash", "cmd", "json"],
        default="powershell" if os.name == "nt" else "bash",
        help="Output format for exported credentials",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automate Zotero curation workflows.")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="Sync papers from plan into Zotero")
    sync.add_argument("--plan", required=True, help="Path to plan file (.yaml/.yml/.json)")
    sync.add_argument("--user-id", help="Zotero user id (or ZOTERO_USER_ID)")
    sync.add_argument("--api-key", help="Zotero API key (or ZOTERO_API_KEY)")
    sync.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Zotero API base URL")
    sync.add_argument("--report", help="Report JSON path")
    sync.add_argument("--tag", action="append", default=[], help="Extra global tag (repeatable)")
    sync.add_argument("--sleep", type=float, default=0.1, help="Sleep seconds between items")
    sync.add_argument("--dry-run", action="store_true", help="No write calls")
    sync.add_argument(
        "--data-dir",
        default=os.getenv("ZOTERO_DATA_DIR", str(Path.home() / "Zotero")),
        help="Zotero local data dir for storage copy (default: $ZOTERO_DATA_DIR or ~/Zotero)",
    )
    sync.add_argument(
        "--download-cache-dir",
        default=str(Path.home() / ".cache" / "zotero-curator" / "pdf"),
        help="Local cache dir for downloaded PDFs",
    )
    sync.add_argument(
        "--prune-pdf-attachments",
        action="store_true",
        help="Delete non-canonical PDF attachments (linked_url/imported_url/linked_file)",
    )
    sync.add_argument(
        "--enrich-arxiv-metadata",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-fill title/date/authors/abstract from arXiv when arxiv_id is available (default: enabled)",
    )
    sync.add_argument(
        "--oauth-authorize",
        action="store_true",
        help="Launch a browser OAuth flow when API credentials are not already set",
    )
    sync.add_argument(
        "--delete-api-key-after",
        action="store_true",
        help="Revoke the temporary OAuth-derived key after sync completes",
    )
    sync.add_argument(
        "--print-env-after-oauth",
        action="store_true",
        help="Print shell exports for the OAuth-derived credentials before running sync",
    )
    sync.add_argument(
        "--exclusive-target-collection",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Move existing items into the target collection instead of keeping old collection memberships (default: enabled)",
    )
    add_oauth_arguments(sync)

    auth = sub.add_parser("auth", help="Manage Zotero OAuth-derived API credentials")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)

    auth_login = auth_sub.add_parser("login", help="Run Zotero OAuth key exchange and print shell exports")
    add_oauth_arguments(auth_login)

    auth_revoke = auth_sub.add_parser("revoke", help="Revoke an API key and optionally print shell cleanup commands")
    auth_revoke.add_argument("--api-key", help="API key to revoke (or ZOTERO_API_KEY)")
    auth_revoke.add_argument("--user-id", help="User id for the authenticated client (optional for revocation)")
    auth_revoke.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Zotero API base URL")
    auth_revoke.add_argument(
        "--env-output-shell",
        choices=["powershell", "bash", "cmd", "json"],
        default="powershell" if os.name == "nt" else "bash",
        help="Output format for environment cleanup commands",
    )
    auth_revoke.add_argument(
        "--print-env-cleanup",
        action="store_true",
        help="Print shell commands that remove ZOTERO_* environment variables after revocation",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "sync":
        return run_sync(args)
    if args.command == "auth":
        if args.auth_command == "login":
            return run_auth_login(args)
        if args.auth_command == "revoke":
            return run_auth_revoke(args)
    raise ZoteroError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ZoteroError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
