from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum
class DatabaseType(Enum):
    POSTGRESQL = "postgresql"
    DORIS = "doris"
    MYSQL = "mysql"
    ELASTICSEARCH = "elasticsearch"
@dataclass
class ColumnInfo:
    column_name: str
    data_type: str
    is_nullable: bool = True
    column_comment: str = ""
    is_primary_key: bool = False
    default_value: str = ""
    extra_info: Dict[str, Any] = field(default_factory=dict)
    sample_values: List[str] = field(default_factory=list)
    def to_prompt_text(self) -> str:
        parts = [f"- {self.column_name}: {self.data_type}"]
        if self.column_comment:
            parts[0] += f" ({self.column_comment})"
        if self.is_primary_key:
            parts.append("  []")
        if not self.is_nullable:
            parts.append("  []")
        if self.sample_values:
            samples = self.sample_values[:3]
            parts.append(f"  : {', '.join(samples)}")
        return "\n".join(parts)
@dataclass
class TableInfo:
    table_name: str
    table_comment: str = ""
    columns: List[ColumnInfo] = field(default_factory=list)
    schema_name: str = ""
    @property
    def full_name(self) -> str:
        if self.schema_name:
            return f"{self.schema_name}.{self.table_name}"
        return self.table_name
    def to_prompt_text(self, include_columns: bool = True, include_samples: bool = True) -> str:
        lines = [f"### {self.full_name}"]
        if self.table_comment:
            lines[0] += f" ({self.table_comment})"
        if include_columns and self.columns:
            lines.append("")
            for col in self.columns:
                if include_samples and col.sample_values:
                    lines.append(col.to_prompt_text())
                else:
                    col_text = f"- {col.column_name}: {col.data_type}"
                    if col.column_comment:
                        col_text += f" ({col.column_comment})"
                    lines.append(col_text)
        return "\n".join(lines)
    def get_table_summary(self) -> str:
        if self.table_comment:
            return f"{self.table_name} ({self.table_comment})"
        return self.table_name
@dataclass
class MetadataCacheEntry:
    tables: List[TableInfo]
    timestamp: float
    ttl_seconds: int = 3600
    def is_expired(self) -> bool:
        import time
        return time.time() - self.timestamp > self.ttl_seconds
class BaseMetadataExtractor(ABC):
    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config
        db_type_str = db_config.get('type', 'postgresql').lower()
        if db_type_str == 'es' or db_type_str == 'elastic':
            db_type_str = 'elasticsearch'
        self.db_type = DatabaseType(db_type_str)
        self._connection = None
    @abstractmethod
    async def connect(self) -> None:
        pass
    @abstractmethod
    async def disconnect(self) -> None:
        pass
    @abstractmethod
    async def get_all_tables(self) -> List[TableInfo]:
        pass
    @abstractmethod
    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        pass
    @abstractmethod
    async def get_table_full_info(self, table_name: str) -> TableInfo:
        pass
    async def get_tables_with_columns(self, table_names: List[str]) -> List[TableInfo]:
        tables = []
        for table_name in table_names:
            try:
                table_info = await self.get_table_full_info(table_name)
                tables.append(table_info)
            except Exception as e:
                from loguru import logger
                logger.warning(f"获取表 {table_name} 元数据失败: {e}")
        return tables
    def get_schema_name(self) -> str:
        return self.db_config.get('schema', '')
    def get_database_name(self) -> str:
        return self.db_config.get('database', '')
    async def __aenter__(self):
        await self.connect()
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
        return False