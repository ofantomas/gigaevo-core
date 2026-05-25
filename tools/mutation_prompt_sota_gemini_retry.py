"""Retry just the Gemini voice from the SOTA final ensemble.

Brief was 95KB; Gemini at reasoning.effort=high disconnected the server.
Retry at medium with the same brief.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import httpx

OUTPUT_DIR = Path(
    "/home/jovyan/gigaevo/output/mutation_prompt_sota_final_ensemble_20260524"
)


async def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY missing", file=sys.stderr)
        return 2

    brief = (OUTPUT_DIR / "ensemble_brief.md").read_text()
    print(f"Brief size: {len(brief) / 1024:.1f} KB", file=sys.stderr)

    proxy = os.environ.get("HTTPS_PROXY")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "mutation-prompt-sota-gemini-retry",
    }

    voice_alias = "google_gemini25"
    body = {
        "model": "google/gemini-2.5-pro",
        "max_tokens": 60000,
        "messages": [{"role": "user", "content": brief}],
        "extra_body": {"reasoning": {"effort": "medium"}},
    }

    async with httpx.AsyncClient(proxy=proxy) as client:
        for attempt in range(1, 4):
            t0 = asyncio.get_event_loop().time()
            try:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=body,
                    timeout=1800.0,
                )
                elapsed = asyncio.get_event_loop().time() - t0
                if resp.status_code != 200:
                    print(
                        f"Attempt {attempt}: HTTP {resp.status_code} in {elapsed:.1f}s; body[:500]={resp.text[:500]}",
                        file=sys.stderr,
                    )
                    if attempt < 3:
                        await asyncio.sleep(5.0)
                        continue
                    return 3
                raw_text = resp.text
                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError as je:
                    (
                        OUTPUT_DIR
                        / f"voice_{voice_alias}_raw_body_retry_attempt{attempt}.txt"
                    ).write_text(raw_text)
                    print(f"Attempt {attempt}: JSON parse error: {je}", file=sys.stderr)
                    if attempt < 3:
                        await asyncio.sleep(5.0)
                        continue
                    return 4
                result = {
                    "alias": voice_alias,
                    "model": "google/gemini-2.5-pro",
                    "ok": True,
                    "elapsed_s": elapsed,
                    "attempt": attempt,
                    "data": data,
                }
                (OUTPUT_DIR / f"voice_{voice_alias}.json").write_text(
                    json.dumps(result, indent=2)
                )
                choices = data.get("choices", []) or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = msg.get("content") or msg.get("reasoning") or ""
                    if content:
                        (OUTPUT_DIR / f"voice_{voice_alias}_response.md").write_text(
                            content
                        )
                        print(
                            f"Attempt {attempt} OK: {len(content)} chars in {elapsed:.1f}s, finish={choices[0].get('finish_reason')}",
                            file=sys.stderr,
                        )
                        return 0
                print(f"Attempt {attempt}: empty content", file=sys.stderr)
                if attempt < 3:
                    await asyncio.sleep(5.0)
                    continue
                return 5
            except Exception as e:
                elapsed = asyncio.get_event_loop().time() - t0
                print(
                    f"Attempt {attempt}: exception in {elapsed:.1f}s: {e}",
                    file=sys.stderr,
                )
                if attempt < 3:
                    await asyncio.sleep(5.0)
                    continue
                return 6
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
