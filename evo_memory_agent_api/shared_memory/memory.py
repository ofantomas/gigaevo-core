from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from dotenv import load_dotenv

_THIS_DIR = Path(__file__).resolve().parent
_AGENT_ROOT = _THIS_DIR.parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from A_mem.agent.agent_class import LLMService

import config

load_dotenv()

if TYPE_CHECKING:
    from A_mem.agentic_memory.memory_system import AgenticMemorySystem, MemoryNote
    from GAM_root.gam import ResearchAgent
    from GAM_root.gam.generator import AMemGenerator


_ALLOWED_STRATEGIES = {"exploration", "exploitation", "hybrid"}
_VECTOR_GAM_TOOLS = {
    "vector",
    "vector_description",
    "vector_task_description",
    "vector_explanation_summary",
}
_ALLOWED_GAM_TOOLS = {
    "keyword",
    "page_index",
    *_VECTOR_GAM_TOOLS,
}
_ALLOWED_GAM_PIPELINE_MODES = {"default", "experimental"}
_DEFAULT_GAM_TOP_K_BY_TOOL = {
    "keyword": 5,
    "vector": 5,
    "vector_description": 5,
    "vector_task_description": 5,
    "vector_explanation_summary": 5,
    "page_index": 5,
}


def _to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_memory_card(
    card: dict[str, Any] | None = None,
    fallback_id: str | None = None,
) -> dict[str, Any]:
    raw = dict(card or {})
    explanation = raw.get("explanation")
    if not isinstance(explanation, dict):
        explanation = {}

    return {
        "id": str(raw.get("id") or fallback_id or ""),
        "category": str(raw.get("category") or "general"),
        "description": str(raw.get("description") or raw.get("content") or ""),
        "task_description": str(raw.get("task_description") or raw.get("context") or ""),
        "strategy": str(raw.get("strategy") or ""),
        "last_generation": _to_int(raw.get("last_generation"), default=0),
        "programs": _to_list(raw.get("programs")),
        "aliases": _to_list(raw.get("aliases")),
        "keywords": _to_list(raw.get("keywords")),
        "evolution_statistics": (
            raw.get("evolution_statistics")
            if isinstance(raw.get("evolution_statistics"), dict)
            else {}
        ),
        "explanation": {
            "explanations": _to_list(explanation.get("explanations")),
            "summary": str(explanation.get("summary") or ""),
        },
        "works_with": _to_list(raw.get("works_with")),
        "links": _to_list(raw.get("links")),
        "usage": raw.get("usage") if isinstance(raw.get("usage"), dict) else {},
    }


def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _memory_to_card(
    memory_note: Any,
    base_card: dict[str, Any] | None = None,
    memory_id: str | None = None,
) -> dict[str, Any]:
    mem_id = _safe_get(memory_note, "id", None) or memory_id
    card = normalize_memory_card(base_card, fallback_id=mem_id)
    if memory_note is None:
        return card

    card["id"] = str(mem_id or card["id"])
    card["category"] = str(card.get("category") or _safe_get(memory_note, "category", None) or "general")
    card["description"] = str(card.get("description") or _safe_get(memory_note, "content", ""))
    card["task_description"] = str(card.get("task_description") or _safe_get(memory_note, "context", ""))
    card["strategy"] = str(card.get("strategy") or _safe_get(memory_note, "strategy", ""))
    card["keywords"] = _to_list(_safe_get(memory_note, "keywords", []) or [])

    if not card.get("links"):
        card["links"] = (
            _safe_get(memory_note, "links", None)
            or _safe_get(memory_note, "linked_memories", None)
            or _safe_get(memory_note, "linked_ids", None)
            or _safe_get(memory_note, "relations", None)
            or []
        )
    card["links"] = _to_list(card["links"])

    return card


