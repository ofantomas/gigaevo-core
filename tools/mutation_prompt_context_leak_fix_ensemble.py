"""3-voice ensemble check on the 'in CONTEXT' scaffolding-leakage fix.

User observation that triggered this: the mutation operator emitted output like
`Extended alpha continuation schedule 4000->10000: n=600, d=11 in CONTEXT creates ...`
The literal phrase `in CONTEXT` was being parroted from the GOOD examples.

Fix: stripped all `in CONTEXT` / `(CONTEXT)` scaffolding tokens from examples in
gigaevo/prompts/mutation/system.txt, restating each clause to name the actual
problem property directly (no scaffolding word).

This script verifies: (a) leakage path actually cut, (b) citation discipline
preserved, (c) no new ambiguity introduced.

Voices: Opus 4.1, o3, Gemini 2.5 Pro via OpenRouter (HTTPS_PROXY = Squid).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import httpx

OUTPUT_DIR = Path(
    "/home/jovyan/gigaevo/output/mutation_prompt_context_leak_fix_20260524"
)
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

PROMPT_PATH = Path("/home/jovyan/gigaevo/gigaevo/prompts/mutation/system.txt")

VOICES = [
    {
        "alias": "anthropic_opus",
        "model": "anthropic/claude-opus-4.1",
        "via": "extra_body",
        "effort": "high",
    },
    {
        "alias": "openai_o3",
        "model": "openai/o3",
        "via": "reasoning_effort",
        "effort": "high",
    },
    {
        "alias": "google_gemini25",
        "model": "google/gemini-2.5-pro",
        "via": "extra_body",
        "effort": "medium",
    },
]


BRIEF = r"""You are reviewing a small targeted fix to a mutation-operator system prompt for an LLM-guided evolutionary code-optimization framework (GigaEvo).

# Context

The mutation operator emits `changes[i].description` strings that flow into a global memory bank consumed by future mutation calls. Cards must be falsifiable causal hypotheses citing real problem properties.

# The leakage observation that triggered this fix

A senior ML researcher running production GigaEvo observed mutation output containing the phrase:

> `Extended alpha continuation schedule 4000->10000: n=600, d=11 in CONTEXT creates ...`

The literal scaffold-word **CONTEXT** is being verbatim-parroted into output. The model is mimicking the surface form of the GOOD examples rather than understanding the citation discipline.

# Root cause (verified in source)

The GOOD examples in the prompt used `<value> in CONTEXT` / `(CONTEXT)` phrasing. Specifically the OLD examples were:

```
GOOD: "Lowered CatBoost depth 7->6: feature_count=8 in CONTEXT — depth 7 saturates expressivity; deeper trees fit val noise."
GOOD: "Raised retrieval_k 3->5: query_avg_entities=4 in CONTEXT — k=3 truncates before the 4th-hop bridge entity."
GOOD: "Rewrote query_rewriter_prompt baseline->entity-decomp: queries in CONTEXT need ≥2 lookups; baseline issues one shot."
GOOD: "Removed target_log_transform log->raw: target hard-capped at 5.0 (CONTEXT) flattens log-loss near saturation; raw restores gradient."
```

The model sees 4 examples with `in CONTEXT` / `(CONTEXT)`, learns it's part of the "good output format", and emits it on inputs that don't even have those properties listed in their CONTEXT section.

This matches a prior team feedback rule: *"Don't embed specific numerics or scaffold tokens in prompts — they leak as hallucinated outputs."*

# The fix (already applied, in the prompt below)

Stripped `in CONTEXT` and `(CONTEXT)` from all 5 GOOD examples + 1 BAD->GOOD pair. Restated each clause to name the actual property directly:

```
NEW: "Lowered CatBoost depth 7->6: feature_count=8 saturates depth-7 expressivity; deeper trees fit val noise."
NEW: "Raised retrieval_k 3->5: query_avg_entities=4 — k=3 truncates before the 4th-hop bridge entity."
NEW: "Rewrote query_rewriter_prompt baseline->entity-decomp: task queries need ≥2 entity lookups; baseline issues one shot."
NEW: "Removed target_log_transform log->raw: target hard-capped at 5.0 flattens log-loss near saturation; raw restores gradient."
```

NOTE preserved elsewhere in the prompt (intentional, not output examples — internal label):
- Section header `## CONTEXT (the TASK the PROGRAM is solving — background ...)`
- Rule sentence `Draw the trigger from TASK CONTEXT / METRICS (or run stats ...)`

These are instructions/headers; they don't appear inside example output strings, so they aren't a leakage vector.

# THE FULL CURRENT PROMPT (post-fix — the artifact you are reviewing)

```
%%PROMPT%%
```

# Your task

Answer ONLY these 3 questions. Be ruthless and specific. Cite exact line fragments. Do NOT propose re-adding format/grammar/regex rules (already explicitly rejected by user).

1. **Leakage path cut?** Did the fix actually break the verbatim-parroting failure mode? Is there any other place in the prompt where the literal token `CONTEXT` could be picked up and parroted into a `changes[i].description` string? (Reminder: section headers and instructions are FINE — only example output strings are leakage vectors.)

2. **Citation discipline preserved?** The OLD `in CONTEXT` phrasing taught the model *where to look for the property* (the CONTEXT section). After stripping that phrase, do the NEW examples still teach the model to cite real problem properties (not invent them)? Or has the strip weakened the "cite, don't invent" signal?

