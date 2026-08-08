import json
from loguru import logger
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
class RerankingStrategy(str, Enum):
    RELEVANCE = "relevance"
    SIMILARITY = "similarity"
    BM25 = "bm25"
    CUSTOM = "custom"
@dataclass
class RerankingConfig:
    enabled: bool = False
    strategy: RerankingStrategy = RerankingStrategy.RELEVANCE
    threshold: float = 0.0
    top_k: Optional[int] = None
    weight_config: Dict[str, float] = field(default_factory=dict)
    @classmethod
    def from_dict(cls, config_dict: Optional[Dict[str, Any]]) -> "RerankingConfig":
        if not config_dict:
            return cls()
        try:
            strategy = config_dict.get("strategy", "relevance").lower()
            if strategy not in [s.value for s in RerankingStrategy]:
                strategy = RerankingStrategy.RELEVANCE.value
            return cls(
                enabled=config_dict.get("enabled", False),
                strategy=RerankingStrategy(strategy),
                threshold=float(config_dict.get("threshold", 0.0)),
                top_k=config_dict.get("top_k"),
                weight_config=config_dict.get("weight_config", {})
            )
        except Exception as e:
            logger.warning(f"[Reranking] : {str(e)}")
            return cls()
class RerankingProcessor:
    def __init__(self, config: Union[Dict[str, Any], RerankingConfig]):
        if isinstance(config, dict):
            self.config = RerankingConfig.from_dict(config)
        else:
            self.config = config
        logger.debug(f"[Reranking] : {self.config.strategy.value}")
    def process(self, data: Union[str, Dict, List]) -> Union[str, Dict, List]:
        if not self.config.enabled:
            return data
        original_data = data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                logger.warning(f"[Reranking]  JSON : {str(e)}")
                return original_data
        results = self._extract_results(data)
        if not results:
            return original_data
        try:
            ranked_results = self._apply_reranking(results)
            if self.config.threshold > 0:
                ranked_results = self._apply_threshold(ranked_results)
            if self.config.top_k is not None:
                ranked_results = ranked_results[:self.config.top_k]
            data = self._update_results(data, ranked_results)
            if isinstance(original_data, str):
                return json.dumps(data, ensure_ascii=False, indent=2)
            return data
        except Exception as e:
            logger.error(f"[Reranking] : {str(e)}", exc_info=True)
            return original_data
    def _extract_results(self, data: Any) -> Optional[List[Dict[str, Any]]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ["results", "data", "items", "content"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
        return None
    def _update_results(self, data: Any, results: List[Dict[str, Any]]) -> Any:
        if isinstance(data, list):
            return results
        if isinstance(data, dict):
            for key in ["results", "data", "items", "content"]:
                if key in data and isinstance(data[key], list):
                    data[key] = results
                    return data
        return data
    def _apply_reranking(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        strategy = self.config.strategy
        if strategy == RerankingStrategy.RELEVANCE:
            return self._rerank_by_relevance(results)
        elif strategy == RerankingStrategy.SIMILARITY:
            return self._rerank_by_similarity(results)
        elif strategy == RerankingStrategy.BM25:
            return self._rerank_by_bm25(results)
        elif strategy == RerankingStrategy.CUSTOM:
            return self._rerank_custom(results)
        else:
            logger.warning(f"[Reranking] : {strategy}")
            return self._rerank_by_relevance(results)
    def _rerank_by_relevance(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        score_keys = ["score", "relevance_score", "confidence", "similarity", "match_score"]
        def get_score(item: Dict[str, Any]) -> float:
            for key in score_keys:
                if key in item and isinstance(item[key], (int, float)):
                    return float(item[key])
            return 0.0
        for item in results:
            if "_reranking_score" not in item:
                item["_reranking_score"] = get_score(item)
        sorted_results = sorted(results, key=lambda x: x.get("_reranking_score", 0), reverse=True)
        logger.debug(f"[Reranking] : {len(sorted_results)}")
        return sorted_results
    def _rerank_by_similarity(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        score_keys = ["similarity", "sim", "cosine_similarity", "similarity_score"]
        def get_similarity(item: Dict[str, Any]) -> float:
            for key in score_keys:
                if key in item and isinstance(item[key], (int, float)):
                    return float(item[key])
            return 0.0
        for item in results:
            if "_reranking_score" not in item:
                item["_reranking_score"] = get_similarity(item)
        sorted_results = sorted(results, key=lambda x: x.get("_reranking_score", 0), reverse=True)
        logger.debug(f"[Reranking] : {len(sorted_results)}")
        return sorted_results
    def _rerank_by_bm25(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        score_keys = ["bm25_score", "bm25"]
        def get_bm25_score(item: Dict[str, Any]) -> float:
            for key in score_keys:
                if key in item and isinstance(item[key], (int, float)):
                    return float(item[key])
            return 0.0
        for item in results:
            if "_reranking_score" not in item:
                item["_reranking_score"] = get_bm25_score(item)
        sorted_results = sorted(results, key=lambda x: x.get("_reranking_score", 0), reverse=True)
        logger.debug(f"[Reranking]  BM25 : {len(sorted_results)}")
        return sorted_results
    def _rerank_custom(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.config.weight_config:
            logger.warning("[Reranking] ")
            return self._rerank_by_relevance(results)
        def calculate_weighted_score(item: Dict[str, Any]) -> float:
            total_score = 0.0
            total_weight = 0.0
            for field_name, weight in self.config.weight_config.items():
                if field_name in item and isinstance(item[field_name], (int, float)):
                    total_score += float(item[field_name]) * weight
                    total_weight += weight
            return total_score / total_weight if total_weight > 0 else 0.0
        for item in results:
            if "_reranking_score" not in item:
                item["_reranking_score"] = calculate_weighted_score(item)
        sorted_results = sorted(results, key=lambda x: x.get("_reranking_score", 0), reverse=True)
        logger.debug(f"[Reranking] : {self.config.weight_config}, : {len(sorted_results)}")
        return sorted_results
    def _apply_threshold(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered = [item for item in results if item.get("_reranking_score", 0) >= self.config.threshold]
        if len(filtered) < len(results):
            logger.debug(f"[Reranking]  {self.config.threshold}: {len(results)}, : {len(filtered)}")
        return filtered