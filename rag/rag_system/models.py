# rag/rag_system/models.py
# RAG 返回数据结构（对齐 unstructured_knowledge_tool.py 接口契约）
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Chunk:
    """检索结果块（对齐接口契约：doc_name/node_title/content）。

    引用定位（citation locator）：
    - page: PDF 页码（1 基），txt/md 为 None
    - char_start/char_end: 文档分片（页）内字符偏移 [start, end)
    - citation: 人类可读引用串（如 'report.pdf · p.3 · chars 1024-1500'）
    """
    doc_name: str
    node_title: str
    content: str
    page: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

    @property
    def citation(self) -> str:
        """人类可读引用定位串。无定位信息时退化为 doc_name。"""
        parts = [self.doc_name]
        if self.page:
            parts.append(f"p.{self.page}")
        if self.char_start is not None and self.char_end is not None:
            parts.append(f"chars {self.char_start}-{self.char_end}")
        return " · ".join(parts)


@dataclass
class RetrieveResult:
    """检索结果（对齐接口契约：query/strategy/latency_ms/chunks）。"""
    query: str
    strategy: str
    latency_ms: float
    chunks: List[Chunk] = field(default_factory=list)
