"""Evolution-quality review of the proposed Rule 2 synthesis for mutation/system.txt.

Three OpenRouter voices review whether the proposed Rule 2 produces memory cards
that BOOST EVOLUTION QUALITY downstream (not verbosity polish — that's already done).

- anthropic/claude-opus-4.1
- google/gemini-2.5-pro (with reasoning effort low, robust JSON parse fallback)
- openai/o3

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
    "/home/jovyan/gigaevo/output/mutation_prompt_evolution_quality_ensemble_20260524"
)
PROMPT_PATH = Path("/home/jovyan/gigaevo/gigaevo/prompts/mutation/system.txt")


SYNTHESIZED_RULE_2 = """\
2. **Each `changes[i].description` is a transfer brief, not a story.**
   FORMAT (exactly one `:`, delimiter between `<delta>` and `<why-it-transfers>`):
   - normal:           `<verb> <noun-phrase> <delta>: <why-it-transfers>`
   - identifier-first: `<noun-phrase> <verb> <delta>: <why-it-transfers>` (verb lowercase)
   Never use `:` inside `<noun-phrase>`, `<delta>`, or `<why-it-transfers>` (use `..` for ranges, not Python slice syntax).

   - `<verb>` (pick one; sentence-capitalized in normal form, lowercase in identifier-first form): `set | raised | lowered | swapped | added | removed | replaced | relaxed | tightened | perturbed | moved | rotated | reflected | scaled | projected | clipped | reordered | split | merged | rewrote | rewired`. No adverbs ("further", "adaptively"); don't echo the verb inside `<delta>`.
   - `<noun-phrase>`: code identifier (`learning_rate`), domain entity (`attacker_policy`), or array form — singleton `x[7]`, set `x[3,8]`, range `x[0..N]`, bare `matrix`. Name the slot even on swaps (`model`, `scorer`).
   - `<delta>` (use `->` only): `old->new` (scalar/swap), `none->behavior` (new mechanism), `axis->y` / `theta->15deg` / `grad-dir->σ=0.02` (geometric transform params), `old_label->new_label` (text/prompt rewrite, ≤8-token labels).
   - `<why-it-transfers>`: ≤20 words. MUST cite a concrete property from the TASK CONTEXT / METRICS sections at the bottom — a value bound (range, cap, threshold, support boundary), distribution shape (heavy-tail, sparse, multimodal, censored), inter-feature relation (correlation, hierarchy, grouping, paired coords), metric quirk (asymmetric penalty, saturation, outlier sensitivity), or domain constraint (physical, monotone, ordinal, sum-to-one) specific to THIS run. Forbidden: textbook lines that apply to any dataset (`models complex interactions`, `prevents overfitting`, `captures non-linear patterns`), metric restatements, preamble. Pure HP tunes with no dataset anchor must say so explicitly: `tunes <hp> for <model-family>; no dataset-property anchor`.
   - Hard cap: 140 characters (soft target 110). If you need more, split into multiple `changes[i]`.

   GOOD: `"Lowered CatBoost depth 7->6: shallow trees reduce variance on small feature sets."`
   GOOD: `"Perturbed points[7] grad-dir->σ=0.02: escapes triangle-min plateau."`
   GOOD: `"Rewrote query_rewriter_prompt baseline->entity-decomp: isolates hop entities."`
   GOOD: `"Replaced attacker_policy mirror->mixed-strategy: randomizes static defender."`
   BAD:  `"Extended hyperparameter tuning to further increase model capacity and optimize learning rate for convergence-stability balance; specifically increased iterations to 4000, depth to 6..."` (preamble, blended knobs, restates goal)
   BAD:  `"Set x[0] 0.123->0.124, x[1] 0.234->0.235, x[2] 0.345->0.347, ..."` (per-scalar items for a coherent vector perturbation — collapse into a single `points[0..N]` noun-phrase instead)

   BAD->GOOD pairs (textbook tautology → dataset-anchored specificity):
   BAD:  `"Raised depth 4->6: models complex non-linear interactions."` (textbook; applies to any dataset)
   GOOD: `"Raised depth 4->6: depth now matches the K-way feature interaction listed in TASK CONTEXT."`
   BAD:  `"Added log1p_transform none->target: prevents overfitting on heavy-tail."` (defensive cliché)
   GOOD: `"Added log1p_transform none->target: compresses the heavy-tail feature noted in TASK CONTEXT."`
   BAD:  `"Lowered learning_rate 0.1->0.05: improves convergence speed."` (generic HP cliché)
   GOOD: `"Lowered learning_rate 0.1->0.05: tunes lr for <model-family>; no dataset-property anchor."` (explicit no-anchor admission)
   BAD:  `"Clipped predictions 0->5: better represents the target."` (metric restatement)
   GOOD: `"Clipped predictions raw->[0,upper_bound]: aligns with the target's hard upper bound from TASK CONTEXT."`

   When ≥2 distinct knobs change together, emit ≥2 separate items in `changes`. A coherent vector perturbation across one named region is ONE item.
