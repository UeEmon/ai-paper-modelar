"""Public reference discovery. Fetch search metadata only, never arbitrary result URLs."""
import asyncio
from html import unescape
import ipaddress
import json
import re
import unicodedata
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

WIKI_API = "https://ja.wikipedia.org/w/api.php"
WEB_SEARCH = "https://www.bing.com/search"
MAX_RESPONSE_BYTES = 512 * 1024


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\x00-\x1f\x7f]", value):
        return None
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower().rstrip(".")
        if (parts.scheme not in {"http", "https"} or not host or parts.username is not None
                or parts.password is not None or parts.port == 0
                or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if "." not in host:
                return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def plain(value, limit=1200):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", unescape(str(value or "")))).strip()[:limit]


def reference(title, url, summary, provider):
    url = public_url(url)
    title = plain(title, 180)
    if not url or not title:
        return None
    return {"title": title, "url": url, "summary": plain(summary),
            "domain": urlsplit(url).hostname, "provider": provider,
            "source_type": "Web検索の抜粋 (Bing)" if provider == "web" else "Wikipediaの概要 (二次資料)",
            "dimensions_verified": False, "reuse_rights_verified": False}


async def fetch_metadata(client, url, params):
    async with asyncio.timeout(12), client.stream("GET", url, params=params) as response:
        response.raise_for_status()
        payload = bytearray()
        async for chunk in response.aiter_bytes():
            payload.extend(chunk)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError("Search response too large")
        return bytes(payload)


async def wikipedia(client, name):
    payload = await fetch_metadata(client, WIKI_API, {
        "action": "query", "generator": "search", "gsrsearch": name,
        "gsrlimit": 6, "prop": "info|extracts", "inprop": "url",
        "exintro": "1", "explaintext": "1", "exchars": "1200", "format": "json",
    })
    data = json.loads(payload)
    if not isinstance(data, dict) or "error" in data:
        raise ValueError("Invalid Wikipedia response")
    pages = data.get("query", {}).get("pages", {})
    if not isinstance(pages, dict):
        raise ValueError("Invalid Wikipedia pages")
    items = []
    for page in sorted(pages.values(), key=lambda item: item.get("index", 0)):
        title = page.get("title", "")
        item = reference(title, page.get("fullurl") or "https://ja.wikipedia.org/wiki/" + quote(title.replace(" ", "_")), page.get("extract", ""), "wikipedia")
        if item:
            items.append(item)
    return items


async def web_search(client, name):
    payload = await fetch_metadata(client, WEB_SEARCH, {
        "q": name, "format": "rss", "mkt": "ja-JP", "setlang": "ja-JP", "count": 8,
    })
    xml = payload.decode("utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, flags=re.I):
        raise ValueError("DTD is not allowed")
    root = ElementTree.fromstring(xml)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Invalid search feed")
    items = []
    for entry in root.findall("./channel/item")[:20]:
        item = reference(entry.findtext("title"), entry.findtext("link"), entry.findtext("description"), "web")
        if item:
            items.append(item)
    return items[:8]


async def research(name: str, scope: str = "all"):
    if scope not in {"all", "web", "wikipedia"}:
        raise ValueError("Invalid search scope")
    names = ["web", "wikipedia"] if scope == "all" else [scope]
    async with httpx.AsyncClient(timeout=12, follow_redirects=False,
            headers={"User-Agent": "AIPaperModelar/0.1 (public reference lookup)"}) as client:
        responses = await asyncio.gather(*(
            web_search(client, name) if provider == "web" else wikipedia(client, name)
            for provider in names), return_exceptions=True)
    providers, groups, warnings = [], {}, []
    for provider, result in zip(names, responses):
        failed = isinstance(result, Exception)
        providers.append({"id": provider, "status": "error" if failed else "ok"})
        groups[provider] = [] if failed else result
        if failed:
            warnings.append(("Web検索" if provider == "web" else "Wikipedia検索") + "を利用できませんでした。利用できた検索元の結果だけを表示しています。再試行するか検索範囲を変更してください。")
    if all(provider["status"] == "error" for provider in providers):
        raise ValueError("Public reference providers unavailable")
    # Interleave web results with encyclopedia context and remove duplicate URLs.
    web, wiki = groups.get("web", []), groups.get("wikipedia", [])
    ordered = []
    while web or wiki:
        ordered += web[:2] + wiki[:1]
        web, wiki = web[2:], wiki[1:]
    unique = {}
    for item in ordered:
        url = item["url"].rstrip("/")
        if url not in unique:
            unique[url] = item
    normalize = lambda text: re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", text).casefold())
    phrase = normalize(name)
    first = normalize(name.split()[0]) if name.split() else ""
    def relevance(item):
        content = normalize(item["title"] + " " + item["summary"])
        return 2 if phrase and phrase in content else 1 if len(first) >= 2 and first in content else 0
    ranked = sorted(unique.values(), key=relevance, reverse=True)
    for item in ranked:
        item["query_match"] = relevance(item) > 0
    return {"results": ranked[:8], "scope": scope, "providers": providers, "warnings": warnings,
            "note": "検索結果の抜粋・概要です。リンク先本文や画像は取得していません。出典を開いて内容・寸法・図面や画像の利用条件を確認してください。"}
