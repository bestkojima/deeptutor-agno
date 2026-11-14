"""Bounded education retrieval: local excerpts and server opt-in fixed endpoints."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

MAX_BYTES = 512_000


def local_retrieve(query: str, sources: list[dict], limit: int = 6) -> list[dict]:
    tokens = set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", query.casefold()))
    def score(s):
        body = str(s.get("text", "")).casefold()
        return sum(token in body for token in tokens)
    scored = sorted(((score(s), i, s) for i, s in enumerate(sources)), key=lambda x: (-x[0], x[1]))
    return [s for rank, _, s in scored[:max(1, min(limit, 12))] if rank > 0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Redirects disabled for retrieval")


def _fetch(url: str, *, body: dict | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers or {})
    with urllib.request.build_opener(_NoRedirect()).open(req, timeout=8) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Retrieval response too large")
    return data


def _source(provider: str, title: str, url: str, text: str) -> dict:
    return {"id": provider + ":" + hashlib.sha256(url.encode()).hexdigest()[:16],
            "title": title[:300], "url": url, "text": text[:4000], "provider": provider}


def arxiv_retrieve(query: str, limit: int = 4) -> list[dict]:
    if os.getenv("TUTOR_ENABLE_ARXIV") != "1":
        raise RuntimeError("arXiv retrieval disabled by server")
    query = re.sub(r'["\\\x00-\x1f]', ' ', str(query))[:220].strip()
    if not query:
        return []
    qs = urllib.parse.urlencode({"search_query": 'all:"' + query + '"',
                                 "max_results": max(1, min(limit, 6))})
    data = _fetch("https://export.arxiv.org/api/query?" + qs)
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)", data, flags=re.I):
        raise ValueError("Unexpected XML declaration")
    root = ET.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    result = []
    for node in root.findall("atom:entry", ns)[:6]:
        identifier = (node.findtext("atom:id", "", ns) or "").rsplit("/abs/", 1)[-1]
        if not re.fullmatch(r"(?:[a-zA-Z.-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", identifier):
            continue
        title = " ".join(node.findtext("atom:title", "", ns).split())
        summary = " ".join(node.findtext("atom:summary", "", ns).split())
        if summary:
            result.append(_source("arxiv", title, f"https://arxiv.org/abs/{identifier}", summary))
    return result


def web_retrieve(query: str, limit: int = 4) -> list[dict]:
    if os.getenv("TUTOR_ENABLE_WEB") != "1":
        raise RuntimeError("Web retrieval disabled by server")
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("Set TAVILY_API_KEY in the server environment")
    data = _fetch("https://api.tavily.com/search",
                  body={"query": str(query)[:300], "max_results": max(1, min(limit, 6)),
                        "search_depth": "basic", "include_answer": False, "include_raw_content": False},
                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    result = []
    for row in json.loads(data).get("results", [])[:6]:
        url = str(row.get("url", ""))
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            continue
        content = str(row.get("content", "")).strip()
        if content:
            result.append(_source("web", str(row.get("title", "")), url[:2000], content))
    return result
