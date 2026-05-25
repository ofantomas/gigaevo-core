"""Final 3-voice ensemble check on the stripped mutation prompt.

Brief includes the FULL final prompt + downstream-parser evidence so reviewers
do NOT re-propose the format/grammar scaffolding that the user explicitly
asked to strip and that the parser doesn't consume.

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
    "/home/jovyan/gigaevo/output/mutation_prompt_sota_final_check_20260524"
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


BRIEF = r"""You are reviewing the FINAL revision of a mutation-operator system prompt for an LLM-guided evolutionary code-optimization framework (GigaEvo).

# Goal of the prompt

The mutation operator emits `changes[i].description` strings that flow into a global memory bank (cards) consumed by future mutation calls. Card quality determines whether the algorithm transfers learned levers across problems. We want cards that are:

- **Helpful** — teach the mutator a real mechanism, not just "what changed".
- **Not bloated** — short, no scaffolding, no fluff.
- **Transferrable** — encode a *falsifiable causal hypothesis* that fires on the right problem property, not on the action taken.

# Recent history (IMPORTANT — please do not re-propose what was deliberately stripped)

A previous 3-voice ensemble (Opus 4.1, o3, Gemini 2.5 Pro) reviewed an earlier draft and converged on FORMAT-tightening edits: hard-require numeric-anchor regex, ban `;` / `,` / `and` joins, expand the verb allowlist, etc.

The user (a senior ML researcher running GigaEvo) pushed back:

> "why do we have some insane grammar rules on that. how are they useful? we over engineered clearly"
> "Let us remove grammar rules and rather keep actually useful things because mutation prompt becomes bloated"

I then investigated the downstream parser and confirmed the format scaffolding was cargo-cult. Verbatim evidence:

```python
# gigaevo/memory/ideas_tracker/idea_bank.py:99-106
_PACKED_RE = re.compile(
    r"^(?P<verb>ADD|REMOVE|UPDATE|SWAP|USE)\s+(?P<target>[^:]+?)\s*:\s*(?P<mechanism>.+)$"
)
# ↑ Only 5 verbs are recognized. Prompt was teaching 21.

# gigaevo/memory/ideas_tracker/idea_bank.py:362-369
def enrich_with_verification(desc: str, ...) -> str:
    parsed = parse_packed_description(desc)
    if parsed is None:
        return desc  # passthrough — any free-form text is accepted as-is
    ...

# gigaevo/memory/shared_memory/amem_gam_retriever.py:39
def make_card_text(card) -> str:
    return f"description: {card.description}"  # no transform
```

Schema enforcement upstream is also minimal:

```python
# gigaevo/llm/agents/mutation.py
class MutationChange(BaseModel):
    description: str
    explanation: str
    # No regex, no max_length, no field validator.
```

Conclusion: the 21-verb allowlist, single-`:` invariant, `..` vs `:` slice notation, 5-shape `<delta>` menu, casing rules, 140-char cap, noun-phrase form enumeration, and filler-word list were **prompt-side only**. The parser ignores them. They were teaching the LLM rules nobody downstream enforced.

# What I deleted from Rule 2

- 21-verb allowlist + normal-form / identifier-first casing rules
- Single-`:` invariant + `..` vs `:` slice notation
- 5-shape `<delta>` menu (scalar / component / none→named / transform-param / prior_label)
- Noun-phrase form enumeration (singleton / set / range / bare)
- 140-character hard cap
- "No further/adaptively/leverage/…" filler-word list
- 3 of 8 GOOD examples (RF→CatBoost, reflect-axis, attacker_policy) — kept the most diverse 5
- 2 of 3 standalone BAD examples — kept only the per-scalar-items pitfall
- 1 of 4 BAD→GOOD pairs (depth tautology — same pattern is already in the kept GOOD example)

# What I kept in Rule 2

- Falsifiable causal hypothesis framing
- Tautology test ("would the clause still be true if the cited property were absent?")
- Failure-mode bypass / Constraint match patterns
- 8 trigger source classes + numeric-anchor preference
- Forbidden list (tautology / diff-restatement / goal-restatement)
- `weak transfer-evidence` escape hatch for HP tunes with no problem-property hypothesis
- ≥2 knobs → ≥2 items rule
- 5 GOOD examples spanning 5 domains: ML-HP (depth), numerical-method (jitter), discrete-geometry (perturb), NLP-retrieve (retrieval_k), prompt-rewrite (query_rewriter)
- 3 BAD→GOOD pairs: target_log_transform (real card defect), perturb (goal-restatement), learning_rate (escape-hatch usage)

# THE FULL FINAL PROMPT (the artifact you are reviewing)

```
%%PROMPT%%
```

# Your task

Answer ONLY these questions — do not re-propose format / grammar / regex / character-cap rules (parser doesn't consume them, user rejected them):

1. **Content-rule sufficiency**: Does Rule 2 give an LLM enough teaching signal to write *falsifiable causal hypothesis* descriptions consistently? Or is some load-bearing teaching signal missing after the strip?

2. **Over-cut detection**: Did the strip delete anything that was NOT cargo-cult format scaffolding but was actually teaching CONTENT? Be specific: cite the deleted item and the teaching signal it carried.

3. **Remaining bloat**: With format scaffolding gone, is there still bloat *in the content rules themselves* or elsewhere in the prompt? Cite specific lines, not vibes.

4. **Example coverage**: Do the 5 GOOD + 3 BAD→GOOD examples span enough patterns to teach the mutator robustly? Is a critical pattern under-represented?

5. **Verdict** (pick exactly one): `SHIP` / `MINOR_TWEAKS` / `OVER_CUT` / `STILL_BLOATED`.

Output a single JSON object (no markdown fences, no prose preamble) with these fields:

```
{
  "content_rule_sufficiency": {"sufficient": bool, "missing_teaching_signal": [string, ...]},
  "over_cut": [{"deleted_item": string, "teaching_signal_lost": string, "suggested_recovery": string}, ...],
  "remaining_bloat": [{"line_or_clause": string, "why_bloat": string, "cut_proposal": string}, ...],
  "example_coverage": {"adequate": bool, "gaps": [string, ...]},
  "verdict": "SHIP" | "MINOR_TWEAKS" | "OVER_CUT" | "STILL_BLOATED",
  "top_3_actionable_edits": [{"rank": int, "old_string": string, "new_string": string, "rationale": string}, ...]
}
```

Be ruthless and specific. Cite exact text fragments from the FINAL PROMPT above. Aim for surgical edits, not rewrites. If verdict is `SHIP`, `top_3_actionable_edits` is `[]`.
"""


async def call_voice(
    client: httpx.AsyncClient, voice: dict, brief: str, api_key: str
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "mutation-prompt-final-check",
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
