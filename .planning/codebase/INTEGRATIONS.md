# External Integrations

## LLM Services
| Service | Endpoint | Purpose |
|---------|----------|---------|
| **LiteLLM Proxy** | `http://localhost:8000/v1` | Central proxy for all LLM requests |
| **OpenAI-compatible API** | Various backend servers | Mutation, chain evaluation, insights |
| **Model**: Qwen3-235B-A22B-Thinking-2507 | Via LiteLLM | Primary mutation + evaluation model |

- Client: `openai` SDK with `httpx` transport
- Auth: `OPENAI_API_KEY=sk-gigaevo` (local key for LiteLLM proxy)
- Config: `gigaevo/infra/balanced_chat.py` handles request routing
- Timeout: 600s request timeout, 0.6 temperature, 81920 max_tokens
- Connection: `NO_PROXY` must include all server IPs (handled by `tools/no_proxy.py`)

## Redis
| Config | Value |
|--------|-------|
| **Host** | `localhost:6379` |
| **DBs** | 0-15 (16 total, one per run) |
| **Client** | `redis-py` with async support |
| **Connection pool** | 150 max connections, 45s timeout |
| **Health check** | Every 120s |

- Used for: program storage, run state, metrics history, MAP-Elites archive, distributed locks
- Key schema: `{prefix}:{namespace}:{id}` (documented in `tools/README.md`)
- Mock: `fakeredis[lua]` for testing

## GitHub
| Integration | Tool |
|-------------|------|
| **PR management** | `gh pr create/edit/comment/merge` |
| **Releases** | `gh release create/upload` (run archives) |
| **Issues** | Project board tracking via `tools/experiment/` |

- All GitHub ops via `gh` CLI (not API directly)
- Merge policy: `--merge --delete-branch` (never squash)
- Release naming: `exp/<task>/<name>` tags

## Telegram Notifications
- Module: `tools/telegram_notify.py`
- Functions: `notify(message)`, `send_photo(path, caption)`
- Uses `requests` library with `HTTPS_PROXY`
- Proxy: `https://623:hvtiloi3Oxdr@xy.2a2i.org:4443` (required — server can't reach api.telegram.org directly)
- Used by: watchdog processes for hourly status + plot delivery

## GitNexus Code Intelligence
- MCP server integration for code graph queries
- Tools: `gitnexus_query`, `gitnexus_context`, `gitnexus_impact`, `gitnexus_detect_changes`, `gitnexus_rename`
- Index: 24942 symbols, 66235 relationships, 300 execution flows
- Auto-refresh hook after git commit/merge

## Claude Code Automation
- Skills: `.claude/skills/*/SKILL.md` (experiment lifecycle, testing, scheduling)
- Agents: `.claude/agents/*.md` (design reviewers, checkpoint analysts, code archaeologists)
- Crons: anomaly detection (2h), checkpoint (4h) via `CronCreate`
- Hooks: PostToolUse hooks for GitNexus refresh, RTK proxying

## LiteLLM Proxy
- Script: `tools/litellm.sh` (start/stop/status)
- Benchmarking: `tools/litellm_bench.py`
- Handles model routing across multiple GPU servers
- Server inventory: `experiments/infrastructure.yaml`

## File System
- NFS-mounted workspace at `/mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/`
- Hydra outputs: relative to CWD (must launch from project root)
- Log rotation: 50 MB per file, 30 days retention
