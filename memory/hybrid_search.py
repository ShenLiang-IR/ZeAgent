import math
import jieba
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
from .blocks import MemoryBlock
class BM25:
    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25
    ):
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.doc_freqs: Dict[str, int] = {}
        self.doc_lens: List[int] = []
        self.avgdl: float = 0
        self.doc_count: int = 0
        self.idf: Dict[str, float] = {}
        self.doc_term_freqs: List[Dict[str, int]] = []
        self._jieba_initialized = False
    def _ensure_jieba(self) -> None:
        if not self._jieba_initialized:
            try:
                jieba.initialize()
            except Exception:
                pass
            self._jieba_initialized = True
    def _tokenize(self, text: str) -> List[str]:
        self._ensure_jieba()
        tokens = []
        words = jieba.cut(text.lower())
        for word in words:
            word = word.strip()
            if len(word) > 1 and word.isalnum():
                tokens.append(word)
            elif word.isalpha() and len(word) == 1:
                tokens.append(word)
        return tokens
    def fit(self, documents: List[str]) -> None:
        self.doc_count = len(documents)
        self.doc_lens = []
        self.doc_term_freqs = []
        self.doc_freqs = {}
        logger.debug(f"[BM25] : {self.doc_count}")
        for doc in documents:
            tokens = self._tokenize(doc)
            self.doc_lens.append(len(tokens))
            term_freqs = Counter(tokens)
            self.doc_term_freqs.append(dict(term_freqs))
            for term in term_freqs:
                if term not in self.doc_freqs:
                    self.doc_freqs[term] = 0
                self.doc_freqs[term] += 1
        self.avgdl = sum(self.doc_lens) / self.doc_count if self.doc_count > 0 else 0
        self.idf = {}
        for term, freq in self.doc_freqs.items():
            idf = math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1)
            self.idf[term] = max(self.epsilon, idf)
        logger.debug(
            f"[BM25]  | "
            f"avgdl={self.avgdl:.2f}, vocab_size={len(self.doc_freqs)}"
        )
    def add_document(self, document: str) -> int:
        doc_idx = self.doc_count
        self.doc_count += 1
        tokens = self._tokenize(document)
        self.doc_lens.append(len(tokens))
        term_freqs = Counter(tokens)
        self.doc_term_freqs.append(dict(term_freqs))
        for term in term_freqs:
            if term not in self.doc_freqs:
                self.doc_freqs[term] = 0
            self.doc_freqs[term] += 1
        self.avgdl = sum(self.doc_lens) / self.doc_count
        for term in term_freqs:
            freq = self.doc_freqs[term]
            idf = math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1)
            self.idf[term] = max(self.epsilon, idf)
        return doc_idx
    def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        if self.doc_count == 0:
            return []
        query_tokens = self._tokenize(query)
        scores = []
        for doc_idx, term_freqs in enumerate(self.doc_term_freqs):
            score = 0.0
            doc_len = self.doc_lens[doc_idx]
            for term in query_tokens:
                if term not in term_freqs:
                    continue
                tf = term_freqs[term]
                idf = self.idf.get(term, 0)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                if denominator > 0:
                    score += idf * numerator / denominator
            if score > 0:
                scores.append((doc_idx, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
    def get_doc_score(self, query: str, doc_idx: int) -> float:
        if doc_idx >= self.doc_count:
            return 0.0
        query_tokens = self._tokenize(query)
        term_freqs = self.doc_term_freqs[doc_idx]
        doc_len = self.doc_lens[doc_idx]
        score = 0.0
        for term in query_tokens:
            if term not in term_freqs:
                continue
            tf = term_freqs[term]
            idf = self.idf.get(term, 0)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            if denominator > 0:
                score += idf * numerator / denominator
        return score
    def clear(self) -> None:
        self.doc_freqs = {}
        self.doc_lens = []
        self.avgdl = 0
        self.doc_count = 0
        self.idf = {}
        self.doc_term_freqs = []
class HybridMemorySearch:
    def __init__(
        self,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        rrf_k: int = 60,
        similarity_threshold: float = 0.5
    ):
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k
        self.similarity_threshold = similarity_threshold
        self.bm25 = BM25()
        self.documents: List[str] = []
        self.memories: List[MemoryBlock] = []
        self.embeddings: List[Optional[List[float]]] = []
        self._embedding_model = None
        self._model_initialized = False
        self._indexed = False
        logger.debug(
            f"[HybridMemorySearch]  | "
            f"bm25_weight={bm25_weight}, vector_weight={vector_weight}, rrf_k={rrf_k}"
        )
    async def _get_embedding_model(self) -> Any:
        """获取 embedding 模型（委托给 embedding_factory 工厂函数）

        注意：与 storage.py 不同，hybrid_search 在所有 embedding 初始化失败时
        返回 None（不 raise），以支持混合搜索的降级模式。
        """
        if self._model_initialized:
            return self._embedding_model
        self._model_initialized = True
        try:
            from memory.embedding_factory import create_embedding_model
            self._embedding_model = create_embedding_model("[HybridMemorySearch]")
        except Exception as e:
            logger.error(f"[HybridMemorySearch] embedding init failed: {e}")
            self._embedding_model = None
        return self._embedding_model
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        model = await self._get_embedding_model()
        if model is None:
            return None
        try:
            if hasattr(model, 'aembed_query'):
                return await model.aembed_query(text)
            elif hasattr(model, 'embed_query'):
                return model.embed_query(text)
            elif hasattr(model, 'encode'):
                return model.encode(text).tolist()
        except Exception as e:
            logger.warning(f"[HybridMemorySearch] : {e}")
        return None
    async def index(self, memories: List[MemoryBlock]) -> None:
        if not memories:
            logger.debug("[HybridMemorySearch] ")
            return
        logger.info(f"[HybridMemorySearch]  {len(memories)} ")
        self.memories = memories
        self.documents = [m.content for m in memories]
        self.bm25.fit(self.documents)
        self.embeddings = []
        for i, memory in enumerate(memories):
            if memory.embedding:
                self.embeddings.append(memory.embedding)
            else:
                emb = await self._get_embedding(memory.content)
                self.embeddings.append(emb)
                memory.embedding = emb
            if (i + 1) % 50 == 0:
                logger.debug(f"[HybridMemorySearch]  {i + 1}/{len(memories)} ")
        self._indexed = True
        logger.info(f"[HybridMemorySearch]  | {len(memories)} ")
    def add_memory(self, memory: MemoryBlock) -> None:
        self.memories.append(memory)
        self.documents.append(memory.content)
        self.bm25.add_document(memory.content)
        self.embeddings.append(memory.embedding)
    async def add_memory_async(self, memory: MemoryBlock) -> None:
        if memory.embedding is None:
            memory.embedding = await self._get_embedding(memory.content)
        self.add_memory(memory)
    def remove_memory(self, memory_id: str) -> bool:
        for i, memory in enumerate(self.memories):
            if memory.id == memory_id:
                self.memories.pop(i)
                self.documents.pop(i)
                self.embeddings.pop(i)
                self.bm25.fit(self.documents)
                return True
        return False
    def clear(self) -> None:
        self.memories = []
        self.documents = []
        self.embeddings = []
        self.bm25.clear()
        self._indexed = False
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0
        return dot_product / (norm_a * norm_b)
    async def _vector_search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        query_embedding = await self._get_embedding(query)
        if not query_embedding:
            return []
        scores = []
        for idx, emb in enumerate(self.embeddings):
            if emb:
                similarity = self._cosine_similarity(query_embedding, emb)
                if similarity >= self.similarity_threshold:
                    scores.append((idx, similarity))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
    def _bm25_search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        return self.bm25.search(query, top_k=top_k)
    def _rrf_merge(
        self,
        bm25_results: List[Tuple[int, float]],
        vector_results: List[Tuple[int, float]],
        top_k: int
    ) -> List[Tuple[int, float]]:
        rrf_scores: Dict[int, float] = {}
        for rank, (doc_idx, _) in enumerate(bm25_results):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0) + \
                self.bm25_weight / (self.rrf_k + rank + 1)
        for rank, (doc_idx, _) in enumerate(vector_results):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0) + \
                self.vector_weight / (self.rrf_k + rank + 1)
        sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]
    async def search(
        self,
        query: str,
        top_k: int = 10,
        use_reranking: bool = False,
        bm25_only: bool = False,
        vector_only: bool = False
    ) -> List[MemoryBlock]:
        if not self.memories:
            return []
        if not self._indexed:
            await self.index(self.memories)
        expansion_factor = 2
        if bm25_only:
            bm25_results = self._bm25_search(query, top_k=top_k * expansion_factor)
            merged_results = [(idx, score) for idx, score in bm25_results]
        elif vector_only:
            vector_results = await self._vector_search(query, top_k=top_k * expansion_factor)
            merged_results = [(idx, score) for idx, score in vector_results]
        else:
            bm25_results = self._bm25_search(query, top_k=top_k * expansion_factor)
            vector_results = await self._vector_search(query, top_k=top_k * expansion_factor)
            merged_results = self._rrf_merge(bm25_results, vector_results, top_k)
        results = []
        for doc_idx, score in merged_results:
            if doc_idx < len(self.memories):
                memory = self.memories[doc_idx]
                memory.metadata['hybrid_score'] = score
                results.append(memory)
        if use_reranking and results:
            results = await self._rerank(query, results)
        logger.debug(
            f"[HybridMemorySearch]  | "
            f"query='{query[:30]}...', results={len(results)}"
        )
        return results
    async def _rerank(
        self,
        query: str,
        memories: List[MemoryBlock],
        top_k: Optional[int] = None
    ) -> List[MemoryBlock]:
        try:
            from llm.llm_client import LLMClient
            client = LLMClient()
            scored = []
            for memory in memories:
                prompt = f""" 0-1 
: {query}
: {memory.content}
"""
                try:
                    score_str = await client.generate(prompt)
                    score = float(score_str.strip())
                    memory.metadata['rerank_score'] = score
                    scored.append((score, memory))
                except (ValueError, Exception) as e:
                    logger.debug(f"[HybridMemorySearch] : {e}")
                    scored.append((0.5, memory))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [m for _, m in scored[:top_k or len(memories)]]
        except ImportError:
            logger.warning("[HybridMemorySearch] LLMClient ")
            return memories
        except Exception as e:
            logger.warning(f"[HybridMemorySearch] : {e}")
            return memories
    def get_stats(self) -> Dict[str, Any]:
        return {
            "memory_count": len(self.memories),
            "indexed": self._indexed,
            "bm25_weight": self.bm25_weight,
            "vector_weight": self.vector_weight,
            "rrf_k": self.rrf_k,
            "similarity_threshold": self.similarity_threshold,
            "avg_doc_length": self.bm25.avgdl if self.bm25.doc_count > 0 else 0,
            "vocabulary_size": len(self.bm25.doc_freqs)
        }
class HybridSearchConfig:
    def __init__(
        self,
        mode: str = "hybrid",
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        rrf_k: int = 60,
        similarity_threshold: float = 0.5,
        reranking_enabled: bool = False
    ):
        self.mode = mode
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k
        self.similarity_threshold = similarity_threshold
        self.reranking_enabled = reranking_enabled
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "HybridSearchConfig":
        return cls(
            mode=config.get("mode", "hybrid"),
            bm25_weight=config.get("bm25_weight", 0.3),
            vector_weight=config.get("vector_weight", 0.7),
            rrf_k=config.get("rrf_k", 60),
            similarity_threshold=config.get("similarity_threshold", 0.5),
            reranking_enabled=config.get("reranking_enabled", False)
        )
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "bm25_weight": self.bm25_weight,
            "vector_weight": self.vector_weight,
            "rrf_k": self.rrf_k,
            "similarity_threshold": self.similarity_threshold,
            "reranking_enabled": self.reranking_enabled
        }