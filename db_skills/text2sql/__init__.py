"""text2sql - Text-to-SQL with tool-based schema retrieval, powered by Deep Agents."""

from db_skills.text2sql.core import TextSQL
from db_skills.text2sql.connection import Database
from db_skills.text2sql.generate import SQLResult
from db_skills.text2sql.tracing import Tracer

__version__ = "0.3.0"
__all__ = ["TextSQL", "Database", "SQLResult", "Tracer"]

try:
    from db_skills.text2sql.middleware import Text2SqlMiddleware
    __all__.append("Text2SqlMiddleware")
except ImportError:
    pass
