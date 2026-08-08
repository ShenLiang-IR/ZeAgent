# rag/rag_system/document_loader.py
# 文档加载（Text/PDF/Markdown）
from pathlib import Path
from loguru import logger


def load_document(file_path: str) -> list:
    """加载文档，返回文本列表。支持 .txt/.md/.pdf。"""
    ext = Path(file_path).suffix.lower()
    try:
        if ext == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader
            docs = PyPDFLoader(file_path).load()
        else:
            # TextLoader 默认可能用系统编码，显式指定 UTF-8
            from langchain_community.document_loaders import TextLoader
            docs = TextLoader(file_path, encoding="utf-8").load()
        return [d.page_content for d in docs]
    except Exception as e:
        logger.error(f"[DocumentLoader] 加载失败 {file_path}: {e}")
        # 降级：直接读文件
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return [f.read()]
        except Exception as e2:
            logger.error(f"[DocumentLoader] 降级读取也失败: {e2}")
            raise


def load_document_with_meta(file_path: str) -> list:
    """加载文档，返回分片列表 [{content, page}, ...]（引用定位用）。

    page 语义：
    - PDF：1 基页码（PyPDFLoader metadata.page 为 0 基，+1 还原）
    - txt/md：None（无分页概念）

    与 load_document 的区别：保留分片级元数据，供 ingest 写入
    页码/字符偏移定位。加载失败同样降级为整文件单分片。
    """
    ext = Path(file_path).suffix.lower()
    try:
        if ext == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader
            docs = PyPDFLoader(file_path).load()
            return [
                {"content": d.page_content,
                 "page": (d.metadata or {}).get("page", i) + 1}
                for i, d in enumerate(docs)
            ]
        from langchain_community.document_loaders import TextLoader
        docs = TextLoader(file_path, encoding="utf-8").load()
        return [{"content": d.page_content, "page": None} for d in docs]
    except Exception as e:
        logger.error(f"[DocumentLoader] 带元数据加载失败 {file_path}: {e}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return [{"content": f.read(), "page": None}]
        except Exception as e2:
            logger.error(f"[DocumentLoader] 降级读取也失败: {e2}")
            raise
