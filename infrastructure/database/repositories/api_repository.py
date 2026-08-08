import json
from utils.common.json_utils import parse_json_field
from loguru import logger
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.api import RkApi, RkApiParam, RkApiNode
from infrastructure.database.repositories.base_repository import BaseRepository
class ApiRepository(BaseRepository[RkApi, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = RkApi
    def _entity_to_dict(self, entity: RkApi, session: Session) -> Dict[str, Any]:
        extend_info_dict = {}
        if entity.extend_info:
            try:
                extend_info_dict = parse_json_field(entity.extend_info)
            except (json.JSONDecodeError, TypeError):
                extend_info_dict = {}
        created_at = getattr(entity, 'create_teller_name', None)
        return {
            'pr_key_id': entity.pr_key_id,
            'name': entity.intfc_name or '',
            'intfc_name': entity.intfc_name or '',
            'intfc_path': entity.intfc_path or '',
            'http_requer_mth_cd': entity.http_requer_mth_cd or '',
            'intfc_invoke_mode_cd': entity.intfc_invoke_mode_cd or '',
            'intfc_sta_cd': entity.intfc_sta_cd or '',
            'vsbl_scope_flag': entity.vsbl_scope_flag or '',
            'intfc_desc': entity.intfc_desc or '',
            'tmout_time_num': entity.tmout_time_num,
            'retry_times': entity.retry_times,
            'extend_info': extend_info_dict,
            'api_base_url': extend_info_dict.get('api_base_url', ''),
            'headers': extend_info_dict.get('headers', {}),
            'parameters': extend_info_dict.get('parameters', {}),
            'req_msg': entity.req_msg or '',
            'resp_msg': entity.resp_msg or '',
            'enabled': entity.intfc_sta_cd == '1',
            'status': entity.intfc_sta_cd,
            'workspace_id': entity.workspace_id,
            'is_public': entity.is_public if entity.is_public is not None else 0,
            'visibility': entity.visibility or '',
            'creator_id': entity.creator_id,
        }
    _pk_name = 'pr_key_id'
    def _entity_to_external_tool_dict(self, entity: RkApi, session: Session) -> Dict[str, Any]:
        intfc_name = entity.intfc_name or ''
        node = None
        node_base_url = ""
        if entity.node_id:
            node_stmt = select(RkApiNode).where(
                and_(
                    RkApiNode.pr_key_id == entity.node_id,
                    RkApiNode.del_flag == '0'
                )
            )
            node = session.scalar(node_stmt)
            if node:
                node_base_url = node.intfc_path or ""
        api_base_url = node_base_url
        http_method_code = entity.http_requer_mth_cd
        method_map = {'1': 'GET', '2': 'POST', '3': 'PUT', '4': 'DELETE'}
        http_method = method_map.get(str(http_method_code), http_method_code) if http_method_code else 'POST'
        endpoint_path = (entity.intfc_path or '').lstrip('/')
        base_url = api_base_url.rstrip('/')
        full_url = f"{base_url}/{endpoint_path}" if endpoint_path else base_url
        examples = []
        if entity.req_msg:
            try:
                req_msg_parsed = json.loads(entity.req_msg) if isinstance(entity.req_msg, str) else entity.req_msg
                if isinstance(req_msg_parsed, list):
                    examples = req_msg_parsed
                elif isinstance(req_msg_parsed, dict):
                    examples = [req_msg_parsed]
                else:
                    examples = [{'input': entity.req_msg}]
            except (json.JSONDecodeError, TypeError):
                examples = [{'input': entity.req_msg}]
        return {
            'name': intfc_name,
            'intfc_name': intfc_name,
            'display_name': intfc_name,
            'description': entity.intfc_desc or '',
            'id': entity.pr_key_id,
            'type': 'api',
            'config': {
                'url': full_url,
                'api_base_url': base_url,
                'api_endpoint': endpoint_path,
                'method': http_method,
                'headers': {},
                'parameters': {},
                'timeout': entity.tmout_time_num or 30,
                'retry_times': entity.retry_times or 0,
            },
            'return_description': entity.resp_msg or '',
            'examples': examples,
            'enabled': entity.intfc_sta_cd == '1',
            'status': entity.intfc_sta_cd,
            'workspace_id': entity.workspace_id,
            'is_public': entity.is_public if entity.is_public is not None else 0,
            'visibility': entity.visibility or '',
            'creator_id': entity.creator_id,
        }
    def get_all(self, return_format: str = 'api', enabled_only: bool = False,
                workspace_id: int = None, viewer_user_id: int = None,
                viewer_workspace_id: int = None, is_admin: bool = False) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(RkApi).where(RkApi.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(RkApi.intfc_sta_cd == '1')
            # 三层可见性过滤（优先）；未提供 viewer_user_id 时回退旧 workspace 精确匹配
            if viewer_user_id is not None or is_admin:
                from utils.common.visibility import build_visibility_orm_filter
                vis_filter = build_visibility_orm_filter(
                    RkApi, viewer_user_id, viewer_workspace_id, is_admin,
                )
                if vis_filter is not None:
                    stmt = stmt.where(vis_filter)
            elif workspace_id is not None:
                stmt = stmt.where(RkApi.workspace_id == workspace_id)
            stmt = stmt.order_by(RkApi.intfc_name)
            entities = session.scalars(stmt).all()
            if return_format == 'external_tool':
                result = [self._entity_to_external_tool_dict(e, session) for e in entities]
            else:
                result = [self._entity_to_dict(e, session) for e in entities]
            logger.debug(f"[Repository] get_all: return_format={return_format}, enabled_only={enabled_only},  {len(result)}  API")
            return result
    def get_by_id(self, api_id: str, return_dict: bool = True) -> Optional[RkApi | Dict[str, Any]]:
        return super().get_by_id(api_id, return_dict=return_dict)
    def get_by_name(self, api_name: str, return_format: str = 'api') -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(RkApi).where(
                and_(
                    RkApi.intfc_name == api_name,
                    RkApi.del_flag == '0'
                )
            )
            result = session.execute(stmt)
            entity = result.scalar_one_or_none()
            if entity:
                if return_format == 'external_tool':
                    return self._entity_to_external_tool_dict(entity, session)
                return self._entity_to_dict(entity, session)
            return None
    def get_tool_parameters(self, tool_name: str) -> Dict[str, Any]:
        """按外部工具 intfc_name 查询其参数（tb_rk_api_param）。

        external_tools.py 与 tools/external_tool.py 均按工具名（intfc_name）调用。
        """
        with self._get_session() as session:
            logger.debug(f"[API] : tool_name={tool_name}")
            param_stmt = select(RkApiParam).where(
                and_(
                    RkApiParam.intfc_name == tool_name,
                    RkApiParam.del_flag == '0'
                )
            )
            entities = session.scalars(param_stmt).all()
            body_params = []
            header_params = {}
            all_params = []
            seen_names = set()
            for entity in entities:
                param_name = entity.para_name or ''
                if param_name in seen_names:
                    logger.debug(f"[API] : {param_name}")
                    continue
                seen_names.add(param_name)
                param_desc = entity.para_desc or ''
                req_flag_code = entity.req_flag_code or '1'
                param_sta = entity.param_sta or '0'
                param_dict = {
                    'param_name': param_name,
                    'param_type': entity.para_type_name or 'string',
                    'param_location': 'header' if req_flag_code == '2' else 'body',
                    'required': param_sta == '1',
                    'default_value': entity.para_value or '',
                    'description': param_desc,
                }
                all_params.append(param_dict)
                if req_flag_code == '2':
                    header_params[param_name] = entity.para_value or ''
                else:
                    body_params.append(param_dict)
            logger.debug(f"[API]  {len(all_params)}  (body: {len(body_params)}, header: {len(header_params)}): tool_name={tool_name}")
            return {
                'body_params': body_params,
                'header_params': header_params,
                'all_params': all_params,
            }
    def save_api(
        self,
        pr_key_id: str,
        intfc_name: str,
        intfc_path: str = "",
        http_requer_mth_cd: str = "POST",
        intfc_invoke_mode_cd: str = "1",
        intfc_desc: str = "",
        tmout_time_num: int = 30,
        retry_times: int = 0,
        extend_info: Dict[str, Any] = None,
        req_msg: str = "",
        resp_msg: str = "",
        enabled: bool = True,
        workspace_id: int = None,
        visibility: str = None,
        creator_id: int = None,
    ) -> bool:
        from utils.common.visibility import normalize_visibility, visibility_to_is_public
        try:
            api_data = {
                'intfc_name': intfc_name,
                'intfc_path': intfc_path,
                'http_requer_mth_cd': http_requer_mth_cd,
                'intfc_invoke_mode_cd': intfc_invoke_mode_cd,
                'intfc_sta_cd': '1' if enabled else '0',
                'intfc_desc': intfc_desc,
                'tmout_time_num': tmout_time_num,
                'retry_times': retry_times,
                'extend_info': json.dumps(extend_info) if extend_info else None,
                'req_msg': req_msg,
                'resp_msg': resp_msg,
                'del_flag': '0'
            }
            if workspace_id is not None:
                api_data['workspace_id'] = workspace_id
            if visibility is not None:
                visibility = normalize_visibility(visibility)
                api_data['visibility'] = visibility
                api_data['is_public'] = visibility_to_is_public(visibility)
            if creator_id is not None:
                api_data['creator_id'] = creator_id
            entity = self.upsert(pr_key_id, **api_data)
            return entity is not None
        except Exception as e:
            logger.error(f"API: {str(e)}", exc_info=True)
            return False
    def delete_api(self, api_id: str) -> bool:
        try:
            with self._get_session() as session:
                session.query(RkApi).filter(
                    RkApi.pr_key_id == api_id
                ).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"API: {str(e)}", exc_info=True)
            return False
    def delete_api_by_name(self, name: str) -> bool:
        """按 intfc_name 软删外部工具（含其参数）。"""
        try:
            with self._get_session() as session:
                session.query(RkApi).filter(
                    and_(RkApi.intfc_name == name, RkApi.del_flag == '0')
                ).update({'del_flag': '1'})
                session.query(RkApiParam).filter(
                    and_(RkApiParam.intfc_name == name, RkApiParam.del_flag == '0')
                ).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"API delete_by_name({name}): {str(e)}", exc_info=True)
            return False
    # ─────────────── 外部工具配置（tb_rk_api 语义） ───────────────
    # method 字符串 ↔ http_requer_mth_cd 映射
    _METHOD_TO_CODE = {'GET': '1', 'POST': '2', 'PUT': '3', 'DELETE': '4'}
    def save_external_tool_config(
        self,
        name: str,
        display_name: str = "",
        description: str = "",
        parameter_descriptions: Dict[str, Any] = None,
        return_description: str = "",
        examples: List[Any] = None,
        api_base_url: str = "",
        api_endpoint: str = "",
        method: str = "POST",
        headers: Dict[str, str] = None,
        parameters: Dict[str, Any] = None,
        http_config_name: str = "",
        enabled: bool = True,
        enable_reranking: bool = False,
        reranking_config: Dict[str, Any] = None,
        config_json: str = None,
        parameters_list: List[Dict[str, Any]] = None,
        workspace_id: int = None,
        visibility: str = None,
        creator_id: int = None,
    ) -> bool:
        """保存外部工具配置到 tb_rk_api（按 intfc_name=name upsert）。

        将外部工具语义字段映射到 RkApi 列：extend_info 存 api_base_url/headers/
        parameters/http_config_name 等；req_msg 存 examples；resp_msg 存
        return_description；http_requer_mth_cd 存 method 的 code。
        """
        from utils.common.visibility import normalize_visibility, visibility_to_is_public
        try:
            method_code = self._METHOD_TO_CODE.get(
                str(method).upper(), self._METHOD_TO_CODE.get('POST', '2'),
            )
            extend_info = {
                'api_base_url': api_base_url or '',
                'headers': headers or {},
                'parameters': parameters or {},
                'http_config_name': http_config_name or '',
                'display_name': display_name or '',
                'parameter_descriptions': parameter_descriptions or {},
                'enable_reranking': enable_reranking,
                'reranking_config': reranking_config,
                'config_json': config_json or '',
            }
            req_msg = json.dumps(examples, ensure_ascii=False) if examples else None
            api_data = {
                'intfc_name': name,
                'intfc_path': api_endpoint or '',
                'http_requer_mth_cd': method_code,
                'intfc_invoke_mode_cd': '1',
                'intfc_sta_cd': '1' if enabled else '0',
                'intfc_desc': description or '',
                'tmout_time_num': 30,
                'retry_times': 0,
                'extend_info': json.dumps(extend_info, ensure_ascii=False),
                'req_msg': req_msg,
                'resp_msg': return_description or '',
                'del_flag': '0',
            }
            if workspace_id is not None:
                api_data['workspace_id'] = workspace_id
            if visibility is not None:
                visibility = normalize_visibility(visibility)
                api_data['visibility'] = visibility
                api_data['is_public'] = visibility_to_is_public(visibility)
            if creator_id is not None:
                api_data['creator_id'] = creator_id
            with self._get_session() as session:
                existing = session.query(RkApi).filter(
                    and_(RkApi.intfc_name == name, RkApi.del_flag == '0')
                ).first()
                if existing:
                    for k, v in api_data.items():
                        if hasattr(existing, k):
                            setattr(existing, k, v)
                else:
                    session.add(RkApi(**api_data))
                session.commit()
            # 可选：保存 parameter_list → tb_rk_api_param
            if parameters_list:
                self.delete_all_tool_parameters(name)
                for param in parameters_list:
                    try:
                        self.save_tool_parameter(
                            tool_name=name,
                            param_name=param.get('param_name', ''),
                            param_type=param.get('param_type', 'string'),
                            required=param.get('required', False),
                            default_value=param.get('default_value'),
                            description=param.get('description', ''),
                            param_location=param.get('param_location', 'body'),
                            validation_rules=param.get('validation_rules', {}),
                            param_order=param.get('param_order', 0),
                        )
                    except Exception as pe:
                        logger.warning(f"外部工具 {name} 参数 {param.get('param_name')} 保存失败: {pe}")
            return True
        except Exception as e:
            logger.error(f"外部工具配置保存失败({name}): {str(e)}", exc_info=True)
            return False
    def save_tool_parameter(
        self,
        tool_name: str,
        param_name: str,
        param_type: str = "string",
        required: bool = False,
        default_value: str = None,
        description: str = "",
        param_location: str = "body",
        validation_rules: Dict[str, Any] = None,
        param_order: int = 0,
    ) -> bool:
        """保存外部工具参数到 tb_rk_api_param（按 intfc_name+para_name upsert）。"""
        try:
            req_flag_code = '2' if param_location == 'header' else '1'
            param_data = {
                'intfc_name': tool_name,
                'intfc_path': '',
                'req_flag_code': req_flag_code,
                'para_name': param_name,
                'para_type_name': param_type,
                'para_desc': description,
                'para_value': default_value or '',
                'param_sta': '1' if required else '0',
                'del_flag': '0',
            }
            with self._get_session() as session:
                existing = session.query(RkApiParam).filter(
                    and_(
                        RkApiParam.intfc_name == tool_name,
                        RkApiParam.para_name == param_name,
                        RkApiParam.del_flag == '0',
                    )
                ).first()
                if existing:
                    for k, v in param_data.items():
                        if hasattr(existing, k):
                            setattr(existing, k, v)
                else:
                    session.add(RkApiParam(**param_data))
                session.commit()
            return True
        except Exception as e:
            logger.error(f"外部工具参数保存失败({tool_name}/{param_name}): {str(e)}", exc_info=True)
            return False
    def delete_all_tool_parameters(self, tool_name: str) -> bool:
        """软删某外部工具的所有参数（重建参数前清旧）。"""
        try:
            with self._get_session() as session:
                session.query(RkApiParam).filter(
                    and_(
                        RkApiParam.intfc_name == tool_name,
                        RkApiParam.del_flag == '0',
                    )
                ).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"外部工具参数清空失败({tool_name}): {str(e)}", exc_info=True)
            return False
    def delete_tool_parameter(self, tool_name: str, param_name: str) -> bool:
        """软删单个外部工具参数。"""
        try:
            with self._get_session() as session:
                updated = session.query(RkApiParam).filter(
                    and_(
                        RkApiParam.intfc_name == tool_name,
                        RkApiParam.para_name == param_name,
                        RkApiParam.del_flag == '0',
                    )
                ).update({'del_flag': '1'})
                session.commit()
                return updated > 0
        except Exception as e:
            logger.error(f"外部工具参数删除失败({tool_name}/{param_name}): {str(e)}", exc_info=True)
            return False
