from .base_extractor import (
    BaseMetadataExtractor,
    ColumnInfo,
    TableInfo,
    DatabaseType,
    MetadataCacheEntry,
)
from .postgres_extractor import PostgresMetadataExtractor
from .doris_extractor import DorisMetadataExtractor
from .es_extractor import ESMetadataExtractor
from .metadata_cache import MetadataCache, get_metadata_cache
from .table_field_provider import get_tables_from_table_field
def create_extractor(db_config: dict, db_type: str = None):
    if db_type is None:
        db_type = (db_config.get('type') or db_config.get('dbtype') or 'postgresql').lower()
    if db_type in ('postgresql', 'postgres'):
        return PostgresMetadataExtractor(db_config)
    elif db_type in ('doris', 'mysql'):
        return DorisMetadataExtractor(db_config)
    elif db_type in ('elasticsearch', 'es', 'elastic'):
        return ESMetadataExtractor(db_config)
    else:
        raise ValueError(f"不支持的元数据数据库类型: {db_type}")
__all__ = [
    "BaseMetadataExtractor",
    "ColumnInfo",
    "TableInfo",
    "DatabaseType",
    "MetadataCacheEntry",
    "PostgresMetadataExtractor",
    "DorisMetadataExtractor",
    "ESMetadataExtractor",
    "MetadataCache",
    "get_metadata_cache",
    "create_extractor",
    "get_tables_from_table_field",
]