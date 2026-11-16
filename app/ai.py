"""Text-only design proposals via configurable AI providers."""
import json
import os
import httpx
from pydantic import BaseModel, Field
from typing import Literal

class ProposalRequest(BaseModel):
    place: str = Field(min_length=2, max_length=120)
    scale: int = Field(default=150, ge=20, le=500)
    style: Literal["faithful","standard","anime","retro","easy"] = "standard"
    sources: list[dict] = Field(default_factory=list, max_length=8)

LABELS = {
    "faithful": "忠実再現", "standard": "標準デフォルメ",
    "anime": "アニメ風", "retro": "昭和レトロ風", "easy": "簡単組立"
}
NOTES = {
    "faithful": "立面や屋根・窓配置の忠実な再現を目指し、実寸と資料の確認後に設計します。",
    "standard": "特徴的な外観を残し、細部を印刷テクスチャにします。",
    "anime": "輪郭と配色を強調した背景美術風にまとめます。",
    "retro": "経年感のある色・看板・木目を追加し、演出箇所を明示します。",
    "easy": "壁4面と屋根で組み立てられる簡易構成にします。"
}

def offline(req: ProposalRequest):
    choices = list(dict.fromkeys([req.style, "faithful", "standard", "anime", "easy"]))[:3]
    return {
        "provider": "offline", "place": req.place,
        "proposals": [
            {"style": s, "title": LABELS[s], "description": NOTES[s]}
            for s in choices
        ],
        "notes": [
            "AI API未設定または利用できないため、定型案を表示しています。",
            "実在の形状・寸法・図面の権利を確認したものではありません。"
        ]
    }

async def proposals(req: ProposalRequest):
    provider = os.getenv("AI_PROVIDER", "none").lower()
    keys = {
        "openai": os.getenv("OPENAI_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "anthropic": os.getenv("ANTHROPIC_API_KEY", "")
    }
    if provider not in keys or not keys[provider]:
        return offline(req)
    system = (
        "Respond only with a JSON object with keys proposals (array of 3 objects: "
        "style, title, description) and notes (array of strings). Japanese output. "
        "style must be faithful, standard, anime, retro, or easy. "
        "Recommend railway paper craft designs and fabrication tradeoffs. "
        "You have not seen images, structural drawings, or verified dimensions. "
        "Treat supplied search metadata as unverified, avoid invented claims and URLs. "
        "No claim of permissions or precise replica without primary sources."
    )
    prompt = json.dumps({
        "place": req.place, "scale": req.scale,
        "preferred_style": req.style, "source_metadata": req.sources[:8]
    }, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            if provider == "openai":
                r = await client.post("https://api.openai.com/v1/responses",
                    headers={"Authorization": "Bearer " + keys[provider]},
                    json={"model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                          "instructions": system, "input": prompt})
                r.raise_for_status()
                data = r.json()
                raw = "".join(c.get("text", "") for out in data.get("output", [])
                              for c in out.get("content", [])
                              if c.get("type") == "output_text")
            elif provider == "gemini":
                model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                r = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    + model + ":generateContent",
                    headers={"x-goog-api-key": keys[provider]},
                    json={"contents": [{"parts": [{"text": system + "\n" + prompt}]}],
                          "generationConfig": {"responseMimeType": "application/json"}})
                r.raise_for_status()
                raw = "".join(p.get("text", "") for c in r.json().get("candidates", [])
                              for p in c.get("content", {}).get("parts", []))
            else:
                r = await client.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": keys[provider], "anthropic-version": "2023-06-01"},
                    json={"model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                          "max_tokens": 1300, "system": system,
                          "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                raw = "".join(c.get("text", "") for c in r.json().get("content", [])
                              if c.get("type") == "text")
        raw = raw.strip()
        if raw.startswith(chr(96) * 3) or raw.startswith("~~~"):
            raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
        result = json.loads(raw)
        accepted = []
        for p in result["proposals"][:3]:
            style = p.get("style", "standard")
            if style not in LABELS:
                style = "standard"
            accepted.append({
                "style": style, "title": str(p.get("title") or LABELS[style])[:80],
                "description": str(p.get("description", ""))[:800]
            })
        if not accepted:
            raise ValueError("No proposals")
        return {"provider": provider, "place": req.place,
                "proposals": accepted,
                "notes": [str(x)[:240] for x in result.get("notes", [])[:8]]}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        answer = offline(req)
        answer["notes"].insert(0, "外部APIに接続できなかったため、代替案を表示しています。")
        return answer