def _export_memories_jsonl(
    memory_system: Any,
    memory_ids: list[str],
    out_path: Path,
    card_overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    card_overrides = card_overrides or {}

    unique_ids = list(dict.fromkeys(memory_ids))
    with out_path.open("w", encoding="utf-8") as file_obj:
        for memory_id in unique_ids:
            memory_note = memory_system.read(memory_id)
            base_card = card_overrides.get(memory_id)
            if memory_note is None and base_card is None:
                continue
            record = _memory_to_card(memory_note, base_card=base_card, memory_id=memory_id)
            file_obj.write(json.dumps(record, ensure_ascii=True) + "\n")


class GigaEvoMemoryBase:
    def save(self, data: str) -> str:
        raise NotImplementedError

    def search(self, query: str) -> str:
        raise NotImplementedError

    def delete(self, memory_id: str) -> bool:
        raise NotImplementedError


class _ConceptApiClient:
    """Small HTTP client around concept endpoints from the main API service."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            host = str(self._http.base_url).rstrip("/")
            raise RuntimeError(
                f"Cannot connect to Memory API at {host}. "
                "Start the API service or set MEMORY_API_URL to a reachable endpoint."
            ) from exc
        except httpx.TimeoutException as exc:
            host = str(self._http.base_url).rstrip("/")
            raise RuntimeError(
                f"Memory API request timed out for {host}. "
                "Check service health and network connectivity."
            ) from exc
        if response.status_code == 204:
            return None
        if response.status_code >= 400:
            raise RuntimeError(
                f"Memory API request failed ({method} {path}): "
                f"{response.status_code} {response.text}"
            )
        return response.json()

    def save_concept(
        self,
        *,
        content: dict[str, Any],
        name: str,
        tags: list[str],
        when_to_use: str,
        channel: str,
        namespace: str | None,
        author: str | None,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "meta": {
                "name": name,
                "tags": tags,
                "when_to_use": when_to_use,
                "namespace": namespace,
                "author": author,
            },
            "channel": channel,
            "content": content,
        }
        if entity_id:
            result = self._request("PUT", f"/v1/concepts/{entity_id}", json=body)
        else:
            result = self._request("POST", "/v1/concepts", json=body)
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected empty response from concept save")
        return result

    def get_concept(self, entity_id: str, channel: str = "latest") -> dict[str, Any]:
        result = self._request("GET", f"/v1/concepts/{entity_id}", params={"channel": channel})
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected empty response from concept get")
        return result

    def search_concepts(
        self,
        *,
        query: str | None,
        limit: int,
        namespace: str | None,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "entity_type": "concept",
            "limit": limit,
            "offset": offset,
        }
        if namespace:
            params["namespace"] = namespace
        query_text = str(query or "").strip()
        if query_text:
            params["q"] = query_text
        result = self._request("GET", "/v1/search", params=params) or {}
        if not isinstance(result, dict):
            return {"hits": [], "total": 0}
        return {
            "hits": list(result.get("hits", [])),
            "total": int(result.get("total", 0) or 0),
        }

    def delete_concept(self, entity_id: str) -> None:
        self._request("DELETE", f"/v1/concepts/{entity_id}")


class AmemGamMemory(GigaEvoMemoryBase):
    """API-backed memory where API is the source of truth and local GAM is retrieval runtime."""

    def __init__(
        self,
        checkpoint_path: str,
        base_url: str = "http://localhost:8000",
        use_api: bool = True,
        namespace: str = "default",
        author: str | None = None,
        channel: str = "latest",
        search_limit: int = 5,
        enable_llm_synthesis: bool = True,
        enable_memory_evolution: bool = True,
        enable_llm_card_enrichment: bool = True,
        rebuild_interval: int = 10,
        enable_bm25: bool = False,
        sync_batch_size: int = 100,
        sync_on_init: bool = True,
        allowed_gam_tools: list[str] | None = None,
        gam_top_k_by_tool: dict[str, int] | None = None,
        gam_pipeline_mode: str = "default",
    ):
        self.checkpoint_dir = Path(checkpoint_path)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.checkpoint_dir / "api_index.json"
        self.export_file = self.checkpoint_dir / "amem_exports" / "amem_memories.jsonl"
        self.gam_store_dir = self.checkpoint_dir / "gam_shared" / "amem_store"

        self.use_api = bool(use_api)
        self.namespace = namespace
        self.author = author
        self.channel = channel
        self.search_limit = search_limit
        self.rebuild_interval = rebuild_interval
        self.enable_bm25 = enable_bm25
        self.sync_batch_size = max(10, int(sync_batch_size))
        self.enable_llm_synthesis = enable_llm_synthesis
        self.enable_memory_evolution = bool(enable_memory_evolution)
        self.enable_llm_card_enrichment = bool(enable_llm_card_enrichment)
        self.allowed_gam_tools = self._normalize_allowed_gam_tools(allowed_gam_tools)
        self.gam_top_k_by_tool = self._normalize_gam_top_k_by_tool(gam_top_k_by_tool)
        self.gam_pipeline_mode = self._normalize_gam_pipeline_mode(gam_pipeline_mode)
        self._iters_after_rebuild = 0

        self.api: _ConceptApiClient | None = None
        if self.use_api:
            self.api = _ConceptApiClient(base_url=base_url)
        else:
            print("[Memory] API mode disabled. Running in local-only mode.")

        self._AgenticMemorySystemCls: type[Any] | None = None
        self._MemoryNoteCls: type[Any] | None = None
        self._ResearchAgentCls: type[Any] | None = None
        self._AMemGeneratorCls: type[Any] | None = None
        self._agentic_import_error: Exception | None = None
        self._load_agentic_classes()

        self.memory_cards: dict[str, dict[str, Any]] = {}
        self.entity_by_card_id: dict[str, str] = {}
        self.card_id_by_entity: dict[str, str] = {}
        self.entity_version_by_entity: dict[str, str] = {}
        self.memory_ids: set[str] = set()
        self._load_index()

        self.llm_service, self.generator = self._init_llm_service_and_generator()
        self.memory_system = self._init_storage()
        self.research_agent: Any | None = None

        if self.memory_system is not None and self.generator is not None and self.export_file.exists():
            try:
                self.research_agent = self._load_or_create_retriever()
            except Exception as exc:
                print(f"[Memory] Initial retriever load skipped: {exc}")

        if sync_on_init and self.use_api:
            self._sync_from_api(force_full=True)

    @staticmethod
    def _normalize_allowed_gam_tools(allowed_gam_tools: list[str] | None) -> set[str]:
        if not allowed_gam_tools:
            return set(_ALLOWED_GAM_TOOLS)

        normalized = {
            str(tool).strip()
            for tool in allowed_gam_tools
            if str(tool).strip()
        }
        valid = {tool for tool in normalized if tool in _ALLOWED_GAM_TOOLS}
        if "vector" in valid:
            # Backward compatibility: opting into "vector" enables all vector-backed tools.
            valid.update(_VECTOR_GAM_TOOLS)
        return valid or set(_ALLOWED_GAM_TOOLS)

    @staticmethod
    def _normalize_gam_top_k_by_tool(gam_top_k_by_tool: dict[str, int] | None) -> dict[str, int]:
        normalized = dict(_DEFAULT_GAM_TOP_K_BY_TOOL)
        if not isinstance(gam_top_k_by_tool, dict):
            return normalized

        for tool_name, raw_value in gam_top_k_by_tool.items():
            tool = str(tool_name).strip()
            if tool not in normalized:
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                normalized[tool] = value
        return normalized

    @staticmethod
    def _normalize_gam_pipeline_mode(gam_pipeline_mode: str | None) -> str:
        mode = str(gam_pipeline_mode or "default").strip().lower()
        if mode in _ALLOWED_GAM_PIPELINE_MODES:
            return mode
        return "default"

    def _load_agentic_classes(self) -> None:
        try:
            from A_mem.agentic_memory.memory_system import (
                AgenticMemorySystem as _AgenticMemorySystem,
                MemoryNote as _MemoryNote,
            )
            from GAM_root.gam import ResearchAgent as _ResearchAgent
            from GAM_root.gam.generator import AMemGenerator as _AMemGenerator
        except Exception as exc:
            self._agentic_import_error = exc
            print(
                "[Memory] Agentic runtime dependencies are unavailable. "
                f"Reason: {exc}. Falling back to API full-text mode."
            )
            return

        self._AgenticMemorySystemCls = _AgenticMemorySystem
        self._MemoryNoteCls = _MemoryNote
        self._ResearchAgentCls = _ResearchAgent
        self._AMemGeneratorCls = _AMemGenerator

    def _init_llm_service_and_generator(self) -> tuple[LLMService | None, Any | None]:
        if self._AMemGeneratorCls is None:
            return None, None
        if not config.OPENROUTER_API_KEY:
            print(
                "[Memory] OPENROUTER_API_KEY is not set. "
                "Agentic retrieval is disabled; API full-text fallback is available."
            )
            return None, None

        try:
            llm_service = LLMService(
                service=config.OPENROUTER_SERVICE,
                model_name=config.OPENROUTER_MODEL_NAME,
                api_key=config.OPENROUTER_API_KEY,
                temperature=0.0,
                max_tokens=0,
                reasoning_effort="low",
            )
            generator = self._AMemGeneratorCls({"llm_service": llm_service})
            return llm_service, generator
        except Exception as exc:
            print(f"[Memory] Could not initialize LLM/generator: {exc}")
            return None, None

    def _init_storage(self) -> Any | None:
        if self.llm_service is None or self._AgenticMemorySystemCls is None:
            return None
        try:
            return self._AgenticMemorySystemCls(
                model_name=config.AMEM_EMBEDDING_MODEL_NAME,
                llm_backend="custom",
                llm_service=self.llm_service,
                chroma_persist_dir=self.checkpoint_dir / "chroma",
                chroma_collection_name="memories",
                use_gam_card_document=True,
                enable_evolution=self.enable_memory_evolution,
            )
        except Exception as exc:
            print(f"[Memory] Could not initialize AgenticMemorySystem: {exc}")
            return None

    def _load_index(self) -> None:
        if not self.index_file.exists():
            return

        try:
            payload = json.loads(self.index_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[Memory] Could not parse index file {self.index_file}: {exc}")
            return

        raw_cards = payload.get("memory_cards", {})
        raw_map = payload.get("entity_by_card_id", {})
        raw_versions = payload.get("entity_version_by_entity", {})

        if isinstance(raw_cards, dict):
            for card_id, card in raw_cards.items():
                cid = str(card_id)
                self.memory_cards[cid] = normalize_memory_card(card, fallback_id=cid)
                self.memory_ids.add(cid)

        if isinstance(raw_map, dict):
            for card_id, entity_id in raw_map.items():
                cid = str(card_id)
                eid = str(entity_id)
                if not cid or not eid:
                    continue
                self.entity_by_card_id[cid] = eid
                self.card_id_by_entity[eid] = cid

        if isinstance(raw_versions, dict):
            for entity_id, version_id in raw_versions.items():
                eid = str(entity_id)
                vid = str(version_id or "")
                if eid:
                    self.entity_version_by_entity[eid] = vid

    def _persist_index(self) -> None:
        payload = {
            "entity_by_card_id": self.entity_by_card_id,
            "entity_version_by_entity": self.entity_version_by_entity,
            "memory_cards": self.memory_cards,
        }
        self.index_file.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        try:
            uuid.UUID(value)
            return True
        except Exception:
            return False

    @staticmethod
    def _dedupe_keep_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _ensure_card_id(self, card: dict[str, Any]) -> str:
        card_id = str(card.get("id") or "").strip()
        if not card_id:
            card_id = f"mem-{uuid.uuid4().hex[:12]}"
            card["id"] = card_id
        return card_id

    def _card_to_concept_content(self, card: dict[str, Any]) -> dict[str, Any]:
        explanation = card.get("explanation")
        if isinstance(explanation, dict):
            explanation_text = str(explanation.get("summary") or "")
        else:
            explanation_text = str(explanation or "")

        strategy = str(card.get("strategy") or "").strip().lower() or None
        if strategy not in _ALLOWED_STRATEGIES:
            strategy = None

        evolution_statistics = card.get("evolution_statistics")
        if not isinstance(evolution_statistics, dict):
            evolution_statistics = None

        usage = card.get("usage")
        if not isinstance(usage, dict):
            usage = None

        return {
            "id": str(card.get("id") or ""),
            "category": str(card.get("category") or "general"),
            "task_description": str(card.get("task_description") or ""),
            "description": str(card.get("description") or ""),
            "explanation": explanation_text,
            "strategy": strategy,
            "keywords": self._dedupe_keep_order(list(card.get("keywords") or [])),
            "evolution_statistics": evolution_statistics,
            "works_with": self._dedupe_keep_order(list(card.get("works_with") or [])),
            "links": self._dedupe_keep_order(list(card.get("links") or [])),
            "usage": usage,
        }

    def _build_entity_meta(self, card: dict[str, Any]) -> tuple[str, list[str], str]:
        card_id = str(card.get("id") or "")
        description = str(card.get("description") or "").strip()
        task_description = str(card.get("task_description") or "").strip()

        explanation = card.get("explanation")
        explanation_summary = ""
        if isinstance(explanation, dict):
            explanation_summary = str(explanation.get("summary") or "").strip()
        else:
            explanation_summary = str(explanation or "").strip()

        name_seed = description or task_description or "memory card"
        name = f"{card_id}: {name_seed}" if card_id else name_seed
        name = name[:255]

        tags = self._dedupe_keep_order(
            [
                str(card.get("category") or "").strip(),
                str(card.get("strategy") or "").strip(),
                *[str(x).strip() for x in (card.get("keywords") or [])],
            ]
        )

        when_to_use_parts = self._dedupe_keep_order(
            [
                task_description,
                description,
                explanation_summary,
                " ".join([str(x) for x in (card.get("keywords") or [])]).strip(),
            ]
        )
        when_to_use = " | ".join(when_to_use_parts)

        return name, tags, when_to_use

    def _concept_to_card(self, concept_content: dict[str, Any], fallback_id: str) -> dict[str, Any]:
        return normalize_memory_card(
            {
                "id": concept_content.get("id") or fallback_id,
                "category": concept_content.get("category") or "general",
                "description": concept_content.get("description") or "",
                "task_description": concept_content.get("task_description") or "",
                "strategy": concept_content.get("strategy") or "",
                "keywords": concept_content.get("keywords") or [],
                "evolution_statistics": concept_content.get("evolution_statistics") or {},
                "explanation": {
                    "explanations": [],
                    "summary": concept_content.get("explanation") or "",
                },
                "works_with": concept_content.get("works_with") or [],
                "links": concept_content.get("links") or [],
                "usage": concept_content.get("usage") or {},
            },
            fallback_id=fallback_id,
        )

    def _note_metadata(self, note: Any) -> dict[str, Any]:
        return {
            "id": note.id,
            "content": note.content,
            "keywords": note.keywords,
            "links": note.links,
            "retrieval_count": note.retrieval_count,
            "timestamp": note.timestamp,
            "last_accessed": note.last_accessed,
            "context": note.context,
            "evolution_history": note.evolution_history,
            "category": note.category,
            "tags": note.tags,
            "strategy": note.strategy,
        }

    def _build_note_from_card(self, card: dict[str, Any]) -> Any:
        if self._MemoryNoteCls is None:
            raise RuntimeError("MemoryNote class is unavailable")
        card_id = str(card.get("id") or "")
        description = str(card.get("description") or "")
        context = str(card.get("task_description") or "General")
        category = str(card.get("category") or "general")
        strategy = str(card.get("strategy") or "")
        keywords = list(card.get("keywords") or [])
        links = list(card.get("links") or [])
        existing = self.memory_system.read(card_id) if self.memory_system is not None else None

        return self._MemoryNoteCls(
            content=description,
            id=card_id,
            keywords=keywords,
            links=links,
            retrieval_count=(existing.retrieval_count if existing is not None else 0),
            timestamp=(existing.timestamp if existing is not None else None),
            last_accessed=(existing.last_accessed if existing is not None else None),
            context=context or "General",
            evolution_history=(existing.evolution_history if existing is not None else None),
            category=category,
            tags=(existing.tags if existing is not None else []),
            strategy=strategy,
        )

    def _upsert_local_note_fast(self, card: dict[str, Any]) -> bool:
        """Synchronize card into local A-MEM/Chroma without running LLM evolution."""
        if self.memory_system is None:
            return False

        note = self._build_note_from_card(card)
        existing = self.memory_system.read(note.id)
        changed = (
            existing is None
            or existing.content != note.content
            or existing.category != note.category
            or existing.context != note.context
            or existing.strategy != note.strategy
            or existing.keywords != note.keywords
            or existing.links != note.links
        )
        if not changed:
            self.memory_ids.add(note.id)
            return False

        self.memory_system.memories[note.id] = note
        try:
            self.memory_system.retriever.delete_document(note.id)
        except Exception:
            pass
        self.memory_system.retriever.add_document(
            self.memory_system._document_for_note(note),
            self._note_metadata(note),
            note.id,
        )
        self.memory_ids.add(note.id)
        return True

    def _upsert_local_note_agentic(self, card: dict[str, Any]) -> bool:
        """Add/update card in local A-MEM using regular add/update path for local writes."""
        if self.memory_system is None:
            return False

        card_id = str(card.get("id") or "").strip()
        if not card_id:
            return False

        description = str(card.get("description") or "")
        kwargs = {
            "category": str(card.get("category") or "general"),
            "keywords": list(card.get("keywords") or []),
            "context": str(card.get("task_description") or "General"),
            "strategy": str(card.get("strategy") or ""),
            "links": list(card.get("links") or []),
            "tags": [],
        }

        existing = self.memory_system.read(card_id)
        if existing is None:
            self.memory_system.add_note(id=card_id, content=description, **kwargs)
        else:
            changed = (
                existing.content != description
                or existing.category != kwargs["category"]
                or existing.context != kwargs["context"]
                or existing.strategy != kwargs["strategy"]
                or existing.keywords != kwargs["keywords"]
                or existing.links != kwargs["links"]
            )
            if not changed:
                self.memory_ids.add(card_id)
                return False
            self.memory_system.update(card_id, content=description, **kwargs)

        self.memory_ids.add(card_id)
        return True

    def _remove_local_note(self, card_id: str) -> bool:
        if self.memory_system is None:
            self.memory_ids.discard(card_id)
            return False
        deleted = self.memory_system.delete(card_id)
        self.memory_ids.discard(card_id)
        return deleted

    def _fetch_all_concept_hits(self) -> list[dict[str, Any]]:
        if not self.use_api or self.api is None:
            return []
        hits: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self.api.search_concepts(
                query=None,
                limit=self.sync_batch_size,
                offset=offset,
                namespace=self.namespace,
            )
            page_hits = list(payload.get("hits", []))
            total = int(payload.get("total", 0) or 0)
            if not page_hits:
                break
            hits.extend(page_hits)
            offset += len(page_hits)
            if total and offset >= total:
                break
            if len(page_hits) < self.sync_batch_size:
                break
        return hits

    def _sync_from_api(self, force_full: bool = False) -> bool:
        if not self.use_api or self.api is None:
            return False
        remote_hits = self._fetch_all_concept_hits()
        remote_entity_ids: set[str] = set()
        changed = False

        for hit in remote_hits:
            entity_id = str(hit.get("entity_id") or "").strip()
            if not entity_id:
                continue
            remote_entity_ids.add(entity_id)
            remote_version = str(hit.get("version_id") or "").strip()

            known_card_id = self.card_id_by_entity.get(entity_id)
            known_version = self.entity_version_by_entity.get(entity_id, "")
            if (
                not force_full
                and known_card_id
                and remote_version
                and known_version == remote_version
            ):
                if (
                    self.memory_system is not None
                    and self.memory_system.read(known_card_id) is None
                    and known_card_id in self.memory_cards
                ):
                    if self._upsert_local_note_fast(self.memory_cards[known_card_id]):
                        changed = True
                self.memory_ids.add(known_card_id)
                continue

            concept = self.api.get_concept(entity_id, channel=self.channel)
            content = concept.get("content") or {}
            fallback_id = self.card_id_by_entity.get(entity_id) or str(content.get("id") or entity_id)
            card = self._concept_to_card(content, fallback_id=fallback_id)
            card_id = self._ensure_card_id(card)

            previous_card_id = self.card_id_by_entity.get(entity_id)
            if previous_card_id and previous_card_id != card_id:
                self.entity_by_card_id.pop(previous_card_id, None)
                self.memory_cards.pop(previous_card_id, None)
                self._remove_local_note(previous_card_id)
                changed = True

            self.card_id_by_entity[entity_id] = card_id
            self.entity_by_card_id[card_id] = entity_id
            self.entity_version_by_entity[entity_id] = str(
                concept.get("version_id") or remote_version or ""
            )

            old_card = self.memory_cards.get(card_id)
            if old_card != card:
                changed = True
            self.memory_cards[card_id] = card

            if self._upsert_local_note_fast(card):
                changed = True

        stale_entities = [eid for eid in self.card_id_by_entity if eid not in remote_entity_ids]
        for entity_id in stale_entities:
            card_id = self.card_id_by_entity.pop(entity_id, None)
            self.entity_version_by_entity.pop(entity_id, None)
            if card_id:
                self.entity_by_card_id.pop(card_id, None)
                self.memory_cards.pop(card_id, None)
                self._remove_local_note(card_id)
            changed = True

        if changed:
            self.rebuild()
        else:
            self._persist_index()
            if self.research_agent is None and self.memory_system is not None and self.generator is not None:
                self.rebuild()

        return changed

    def _load_or_create_retriever(self) -> Any | None:
        if self.generator is None or self._ResearchAgentCls is None:
            raise RuntimeError("Generator is not available. Cannot create GAM research agent.")
        try:
            from shared_memory.amem_gam_retriever import (
                build_gam_store,
                build_retrievers,
                load_amem_records,
            )
        except Exception as exc:
            raise RuntimeError(f"GAM helper modules are unavailable: {exc}") from exc

        self.gam_store_dir.mkdir(parents=True, exist_ok=True)
        if self.export_file.exists():
            records = load_amem_records(self.export_file)
        else:
            records = list(self.memory_cards.values())

        memory_store, page_store, added = build_gam_store(records, self.gam_store_dir)
        print(f"[Memory] Loaded {len(records)} cards, added {added} new pages.")

        retrievers = build_retrievers(
            page_store,
            self.gam_store_dir / "indexes",
            self.checkpoint_dir / "chroma",
            enable_bm25=self.enable_bm25,
        )
        retrievers = {
            name: retriever
            for name, retriever in retrievers.items()
            if name in self.allowed_gam_tools
        }
        if not retrievers:
            print(
                "[Memory] No GAM retrievers enabled after applying allowed_gam_tools. "
                "GAM agentic search is disabled."
            )
            return None
        return self._ResearchAgentCls(
            page_store=page_store,
            memory_store=memory_store,
            retrievers=retrievers,
            generator=self.generator,
            max_iters=3,
            allowed_tools=sorted(self.allowed_gam_tools),
            top_k_by_tool=self.gam_top_k_by_tool,
            pipeline_mode=self.gam_pipeline_mode,
        )

    def _dump_memory(self) -> None:
        if self.memory_system is None:
            return
        all_ids = sorted(set(self.memory_ids) | set(self.memory_cards.keys()))
        _export_memories_jsonl(
            self.memory_system,
            all_ids,
            self.export_file,
            card_overrides=self.memory_cards,
        )

    def save_card(self, card: dict[str, Any]) -> str:
        card = normalize_memory_card(card)
        card_id = self._ensure_card_id(card)

        if self.enable_llm_card_enrichment and self.memory_system is not None:
            analysis = self.memory_system.analyze_content(card["description"])
            if not card.get("keywords"):
                card["keywords"] = analysis.get("keywords") or []
            if not card.get("task_description"):
                card["task_description"] = analysis.get("context") or ""

        content = self._card_to_concept_content(card)
        name, tags, when_to_use = self._build_entity_meta(card)

        if self.use_api and self.api is not None:
            current_entity_id = self.entity_by_card_id.get(card_id)
            response = self.api.save_concept(
                content=content,
                name=name,
                tags=tags,
                when_to_use=when_to_use,
                channel=self.channel,
                namespace=self.namespace,
                author=self.author,
                entity_id=current_entity_id,
            )

            saved_entity_id = str(response["entity_id"])
            if current_entity_id and current_entity_id != saved_entity_id:
                self.card_id_by_entity.pop(current_entity_id, None)
                self.entity_version_by_entity.pop(current_entity_id, None)

            self.entity_by_card_id[card_id] = saved_entity_id
            self.card_id_by_entity[saved_entity_id] = card_id
            self.entity_version_by_entity[saved_entity_id] = str(response.get("version_id") or "")
        else:
            stale_entity_id = self.entity_by_card_id.pop(card_id, None)
            if stale_entity_id:
                self.card_id_by_entity.pop(stale_entity_id, None)
                self.entity_version_by_entity.pop(stale_entity_id, None)
        self.memory_cards[card_id] = normalize_memory_card(card, fallback_id=card_id)

        self._upsert_local_note_agentic(self.memory_cards[card_id])
        self._persist_index()

        self._iters_after_rebuild += 1
        if self._iters_after_rebuild >= self.rebuild_interval:
            self.rebuild()

        return card_id

    def save(self, data: str, category: str = "general") -> str:
        return self.save_card(
            {
                "category": category,
                "description": data,
                "task_description": "",
                "strategy": "",
                "last_generation": 0,
                "programs": [],
                "aliases": [],
                "keywords": [],
                "evolution_statistics": {},
                "explanation": {"explanations": [], "summary": ""},
                "works_with": [],
                "links": [],
                "usage": {},
            }
        )

    def _format_search_results(self, query: str, cards: list[dict[str, Any]]) -> str:
        lines = [f"Query: {query}", "", "Top relevant memory cards:"]
        for idx, card in enumerate(cards, start=1):
            card_id = str(card.get("id") or "")
            category = str(card.get("category") or "general")
            description = str(card.get("description") or "").strip()
            lines.append(f"{idx}. {card_id} [{category}] {description}")
        return "\n".join(lines)

    def _synthesize_results(
        self,
        query: str,
        memory_state: str | None,
        cards: list[dict[str, Any]],
    ) -> str:
        if self.llm_service is None:
            return self._format_search_results(query, cards)

        cards_blob = []
        for card in cards:
            cards_blob.append(
                "\n".join(
                    [
                        f"id: {card.get('id', '')}",
                        f"category: {card.get('category', '')}",
                        f"task_description: {card.get('task_description', '')}",
                        f"description: {card.get('description', '')}",
                        f"keywords: {card.get('keywords', [])}",
                        f"explanation: {card.get('explanation', {}).get('summary', '') if isinstance(card.get('explanation'), dict) else card.get('explanation', '')}",
                    ]
                )
            )

        prompt = (
            "You are a memory retrieval assistant.\n"
            "Use only the provided memory cards to answer the user query.\n"
            "Always cite card ids explicitly (example: mem-029).\n"
            "If evidence is insufficient, say so clearly.\n\n"
            f"Memory state:\n{memory_state or '(empty)'}\n\n"
            f"User query:\n{query}\n\n"
            "Retrieved cards:\n"
            + "\n\n".join(cards_blob)
            + "\n\nAnswer:"
        )

        try:
            text, _, _, _ = self.llm_service.generate(prompt)
            text = str(text or "").strip()
            if text:
                return text
        except Exception as exc:
            print(f"[Memory] LLM synthesis failed, fallback to plain output: {exc}")

        return self._format_search_results(query, cards)

    def _search_via_api(self, query: str, memory_state: str | None = None) -> str:
        if not self.use_api or self.api is None:
            return self._search_local_cards(query, memory_state)
        effective_query = query.strip()
        if memory_state:
            effective_query = f"{effective_query}\n{memory_state.strip()}"

        payload = self.api.search_concepts(
            query=effective_query,
            limit=self.search_limit,
            namespace=self.namespace,
            offset=0,
        )
        hits = payload.get("hits", [])
        if not hits:
            return f"Query: {query}\n\nNo relevant memories found."

        cards: list[dict[str, Any]] = []
        local_changed = False

        for hit in hits:
            entity_id = str(hit.get("entity_id") or "").strip()
            if not entity_id:
                continue

            concept = self.api.get_concept(entity_id, channel=self.channel)
            content = concept.get("content") or {}

            card_id = str(content.get("id") or self.card_id_by_entity.get(entity_id) or entity_id)
            card = self._concept_to_card(content, fallback_id=card_id)
            card_id = self._ensure_card_id(card)

            self.card_id_by_entity[entity_id] = card_id
            self.entity_by_card_id[card_id] = entity_id
            self.entity_version_by_entity[entity_id] = str(
                concept.get("version_id") or hit.get("version_id") or ""
            )
            self.memory_cards[card_id] = card
            cards.append(card)

            if self._upsert_local_note_fast(card):
                local_changed = True

        self._persist_index()
        if local_changed and self.memory_system is not None and self.generator is not None:
            self.rebuild()

        if not cards:
            return f"Query: {query}\n\nNo relevant memories found."

        if self.enable_llm_synthesis:
            return self._synthesize_results(query, memory_state, cards)
        return self._format_search_results(query, cards)

    def _search_local_cards(self, query: str, memory_state: str | None = None) -> str:
        if not self.memory_cards:
            return f"Query: {query}\n\nNo relevant memories found."

        query_text = f"{query} {memory_state or ''}".strip().lower()
        tokens = [tok for tok in re.split(r"\W+", query_text) if tok]
        if not tokens:
            tokens = [query.strip().lower()] if query.strip() else []

        scored: list[tuple[int, dict[str, Any]]] = []
        for card in self.memory_cards.values():
            haystack = " ".join(
                [
                    str(card.get("description") or ""),
                    str(card.get("task_description") or ""),
                    " ".join([str(x) for x in (card.get("keywords") or [])]),
                    str(card.get("category") or ""),
                ]
            ).lower()
            score = sum(1 for tok in tokens if tok and tok in haystack)
            if score > 0:
                scored.append((score, card))

        scored.sort(key=lambda item: item[0], reverse=True)
        top_cards = [card for _, card in scored[: self.search_limit]]

        if not top_cards:
            return f"Query: {query}\n\nNo relevant memories found."

        if self.enable_llm_synthesis:
            return self._synthesize_results(query, memory_state, top_cards)
        return self._format_search_results(query, top_cards)

    def search(self, query: str, memory_state: str | None = None) -> str:
        if self.use_api and self.api is not None:
            self._sync_from_api(force_full=False)

        if self.research_agent is not None:
            try:
                return self.research_agent.research(query, memory_state=memory_state).integrated_memory
            except Exception as exc:
                print(f"[Memory] GAM search failed, falling back to non-agentic search: {exc}")

        if self.use_api and self.api is not None:
            return self._search_via_api(query, memory_state=memory_state)
        return self._search_local_cards(query, memory_state=memory_state)

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        return self.memory_cards.get(card_id)

    def rebuild(self) -> None:
        self._persist_index()
        if self.memory_system is None or self.generator is None:
            return
        self._dump_memory()
        self.research_agent = self._load_or_create_retriever()
        self._iters_after_rebuild = 0

    def delete(self, memory_id: str) -> bool:
        key = str(memory_id).strip()
        if self.use_api and self.api is not None:
            entity_id = self.entity_by_card_id.get(key)
            if not entity_id and self._looks_like_uuid(key):
                entity_id = key
            if not entity_id:
                return False
            self.api.delete_concept(entity_id)
            card_id = self.card_id_by_entity.pop(entity_id, key)
            self.entity_version_by_entity.pop(entity_id, None)
        else:
            card_id = key
            if card_id not in self.memory_cards and key in self.card_id_by_entity:
                card_id = self.card_id_by_entity[key]
            if card_id not in self.memory_cards:
                return False
            entity_id = self.entity_by_card_id.get(card_id)
            if entity_id:
                self.card_id_by_entity.pop(entity_id, None)
                self.entity_version_by_entity.pop(entity_id, None)

        self.entity_by_card_id.pop(card_id, None)
        self.memory_cards.pop(card_id, None)
        self._remove_local_note(card_id)
        self._persist_index()

        if self.memory_system is not None and self.generator is not None:
            self.rebuild()

        return True

    def close(self) -> None:
        if self.api is not None:
            self.api.close()

    def __del__(self) -> None:
        try:
            if self._iters_after_rebuild > 0:
                self.rebuild()
        except Exception:
            pass
        try:
            self.close()
        except Exception:
            pass
