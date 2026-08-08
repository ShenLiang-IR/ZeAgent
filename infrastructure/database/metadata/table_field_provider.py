from collections import defaultdict
from typing import Dict, List, Optional
from loguru import logger
from infrastructure.database.metadata.base_extractor import ColumnInfo, TableInfo
async def get_tables_from_table_field(
    knowledge_base_id: str,
    table_names: Optional[List[str]] = None,
) -> List[TableInfo]:
    from utils.config.config_db import get_config_db
    config_db = get_config_db()
    fields = config_db.knowledge_table_fields.get_enabled_by_kb(knowledge_base_id)
    if not fields:
        logger.debug(
            f"[TableFieldProvider]  {knowledge_base_id} "
        )
        return []
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for field in fields:
        grouped[field['table_name']].append(field)
    if table_names:
        table_names_set = set(table_names)
        grouped = {k: v for k, v in grouped.items() if k in table_names_set}
    tables: List[TableInfo] = []
    for tbl_name, tbl_fields in grouped.items():
        columns = [
            ColumnInfo(
                column_name=f['field_name'],
                data_type=f['field_type'] or '',
                column_comment=f['field_desc'] or '',
            )
            for f in tbl_fields
        ]
        tables.append(TableInfo(
            table_name=tbl_name,
            table_comment='',
            columns=columns,
        ))
    logger.debug(
        f"[TableFieldProvider]  {knowledge_base_id} "
        f" {len(tables)} ,  {len(fields)} "
    )
    return tables