3. **New ambiguity introduced?** Specifically: by deleting `in CONTEXT — depth 7 saturates ...` → `saturates depth-7 ...`, did we accidentally make the example less parsable? Does it still clearly show the *failure-mode-bypass* / *constraint-match* pattern from Rule 2? Cite specific examples that look wobbly.

**Verdict** (pick exactly one): `FIX_GOOD` / `FIX_INSUFFICIENT` / `FIX_BROKE_TEACHING`.

Output a single JSON object (no markdown fences, no prose preamble) with these fields:

```
{
  "leakage_path_cut": {"cut": bool, "remaining_leakage_vectors": [{"location": string, "why_risky": string}, ...]},
  "citation_discipline_preserved": {"preserved": bool, "evidence": string, "weakening_concerns": [string, ...]},
  "new_ambiguity": {"introduced": bool, "wobbly_examples": [{"example_quote": string, "ambiguity_concern": string}, ...]},
  "verdict": "FIX_GOOD" | "FIX_INSUFFICIENT" | "FIX_BROKE_TEACHING",
  "surgical_followup_edits": [{"old_fragment": string, "new_fragment": string, "rationale": string}, ...]
}
```

Aim for at most 3 surgical follow-up edits. If verdict is `FIX_GOOD`, `surgical_followup_edits` is `[]`.
"""


async def call_voice(
    client: httpx.AsyncClient, voice: dict, brief: str, api_key: str
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "mutation-prompt-context-leak-fix",
    }
    body = {
        "model": voice["model"],
        "max_tokens": 60000,
        "messages": [{"role": "user", "content": brief}],
    }
    if voice["via"] == "extra_body":
        body["extra_body"] = {"reasoning": {"effort": voice["effort"]}}
    else:
        body["reasoning_effort"] = voice["effort"]

    alias = voice["alias"]
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
                    f"[{alias}] attempt {attempt}: HTTP {resp.status_code} in {elapsed:.1f}s; body[:300]={resp.text[:300]}",
                    file=sys.stderr,
                )
                if attempt < 3:
                    await asyncio.sleep(5.0)
                    continue
                return {
                    "alias": alias,
                    "ok": False,
                    "error": f"HTTP {resp.status_code}",
                    "body_head": resp.text[:1000],
                }
            raw_text = resp.text
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError as je:
                (
                    OUTPUT_DIR / f"voice_{alias}_raw_body_attempt{attempt}.txt"
                ).write_text(raw_text)
                print(
                    f"[{alias}] attempt {attempt}: JSON parse error: {je}",
                    file=sys.stderr,
                )
                if attempt < 3:
                    await asyncio.sleep(5.0)
                    continue
                return {"alias": alias, "ok": False, "error": f"JSON parse: {je}"}
            choices = data.get("choices") or []
            if not choices:
                if attempt < 3:
                    await asyncio.sleep(5.0)
                    continue
                return {"alias": alias, "ok": False, "error": "no choices"}
            msg = choices[0].get("message") or {}
            content = msg.get("content") or msg.get("reasoning") or ""
            if not content:
                if attempt < 3:
                    await asyncio.sleep(5.0)
                    continue
                return {"alias": alias, "ok": False, "error": "empty content"}
            (OUTPUT_DIR / f"voice_{alias}_response.md").write_text(content)
            return {
                "alias": alias,
                "model": voice["model"],
                "ok": True,
                "elapsed_s": elapsed,
                "attempt": attempt,
                "finish_reason": choices[0].get("finish_reason"),
                "content_chars": len(content),
            }
        except Exception as e:
            elapsed = asyncio.get_event_loop().time() - t0
            print(
                f"[{alias}] attempt {attempt}: exception in {elapsed:.1f}s: {e}",
                file=sys.stderr,
            )
            if attempt < 3:
                await asyncio.sleep(5.0)
                continue
            return {"alias": alias, "ok": False, "error": str(e)}
    return {"alias": alias, "ok": False, "error": "exhausted retries"}


async def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY missing", file=sys.stderr)
        return 2

    proxy = os.environ.get("HTTPS_PROXY")
    full_prompt = PROMPT_PATH.read_text()
    brief = BRIEF.replace("%%PROMPT%%", full_prompt)
    (OUTPUT_DIR / "ensemble_brief.md").write_text(brief)
    print(f"Brief size: {len(brief) / 1024:.1f} KB", file=sys.stderr)

    async with httpx.AsyncClient(proxy=proxy) as client:
        results = await asyncio.gather(
            *(call_voice(client, v, brief, api_key) for v in VOICES),
            return_exceptions=False,
        )

    (OUTPUT_DIR / "ensemble_summary.json").write_text(json.dumps(results, indent=2))
    ok_count = sum(1 for r in results if r.get("ok"))
    print(f"\n=== {ok_count}/{len(VOICES)} voices succeeded ===", file=sys.stderr)
    for r in results:
        print(
            f"  {r['alias']}: ok={r.get('ok')} chars={r.get('content_chars')} time={r.get('elapsed_s')} attempt={r.get('attempt')}",
            file=sys.stderr,
        )
    return 0 if ok_count == len(VOICES) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
