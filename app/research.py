"""Research is secondary reference lookup only, without unlicensed image copying."""
from html import unescape
import re
from urllib.parse import quote
import httpx

WIKI_API = "https://ja.wikipedia.org/w/api.php"

async def research(name: str):
    params = {
        "action": "query", "generator": "search", "gsrsearch": name,
        "gsrlimit": 6, "prop": "info|extracts", "inprop": "url",
        "exintro": "1", "explaintext": "1", "exsentences": "2",
        "format": "json"
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=False,
            headers={"User-Agent": "AIPaperModelar/0.1 (research prototype)"}) as client:
        result = await client.get(WIKI_API, params=params)
        result.raise_for_status()
    pages = result.json().get("query", {}).get("pages", {})
    items = []
    for page in sorted(pages.values(), key=lambda a: a.get("index", 0)):
        name = page.get("title", "")
        if name:
            items.append({
                "title": name[:180],
                "url": page.get("fullurl") or
                       "https://ja.wikipedia.org/wiki/" + quote(name.replace(" ", "_")),
                "summary": re.sub(r"\s+", " ", unescape(page.get("extract", "")))[:330],
                "source_type": "Wikipedia (secondary reference)",
                "dimensions_verified": False,
                "reuse_rights_verified": False
            })
    return {
        "results": items,
        "note": ("Wikipediaの概要資料です。一次資料の外観図・構造図、"
                 "実寸の根拠、画像の利用条件は別途確認してください。")
    }
