import json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from A_mem.agentic_memory.memory_system import AgenticMemorySystem
from A_mem.agent.agent_class import LLMService
import config

from GAM_root.gam import ResearchAgent
from GAM_root.gam.generator import AMemGenerator

from a_mem_memory_creation import export_memories_jsonl, add_memories_from_list
from amem_gam_retriever import load_amem_records, build_retrievers, build_gam_store


class GigaEvoMemoryBase:
    def save(self, data: str) -> int:
        raise NotImplementedError
    
    def search(self, query: str) -> str:
        raise NotImplementedError
    
    def delete(self, id: int):
        raise NotImplementedError

class AmemGamMemory(GigaEvoMemoryBase):
    def __init__(self, checkpoint_path: str, rebuild_interval: int = 10):
        # Treat checkpoint_path as a directory that holds:
        # - amem_exports/amem_memories.jsonl (A-mem export)
        # - gam_shared/amem_store/ (GAM store + indexes)
        self.checkpoint_dir = Path(checkpoint_path)
        self.rebuild_interval = rebuild_interval
        self._iters_after_rebuild = 0

        self.llm_service, self.generator = self._init_llm_service_and_generator()
        
        self.memory_system, self.memory_ids = self._init_storage()
        self.export_file = self.checkpoint_dir / "amem_exports" / "amem_memories.jsonl"
        self.gam_store_dir = self.checkpoint_dir / "gam_shared" / "amem_store"

        self.research_agent = self._load_or_create_retriever()

    def _init_storage(self):
        # Initialize the memory system 🚀
        memory_system = AgenticMemorySystem(
            model_name=config.AMEM_EMBEDDING_MODEL_NAME,  # Embedding model for ChromaDB
            llm_backend="custom",           # Use external LLMService
            llm_service=self.llm_service,
            chroma_persist_dir=self.checkpoint_dir / "chroma",
            chroma_collection_name="memories",
            use_gam_card_document=True,
        )
        memory_ids = set()
        
        return memory_system, memory_ids
        
    def _init_llm_service_and_generator(self):
        llm_service = LLMService(
            service=config.OPENROUTER_SERVICE,
            model_name=config.OPENROUTER_MODEL_NAME,
            api_key=config.OPENROUTER_API_KEY,
            temperature=0.0,
            max_tokens=2048,
        )
        generator = AMemGenerator({"llm_service": llm_service})
        return llm_service, generator

        
    def _dump_memory(self):
        export_memories_jsonl(self.memory_system, list(self.memory_ids), self.export_file)
        
    def _load_or_create_retriever(self):
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        if self.export_file.exists():
            records = load_amem_records(self.export_file)
        else:
            records = []

        self.gam_store_dir.mkdir(parents=True, exist_ok=True)
        memory_store, page_store, added = build_gam_store(records, self.gam_store_dir)
        print(f"[Memory] Loaded {len(records)} A-mem records, added {added} new pages.")
        retrievers = build_retrievers(
            page_store,
            self.gam_store_dir / "indexes",
            self.checkpoint_dir / "chroma",
        )
        research_agent = ResearchAgent(
            page_store=page_store,
            memory_store=memory_store,
            retrievers=retrievers,
            generator=self.generator,
            max_iters=3,
        )
        
        return research_agent
        
    def rebuild(self):
        self._dump_memory()
        self.research_agent = self._load_or_create_retriever()
    
    def save(self, data: str, category: str = "general") -> int:
        new_memory_ids = add_memories_from_list(self.memory_system, [data], category)
        self.memory_ids.update(new_memory_ids)
        
        self._iters_after_rebuild += 1
        if self._iters_after_rebuild >= self.rebuild_interval:
            self.rebuild()
            self._iters_after_rebuild = 0
        
        return new_memory_ids[0]

    def search(self, query: str, memory_state: str | None = None) -> str:
        # ResearchAgent's public API is `research(request) -> ResearchOutput`.
        return self.research_agent.research(query, memory_state=memory_state).integrated_memory
    
    def __del__(self):
        if self._iters_after_rebuild > 0:
            print(f"[Memory] Flushing memory to {self.export_file} before destruction")
            self._dump_memory()
            self._iters_after_rebuild = 0