class RkApiNodeRepository(BaseRepository[RkApiNode, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = RkApiNode
    def _entity_to_dict(self, entity: RkApiNode, session: Session) -> Dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'node_name': entity.node_name or '',
            'agent_node_no': entity.agent_node_no or '',
            'api_base_url': entity.intfc_path or '',
            'node_desc': entity.node_desc or '',
            'server_run_envnm_cd': entity.server_run_envnm_cd or '',
            'node_status': entity.node_status or '1',
            'belong_area_name': entity.belong_area_name or '',
            'enabled': entity.node_status == '1',
        }
    _pk_name = 'pr_key_id'
    def get_all(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(RkApiNode).where(RkApiNode.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(RkApiNode.node_status == '1')
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
class RkApiParamRepository(BaseRepository[RkApiParam, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = RkApiParam
    def _entity_to_dict(self, entity: RkApiParam, session: Session) -> Dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'intfc_name': entity.intfc_name or '',
            'intfc_path': entity.intfc_path or '',
            'req_flag_code': entity.req_flag_code or '1',
            'para_name': entity.para_name or '',
            'para_type_name': entity.para_type_name or 'string',
            'para_desc': entity.para_desc or '',
            'para_value': entity.para_value or '',
            'param_sta': entity.param_sta or '0',
        }
    _pk_name = 'pr_key_id'
    def get_by_api_id(self, api_id: str) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            param_stmt = select(RkApiParam).where(
                and_(
                    RkApiParam.pr_key_id == api_id,
                    RkApiParam.del_flag == '0'
                )
            )
            entities = session.scalars(param_stmt).all()
            seen_names = set()
            result = []
            for e in entities:
                param_name = e.para_name or ''
                if param_name in seen_names:
                    continue
                seen_names.add(param_name)
                result.append(self._entity_to_dict(e, session))
            logger.debug(f"[RkApiParamRepository] get_by_api_id: api_id={api_id},  {len(result)} ")
            return result
    def get_by_intfc_name(self, intfc_name: str) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(RkApiParam).where(
                and_(
                    RkApiParam.intfc_name == intfc_name,
                    RkApiParam.del_flag == '0'
                )
            )
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
RkApiRepository = ApiRepository