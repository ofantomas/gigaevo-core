"""Retry voices that failed in the first ensemble pass.

Gemini truncated under 16K budget. o3 crashed in the loop. Re-issue both with
larger budget, reasoning effort dropped/loosened, and robust None-content handling.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import httpx

OUTPUT_DIR = Path("/home/jovyan/gigaevo/output/memory_excellent_card_ensemble_20260524")


async def call_openrouter(client: httpx.AsyncClient, voice: dict, api_key: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "memory-card-quality-ensemble-retry",
    }
    body = {
        "model": voice["model"],
        "max_tokens": voice.get("max_tokens", 40000),
        "messages": voice["messages"],
        **voice.get("extra", {}),
    }
    t0 = asyncio.get_event_loop().time()
    try:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=900.0,
        )
        elapsed = asyncio.get_event_loop().time() - t0
        if resp.status_code != 200:
            return {
                "alias": voice["alias"],
                "model": voice["model"],
                "ok": False,
                "status": resp.status_code,
                "body": resp.text[:2000],
                "elapsed_s": elapsed,
            }
        data = resp.json()
        return {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": True,
            "elapsed_s": elapsed,
            "data": data,
        }
    except Exception as e:
        return {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": False,
            "error": str(e),
            "elapsed_s": asyncio.get_event_loop().time() - t0,
        }


async def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY missing", file=sys.stderr)
        return 2

    context = (OUTPUT_DIR / "ensemble_brief.md").read_text()
    msgs = [{"role": "user", "content": context}]

    voices = [
        {
            "alias": "google_gemini25",
            "model": "google/gemini-2.5-pro",
            "messages": msgs,
            "max_tokens": 40000,
            "extra": {},
        },
        {
            "alias": "openai_o3",
            "model": "openai/o3",
            "messages": msgs,
            "max_tokens": 40000,
            "extra": {"reasoning_effort": "medium"},
        },
    ]

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[call_openrouter(client, v, api_key) for v in voices]
        )

    summary = []
    for voice, result in zip(voices, results):
        out_path = OUTPUT_DIR / f"voice_{voice['alias']}.json"
        out_path.write_text(json.dumps(result, indent=2))
        row = {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": result.get("ok"),
            "elapsed_s": result.get("elapsed_s"),
            "path": str(out_path),
        }
        if result.get("ok") and "data" in result:
            choices = result["data"].get("choices", []) or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or msg.get("reasoning") or ""
                row["content_chars"] = len(content)
                row["finish_reason"] = choices[0].get("finish_reason")
                row["used_field"] = "content" if msg.get("content") else "reasoning"
                if content:
                    (OUTPUT_DIR / f"voice_{voice['alias']}_response.md").write_text(
                        content
                    )
        else:
            row["error_head"] = (result.get("error") or result.get("body", ""))[:500]
        summary.append(row)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
