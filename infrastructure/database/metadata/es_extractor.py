from typing import List, Dict, Any
from loguru import logger
from .base_extractor import (
    BaseMetadataExtractor,
    ColumnInfo,
    TableInfo,
    DatabaseType,
)
class ESMetadataExtractor(BaseMetadataExtractor):
    def __init__(self, db_config: Dict[str, Any]):
        super().__init__(db_config)
        self.db_type = DatabaseType.ELASTICSEARCH
        self._client = None
    async def connect(self) -> None:
        try:
            from elasticsearch import AsyncElasticsearch
            import elastic_transport
            elastic_transport._verified_elasticsearch = True
            hosts = self.db_config.get('host', 'localhost').split(',')
            port = self.db_config.get('port', 9200)
            use_ssl = self.db_config.get('use_ssl', False)
            verify_certs = self.db_config.get('verify_certs', True)
            es_hosts = [
                f"{'https' if use_ssl else 'http'}://{h.strip()}:{port}"
                for h in hosts
            ]
            client_kwargs = {
                'hosts': es_hosts,
                'verify_certs': verify_certs,
            }
            if self.db_config.get('api_key'):
                client_kwargs['api_key'] = self.db_config['api_key']
            elif self.db_config.get('username') and self.db_config.get('password'):
                client_kwargs['http_auth'] = (
                    self.db_config['username'],
                    self.db_config['password']
                )
            elif self.db_config.get('username') and self.db_config.get('pwd'):
                client_kwargs['http_auth'] = (
                    self.db_config['username'],
                    self.db_config['pwd']
                )
            elif self.db_config.get('user') and self.db_config.get('password'):
                client_kwargs['http_auth'] = (
                    self.db_config['user'],
                    self.db_config['password']
                )
            elif self.db_config.get('user') and self.db_config.get('pwd'):
                client_kwargs['http_auth'] = (
                    self.db_config['user'],
                    self.db_config['pwd']
                )
            if self.db_config.get('ca_certs'):
                client_kwargs['ca_certs'] = self.db_config['ca_certs']
            self._client = AsyncElasticsearch(**client_kwargs)
            info = await self._client.info()
            logger.debug(f"[ESMetadataExtractor] : {info.get('cluster_name', 'unknown')}")
        except Exception as e:
            logger.error(f"[ESMetadataExtractor] : {e}")
            raise
    async def disconnect(self) -> None:
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning(f"[ESMetadataExtractor] : {e}")
            finally:
                self._client = None
    async def get_all_tables(self) -> List[TableInfo]:
        if not self._client:
            await self.connect()
        index_pattern = self.db_config.get('index_pattern', '*')
        try:
            indices = await self._client.cat.indices(
                index=index_pattern,
                format='json',
                h='index,docs.count,store.size'
            )
            tables = []
            for idx in indices:
                index_name = idx.get('index', '')
                if index_name.startswith('.'):
                    continue
                tables.append(TableInfo(
                    table_name=index_name,
                    table_comment=f": {idx.get('docs.count', 'N/A')}, : {idx.get('store.size', 'N/A')}",
                    schema_name='',
                    columns=[]
                ))
            logger.debug(f"[ESMetadataExtractor]  {len(tables)} ")
            return tables
        except Exception as e:
            logger.error(f"[ESMetadataExtractor] : {e}")
            raise
    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        if not self._client:
            await self.connect()
        try:
            mapping = await self._client.indices.get_mapping(index=table_name)
            columns = []
            for idx_name, idx_data in mapping.items():
                properties = idx_data.get('mappings', {}).get('properties', {})
                columns.extend(self._parse_mapping_properties(properties))
            logger.debug(f"[ESMetadataExtractor]  {table_name}  {len(columns)} ")
            return columns
        except Exception as e:
            logger.error(f"[ESMetadataExtractor] : {e}")
            raise
    def _parse_mapping_properties(
        self,
        properties: Dict[str, Any],
        parent_path: str = ''
    ) -> List[ColumnInfo]:
        columns = []
        for field_name, field_info in properties.items():
            full_path = f"{parent_path}.{field_name}" if parent_path else field_name
            field_type = field_info.get('type', 'object')
            if field_type == 'object':
                nested_props = field_info.get('properties', {})
                columns.extend(self._parse_mapping_properties(nested_props, full_path))
            elif field_type == 'nested':
                nested_props = field_info.get('properties', {})
                columns.append(ColumnInfo(
                    column_name=full_path,
                    data_type='nested',
                    is_nullable=True,
                    column_comment='',
                    is_primary_key=False,
                    default_value=''
                ))
                columns.extend(self._parse_mapping_properties(nested_props, full_path))
            else:
                columns.append(ColumnInfo(
                    column_name=full_path,
                    data_type=self._map_es_type(field_type),
                    is_nullable=True,
                    column_comment=field_info.get('fields', {}).get('keyword', {}).get('type', ''),
                    is_primary_key=(field_name == '_id'),
                    default_value=''
                ))
        return columns
    def _map_es_type(self, es_type: str) -> str:
        type_mapping = {
            'text': 'text',
            'keyword': 'string',
            'integer': 'int',
            'long': 'bigint',
            'float': 'float',
            'double': 'double',
            'date': 'timestamp',
            'boolean': 'boolean',
            'object': 'object',
            'nested': 'nested',
            'geo_point': 'geo_point',
            'ip': 'ip',
            'binary': 'binary',
        }
        return type_mapping.get(es_type, es_type)
    async def get_table_full_info(self, table_name: str, include_samples: bool = True) -> TableInfo:
        if not self._client:
            await self.connect()
        try:
            stats = await self._client.indices.stats(index=table_name)
            total_docs = stats.get('indices', {}).get(table_name, {}).get('total', {}).get('docs', {}).get('count', 0)
            columns = await self.get_table_columns(table_name)
            if include_samples and columns:
                sample_values_map = await self.get_column_sample_values(
                    table_name,
                    [col.column_name for col in columns if col.data_type in ('text', 'string', 'keyword', 'int', 'bigint', 'float', 'double', 'timestamp')]
                )
                for col in columns:
                    if col.column_name in sample_values_map:
                        col.sample_values = sample_values_map[col.column_name]
            return TableInfo(
                table_name=table_name,
                table_comment=f": {total_docs}",
                schema_name='',
                columns=columns
            )
        except Exception as e:
            logger.error(f"[ESMetadataExtractor] : {e}")
            raise
    async def get_column_sample_values(
        self,
        table_name: str,
        column_names: List[str],
        limit: int = 3
    ) -> Dict[str, List[str]]:
        if not self._client:
            await self.connect()
        sample_values = {col: [] for col in column_names}
        for column_name in column_names:
            try:
                response = await self._client.search(
                    index=table_name,
                    size=limit,
                    _source=[column_name],
                    query={"exists": {"field": column_name}},
                    sort=[{"_id": "desc"}]
                )
                hits = response.get('hits', {}).get('hits', [])
                values = []
                for hit in hits:
                    source = hit.get('_source', {})
                    val = source
                    for part in column_name.split('.'):
                        val = val.get(part, '') if isinstance(val, dict) else ''
                    if val:
                        values.append(str(val)[:100])
                sample_values[column_name] = values
            except Exception as e:
                logger.debug(f"[ESMetadataExtractor]  {column_name} : {e}")
                sample_values[column_name] = []
        return sample_values