3. **`code` is Python source, not JSON** — no embedded JSON, templates, or format examples.
"""


def build_brief() -> str:
    surrounding_context = PROMPT_PATH.read_text()

    return f"""# Mutation Prompt — Evolution-Quality Review

You are reviewing the **proposed synthesis** of Rule 2 of GigaEvo's mutation operator prompt. The goal of this review is NOT verbosity polish (already done) but: **does this Rule 2 produce memory cards that BOOST EVOLUTION QUALITY downstream?**

## Card Pipeline (read first)

Mutation operator → each `changes[i].description` (text the operator writes) → downstream packager wraps it into a v4 packed-grammar memory card:

  `[UNVERIFIED_]<VERB> <target> [<old>→<new>]: <mechanism>; support=N; Δbest=+F; co=[t1,t2]`

The `<mechanism>` slot = the `<why-it-transfers>` clause from the description.
Cards accumulate over the run. Subsequent mutation calls see them in EVIDENCE INPUTS → "Memory Cards" (see line 19 of the surrounding context below). The mutator picks high-`support × Δbest` cards and transposes the mechanism into a new child program.

## What a USEFUL card delivers to the next mutator

- WHAT lever to touch — VERB + target (given by packed grammar)
- WHAT delta to apply — old→new (given)
- WHEN to apply it — `<mechanism>` must name the dataset property that triggers this lever
- HOW it works — `<mechanism>` must name the causal chain
- WHETHER it transfers — `<mechanism>` should name a property class recognizable on OTHER problems
- WHAT could break it / co-changes — implicit via UNVERIFIED prefix + co=[…] list

## The PROPOSAL under review (synthesized Rule 2 + Rule 3)

```
{SYNTHESIZED_RULE_2}
```

## Surrounding context (full current mutation/system.txt — pre-synthesis, for orientation only)

```
{surrounding_context}
```

## Your task (3 voices in parallel)

Forget verbosity. Focus PURELY on: **what would maximally boost downstream-evolution usefulness of the cards this Rule 2 produces?**

Specifically:

1. For each of the 4 BAD→GOOD pairs in the proposal: does the GOOD card give a future mutator everything they need to RE-APPLY this lever on a similar problem? If not, what's missing? Propose an improved GOOD version that increases evolutionary usefulness.

2. Is the 5-class property taxonomy (value bound, distribution shape, inter-feature relation, metric quirk, domain constraint) the right TAXONOMY for naming when-to-apply triggers? Add/remove/refine?

3. The escape hatch `tunes <hp> for <model-family>; no dataset-property anchor` — does this produce a USEFUL card for future mutators, or noise? Should the prompt instead REJECT no-anchor HP tunes entirely (forcing the mutator to find an anchor)?

4. The 4 kept GOOD examples (CatBoost depth, points[7] grad-dir, query_rewriter_prompt, attacker_policy) — does each model a card that a downstream mutator would benefit from? If not, replace.

