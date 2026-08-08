# rag/rag_system/chunker.py
# 文档分块（RecursiveCharacterTextSplitter + 结构感知 + 父子文档）
from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing import List, Dict, Any
from loguru import logger

DEFAULT_BY_TYPE = {"pdf": (1000, 200), "txt": (500, 100), "md": (512, 51)}


def create_chunker(chunk_size: int = 500, chunk_overlap: int = 100,
                    doc_type: str = None, by_doc_type: dict = None):
    """创建文本分块器（RecursiveCharacterTextSplitter，按文档类型调整参数）。"""
    if doc_type and by_doc_type:
        cfg = by_doc_type.get(doc_type)
        if cfg:
            chunk_size, chunk_overlap = cfg[0], cfg[1]
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )


# ===== 结构感知分块 =====

def create_structure_chunker(doc_type: str, headers: list = None):
    """按文档结构分块（Markdown/HTML/Python/JSON）。"""
    if doc_type == "md":
        from langchain_text_splitters import MarkdownHeaderTextSplitter
        h = headers or [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
        return MarkdownHeaderTextSplitter(headers_to_split_on=h)
    elif doc_type == "html":
        from langchain_text_splitters import HTMLHeaderTextSplitter
        h = headers or [("h1", "Header 1"), ("h2", "Header 2"), ("h3", "Header 3")]
        return HTMLHeaderTextSplitter(headers_to_split_on=h)
    elif doc_type == "py" or doc_type == "python":
        from langchain_text_splitters import PythonCodeTextSplitter
        return PythonCodeTextSplitter(chunk_size=500, chunk_overlap=50)
    elif doc_type == "json":
        from langchain_text_splitters import RecursiveJsonSplitter
        return RecursiveJsonSplitter(max_chunk_size=500)
    return None


def split_by_structure(text: str, doc_type: str, headers: list = None) -> List[Dict[str, Any]]:
    """结构感知分块。返回 [{content, node_title, metadata}, ...]。"""
    splitter = create_structure_chunker(doc_type, headers)
    if splitter is None:
        return [{"content": text, "node_title": "full", "metadata": {}}]
    docs = splitter.split_text(text)
    chunks = []
    for i, doc in enumerate(docs):
        node_title = " > ".join(str(v) for v in (doc.metadata or {}).values()) or f"section_{i}"
        chunks.append({
            "content": doc.page_content,
            "node_title": node_title,
            "metadata": doc.metadata or {},
        })
    logger.info(f"[Chunker] structure split: {len(chunks)} chunks (type={doc_type})")
    return chunks


# ===== 父子文档分块 =====

class ParentChildChunker:
    """父子文档分块：父块（粗粒度）+ 子块（细粒度）。检索子块，返回父块。"""

    def __init__(self, parent_chunk_size: int = 1000, parent_overlap: int = 200,
                 child_chunk_size: int = 200, child_overlap: int = 20):
        self._parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=parent_chunk_size, chunk_overlap=parent_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
        self._child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size, chunk_overlap=child_overlap,
            separators=["\n", " ", ""],
        )
        logger.info(f"[ParentChildChunker] parent={parent_chunk_size}/{parent_overlap} "
                     f"child={child_chunk_size}/{child_overlap}")

    def split(self, text: str, doc_name: str = "unknown") -> List[Dict[str, Any]]:
        """分块。返回 [{parent_id, parent_content, child_id, child_content, doc_name}, ...]。"""
        parent_chunks = self._parent_splitter.split_text(text)
        results = []
        for p_idx, parent in enumerate(parent_chunks):
            child_chunks = self._child_splitter.split_text(parent)
            for c_idx, child in enumerate(child_chunks):
                results.append({
                    "parent_id": f"parent_{p_idx}",
                    "parent_content": parent,
                    "child_id": f"parent_{p_idx}_child_{c_idx}",
                    "child_content": child,
                    "doc_name": doc_name,
                })
        logger.info(f"[ParentChildChunker] split: {len(parent_chunks)} parents → "
                    f"{len(results)} children")
        return results
