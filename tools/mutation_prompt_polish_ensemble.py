"""Polish ensemble for mutation/system.txt Rule 2 (memory-card-building section).

Three OpenRouter voices critique the post-patch mutation prompt:
- anthropic/claude-opus-4.1
- google/gemini-2.5-pro
- openai/o3

Goal: trade verbosity reduction off against the 4 load-bearing additions just made.

Squid proxy MUST be active for openai/o3 (region-blocked direct egress).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import httpx

OUTPUT_DIR = Path(
    "/home/jovyan/gigaevo/output/mutation_prompt_polish_ensemble_20260524"
)
PROMPT_PATH = Path("/home/jovyan/gigaevo/gigaevo/prompts/mutation/system.txt")


def build_brief() -> str:
    prompt_text = PROMPT_PATH.read_text()

    intro = """# Mutation Prompt Polish Ensemble

You are reviewing the **memory-card-building section** (Rule 2 of OUTPUT RULES, roughly lines 65-99 post-patch) of GigaEvo's mutation operator prompt. The full file is below. Three voices (you, plus two others in parallel) will propose tightenings; we will synthesize.

## Mission

Polish Rule 2 for **SOTA memory prompting**. Each `changes[i].description` produced by this prompt propagates **as the `<mechanism>` slot of v4 packed-grammar memory cards** of the form `[UNVERIFIED_]<VERB> <target> [<old>->-<new>]: <mechanism>; support=N; Δbest=+F; co=[t1,t2]`. Those cards are recycled back into subsequent mutation calls as "Memory Cards" evidence (see EVIDENCE INPUTS line 19). The quality of the mechanism text directly drives the quality of every downstream card.

## Hard constraints (NON-NEGOTIABLE)

1. **Problem-agnostic** — this prompt serves ALL problems (tabular_regression, heilbron, hover, future). Do NOT propose examples or rules specific to any single problem (no California-Housing values, no Heilbron-specific terminology, no model-family-specific terms unless using a `<model-family>` placeholder). Use placeholders or abstract property-class names.

2. **Four load-bearing additions just made — DO NOT REMOVE**:
   a) The `<why-it-transfers>` citation rule (lists 5 property classes — value bound, distribution shape, inter-feature relation, metric quirk, domain constraint — and forbids textbook tautologies).
   b) The char cap 140 / soft 110 (replaced the previous 100/80 to accommodate the 20-word ceiling).
   c) The BAD->GOOD pairs block (4 paired examples teaching tautology->specificity).
   d) The escape-hatch `tunes <hp> for <model-family>; no dataset-property anchor` for pure HP tunes with no dataset anchor.

3. **Don't propose touching anything OUTSIDE Rule 2** (lines 65-99 post-patch). Other sections (ROLE, EVIDENCE INPUTS, ARCHETYPE, EXECUTION PRINCIPLES, CONTEXT injection) are out of scope.

4. **Schema field names + types are FROZEN** (external GAM contract). Do not propose renaming/adding fields.

## Verbosity goal

Current Rule 2 post-patch: roughly 35-37 lines.
Target: 28-32 lines (>=10% leaner), ideally even tighter, while keeping all 4 load-bearing additions intact.
Method: find collapsible redundancy in:
- The verb whitelist paragraph — currently 20+ verbs in prose
- The delta-shapes paragraph — five sub-bullets, possibly compressible
- The noun-phrase paragraph — verbose enumeration of forms
- The existing GOOD example list — 7 examples; can some be merged or dropped if redundant with the new BAD->GOOD pairs?

## Per-voice ask (output as structured JSON)

Output STRICTLY valid JSON (no markdown fences around the JSON object) with these fields:
- `redundancies_flagged`: list of objects, each with `location` (which line/paragraph), `what` (the redundancy), and `compressed_form` (your proposed tighter version)
- `proposed_rewrite_of_rule_2`: full proposed text of Rule 2 (from "Each `changes[i].description` is a transfer brief..." through "code is Python source, not JSON" inclusive)
- `load_bearing_check`: object with four boolean fields — `citation_rule_preserved`, `char_cap_140_preserved`, `bad_good_pairs_preserved`, `escape_hatch_preserved`
- `word_count_old`: int (your count for the current Rule 2)
- `word_count_new`: int (your count for the proposed rewrite)
- `line_count_old`: int
- `line_count_new`: int
- `notes`: string (caveats, alternative cuts considered, or concerns)

## The post-patch mutation/system.txt (full file)

```
"""
    outro = """
```

Now produce your structured JSON review. Be ruthless on redundancy but surgical — don't reword what's already tight.
"""
    return intro + prompt_text + outro


async def call_openrouter(
    client: httpx.AsyncClient, voice: dict, api_key: str, brief: str
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "mutation-prompt-polish-ensemble",
    }
    body = {
        "model": voice["model"],
        "max_tokens": 40000,
        "messages": [{"role": "user", "content": brief}],
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    brief = build_brief()
    (OUTPUT_DIR / "ensemble_brief.md").write_text(brief)

    voices = [
        {
            "alias": "anthropic_opus",
            "model": "anthropic/claude-opus-4.1",
            "extra": {"extra_body": {"reasoning": {"effort": "high"}}},
        },
        {
            "alias": "google_gemini25",
            "model": "google/gemini-2.5-pro",
            "extra": {},
        },
        {
            "alias": "openai_o3",
            "model": "openai/o3",
            "extra": {"reasoning_effort": "medium"},
        },
    ]

    proxy = os.environ.get("HTTPS_PROXY")
    async with httpx.AsyncClient(proxy=proxy) as client:
        results = await asyncio.gather(
            *[call_openrouter(client, v, api_key, brief) for v in voices]
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

    (OUTPUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