5. Is there ANY OTHER addition (beyond the citation rule + char cap + BAD→GOOD pairs) that would BOOST card usefulness for evolution? Examples to consider: a "transfer condition" hint, an "expected reversal" caveat, a "minimum support to trust" note, a "co-change disambiguation" line, a "negative result" note when Δbest is small, a structured suffix like `;when=<trigger>`.

## Hard constraints

- Stay PROBLEM-AGNOSTIC. No California/Heilbron/HoVer-specific examples in your proposals — use placeholders or generic property-class language.
- The 4 load-bearing additions just made (citation rule, 140-char cap, BAD→GOOD pairs, escape hatch) are protected. You may REFINE them; do not REMOVE them wholesale.
- Schema field names (`changes[i].description`, `explanation`, etc.) are FROZEN.
- Stay inside Rule 2 + Rule 3 scope.

## Output format (STRICTLY valid JSON, no markdown fence around the JSON object)

{{
  "pair_assessment": [
    {{
      "pair_num": 1,
      "good_card_as_proposed": "...",
      "would_help_future_mutator": "yes | partial | no",
      "missing": "...",
      "improved_version": "..."
    }}
  ],
  "property_class_taxonomy_review": {{
    "verdict": "keep_as_is | refine | replace",
    "suggested_changes": "..."
  }},
  "escape_hatch_verdict": {{
    "verdict": "keep | replace | reject_entirely",
    "reasoning": "...",
    "if_replace_or_reject_what_to_do": "..."
  }},
  "good_examples_review": [
    {{
      "example": "...",
      "useful_for_future_mutator": "yes | no",
      "reasoning": "..."
    }}
  ],
  "additional_card_boosters": [
    {{
      "proposal": "...",
      "would_boost_evolution_because": "..."
    }}
  ],
  "top_3_changes_to_maximize_evolution_quality": ["...", "...", "..."],
  "notes": "..."
}}

Be specific and ruthless. Cite which line of the proposal you're commenting on. Propose CONCRETE replacements, not abstract critique.
"""


async def call_openrouter(
    client: httpx.AsyncClient, voice: dict, api_key: str, brief: str, attempt: int = 1
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "mutation-prompt-evolution-quality-ensemble",
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
                "attempt": attempt,
            }
        raw_text = resp.text
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as je:
            (
                OUTPUT_DIR / f"voice_{voice['alias']}_raw_body_attempt{attempt}.txt"
            ).write_text(raw_text)
            if attempt < 2:
                await asyncio.sleep(2.0)
                return await call_openrouter(
                    client, voice, api_key, brief, attempt=attempt + 1
                )
            return {
                "alias": voice["alias"],
                "model": voice["model"],
                "ok": False,
                "error": f"JSON parse error after {attempt} attempts: {je}; raw body saved",
                "elapsed_s": elapsed,
                "attempt": attempt,
                "raw_body_head": raw_text[:500],
                "raw_body_tail": raw_text[-500:],
            }
        return {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": True,
            "elapsed_s": elapsed,
            "attempt": attempt,
            "data": data,
        }
    except Exception as e:
        return {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": False,
            "error": str(e),
            "elapsed_s": asyncio.get_event_loop().time() - t0,
            "attempt": attempt,
        }


async def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY missing", file=sys.stderr)
        return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    brief = build_brief()
    (OUTPUT_DIR / "ensemble_brief.md").write_text(brief)
    (OUTPUT_DIR / "synthesized_rule_2_under_review.txt").write_text(SYNTHESIZED_RULE_2)

    voices = [
        {
            "alias": "anthropic_opus",
            "model": "anthropic/claude-opus-4.1",
            "extra": {"extra_body": {"reasoning": {"effort": "high"}}},
        },
        {
            "alias": "google_gemini25",
            "model": "google/gemini-2.5-pro",
            "extra": {"extra_body": {"reasoning": {"effort": "low"}}},
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
            "attempt": result.get("attempt"),
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
