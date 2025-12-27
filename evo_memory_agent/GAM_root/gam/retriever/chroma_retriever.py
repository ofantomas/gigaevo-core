# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from typing import Any, Dict, List

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from GAM_root.gam.retriever.base import AbsRetriever
from GAM_root.gam.schemas import Hit


class ChromaRetriever(AbsRetriever):
    name = "vector"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        persist_dir = config.get("persist_dir")
        if not persist_dir:
            raise ValueError("ChromaRetriever requires 'persist_dir' in config")

        self.collection_name = config.get("collection_name", "memories")
        self.model_name = config.get("model_name", "all-MiniLM-L6-v2")

        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.embedding_function = SentenceTransformerEmbeddingFunction(
            model_name=self.model_name
        )
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
        )

    def build(self, page_store) -> None:
        # Chroma collection is updated at insert time; no build step required.
        return None

    def load(self) -> None:
        return None

    def update(self, page_store) -> None:
        return None

    def search(self, query_list: List[str], top_k: int = 10) -> List[List[Hit]]:
        if not query_list:
            return []

        results = self.collection.query(
            query_texts=query_list,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        metadatas = results.get("metadatas", [])
        documents = results.get("documents", [])
        ids = results.get("ids", [])
        distances = results.get("distances", [])

        hits_per_query: List[List[Hit]] = []
        for q_idx in range(len(query_list)):
            q_hits: List[Hit] = []
            q_ids = ids[q_idx] if q_idx < len(ids) else []
            q_docs = documents[q_idx] if q_idx < len(documents) else []
            q_meta = metadatas[q_idx] if q_idx < len(metadatas) else []
            q_dist = distances[q_idx] if q_idx < len(distances) else []

            for i, doc_id in enumerate(q_ids):
                metadata: Dict[str, Any] = {}
                if i < len(q_meta) and isinstance(q_meta[i], dict):
                    metadata = self._convert_metadata_types(q_meta[i])

                document = q_docs[i] if i < len(q_docs) else ""
                snippet = metadata.get("content") or document or ""

                score = q_dist[i] if i < len(q_dist) else None
                meta: Dict[str, Any] = {"distance": score, "metadata": metadata}
                if document:
                    meta["document"] = document

                q_hits.append(
                    Hit(
                        page_id=doc_id,
                        snippet=snippet,
                        source="vector",
                        meta=meta,
                    )
                )

            hits_per_query.append(q_hits)

        return hits_per_query

    def _convert_metadata_types(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        converted = dict(metadata)
        for key, value in converted.items():
            if not isinstance(value, str):
                continue
            try:
                converted[key] = ast.literal_eval(value)
            except Exception:
                pass
        return converted
