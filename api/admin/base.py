import io
import json
import zipfile
from typing import Dict, List, Any, Optional, Type, Callable
from fastapi import APIRouter, HTTPException, Depends, UploadFile, Query
from fastapi.responses import Response
from pydantic import BaseModel
from loguru import logger
from .permissions import require_read, require_write, require_delete
from .common import verify_token, reload_config
from utils.common.permissions import UserPermissions
class CRUDResponse(BaseModel):
    success: bool = True
    message: str = ""
    status: str = "success"
    data: Any = None
def wrap_response(data: Any = None, message: str = "success", success: bool = True) -> Dict[str, Any]:
    return {
        "code": "0000000000000000" if success else "9999999999999999",
        "message": message,
        "data": data
    }
def create_crud_router(
    repository: Any,
    resource_name: str,
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    tags: List[str],
    prefix: str,
    search_fields: List[str] = ["name", "display_name", "description"],
    id_field: str = "name",
    reload_after_write: bool = True,
    create_func: Optional[Callable] = None,
    update_func: Optional[Callable] = None,
    delete_func: Optional[Callable] = None
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=tags, dependencies=[Depends(verify_token)])
    def _get_item_from_repo(id_value: str):
        item = None
        if hasattr(repository, 'get_by_id'):
            item = repository.get_by_id(id_value, return_dict=True)
        if not item and hasattr(repository, 'get_by_name'):
            item = repository.get_by_name(id_value)
        return item
    @router.get("")
    async def list_items(
        skip: int = Query(0, ge=0),
        limit: int = Query(10, ge=1, le=100),
        search: str = Query(""),
        enabled: Optional[bool] = Query(None),
        user_permissions: UserPermissions = Depends(require_read(resource_name))
    ):
        try:
            all_items = repository.get_all() or []
            filtered_items = all_items
            if enabled is not None:
                target_val = 1 if enabled else 0
                filtered_items = [
                    item for item in filtered_items 
                    if item.get("enabled") == target_val or item.get("enabled") is enabled
                ]
            if search:
                s = search.lower()
                filtered_items = [
                    item for item in filtered_items
                    if any(s in str(item.get(field, "")).lower() for field in search_fields)
                ]
            total = len(filtered_items)
            paginated = filtered_items[skip : skip + limit]
            return wrap_response({
                resource_name + "s": paginated,
                "total": total,
                "count": len(paginated),
                "skip": skip,
                "limit": limit
            })
        except Exception as e:
            logger.error(f"{resource_name}操作失败: {e}")
            raise HTTPException(status_code=500, detail=f"查询{resource_name}列表失败: {str(e)}")
    @router.get("/{id_value}")
    async def get_item(
        id_value: str,
        user_permissions: UserPermissions = Depends(require_read(resource_name))
    ):
        try:
            item = _get_item_from_repo(id_value)
            if not item:
                raise HTTPException(status_code=404, detail=f"{resource_name}不存在: {id_value}")
            return wrap_response(item)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"{resource_name}操作失败({id_value}): {e}")
            raise HTTPException(status_code=500, detail=str(e))
    @router.post("")
    async def create_item(
        data: create_schema,
        user_permissions: UserPermissions = Depends(require_write(resource_name))
    ):
        try:
            logger.info(f"用户{user_permissions.user_id}创建{resource_name}: {getattr(data, id_field, 'unknown')}")
            id_value = getattr(data, id_field, None)
            if id_value and _get_item_from_repo(id_value):
                raise HTTPException(status_code=400, detail=f"{resource_name}已存在: {id_value}")
            if create_func:
                result = await create_func(data)
            else:
                save_method_name = f"save_{resource_name}_config"
                alt_save_method_name = f"save_{resource_name}"
                if hasattr(repository, save_method_name):
                    result = getattr(repository, save_method_name)(**data.model_dump())
                elif hasattr(repository, alt_save_method_name):
                    result = getattr(repository, alt_save_method_name)(**data.model_dump())
                else:
                    result = repository.create(**data.model_dump())
            if not result:
                raise HTTPException(status_code=500, detail=f"{resource_name}操作失败")
            if reload_after_write:
                reload_config()
            return wrap_response(message=f"{resource_name}操作成功")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"{resource_name}操作失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    @router.put("/{id_value}")
    async def update_item(
        id_value: str,
        data: update_schema,
        user_permissions: UserPermissions = Depends(require_write(resource_name))
    ):
        try:
            logger.info(f"用户{user_permissions.user_id}操作{resource_name}: {id_value}")
            if not _get_item_from_repo(id_value):
                raise HTTPException(status_code=404, detail=f"{resource_name}不存在: {id_value}")
            new_id = getattr(data, id_field, id_value)
            if new_id != id_value:
                if _get_item_from_repo(new_id):
                    raise HTTPException(status_code=400, detail=f"{resource_name}已存在: {new_id}")
                repository.delete(id_value)
            if update_func:
                result = await update_func(id_value, data)
            else:
                save_method_name = f"save_{resource_name}_config"
                alt_save_method_name = f"save_{resource_name}"
                if hasattr(repository, save_method_name):
                    result = getattr(repository, save_method_name)(**data.model_dump())
                elif hasattr(repository, alt_save_method_name):
                    result = getattr(repository, alt_save_method_name)(**data.model_dump())
                else:
                    result = repository.update(new_id if new_id != id_value else id_value, **data.model_dump())
            if not result:
                raise HTTPException(status_code=500, detail=f"{resource_name}操作失败")
            if reload_after_write:
                reload_config()
            return wrap_response(message=f"{resource_name}操作成功")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"{resource_name}操作失败({id_value}): {e}")
            raise HTTPException(status_code=500, detail=str(e))
    @router.delete("/{id_value}")
    async def delete_item(
        id_value: str,
        user_permissions: UserPermissions = Depends(require_delete(resource_name))
    ):
        try:
            logger.info(f"用户{user_permissions.user_id}操作{resource_name}: {id_value}")
            if delete_func:
                success = await delete_func(id_value)
            else:
                if not _get_item_from_repo(id_value):
                    raise HTTPException(status_code=404, detail=f"{resource_name}不存在: {id_value}")
                success = repository.delete(id_value)
            if not success:
                raise HTTPException(status_code=500, detail=f"{resource_name}操作失败")
            if reload_after_write:
                reload_config()
            return wrap_response(message=f"{resource_name}操作成功")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"{resource_name}操作失败({id_value}): {e}")
            raise HTTPException(status_code=500, detail=str(e))
    @router.patch("/{id_value}/toggle")
    async def toggle_item(
        id_value: str,
        enabled: bool = Query(...),
        user_permissions: UserPermissions = Depends(require_write(resource_name))
    ):
        try:
            logger.info(f"用户{user_permissions.user_id}切换{resource_name}状态: {id_value} -> {enabled}")
            toggle_method_name = f"toggle_{resource_name}_enabled"
            if hasattr(repository, toggle_method_name):
                success = getattr(repository, toggle_method_name)(id_value, enabled)
            else:
                result = repository.update(id_value, enabled=enabled)
                success = result is not None
            if not success:
                raise HTTPException(status_code=500, detail=f"切换{resource_name}启用状态失败")
            if reload_after_write:
                reload_config()
            return wrap_response(data={"enabled": enabled}, message=f"{resource_name}启用状态已更新")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"{resource_name}操作失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    return router
async def handle_import_files(
    files: List[UploadFile],
    import_func: Callable[[Dict[str, Any]], Dict[str, Any]],
    resource_name: str
) -> Dict[str, Any]:
    all_imported = []
    all_failed = []
    for file in files:
        if not file.filename: continue
        try:
            content = await file.read()
            configs = []
            if file.filename.endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(content), 'r') as zipf:
                    json_files = [n for n in zipf.namelist() if n.endswith('.json')]
                    for name in json_files:
                        try:
                            data = json.loads(zipf.read(name).decode('utf-8'))
                            if isinstance(data, list): configs.extend(data)
                            else: configs.append(data)
                        except Exception as e:
                            all_failed.append({"name": name, "error": f"JSON: {str(e)}", "file": file.filename})
            else:
                data = json.loads(content.decode('utf-8'))
                if isinstance(data, list): configs = data
                elif isinstance(data, dict):
                    plural_name = resource_name + "s"
                    if plural_name in data: configs = data[plural_name]
                    elif "items" in data: configs = data["items"]
                    else: configs = [data]
            for config in configs:
                try:
                    import_res = import_func(config)
                    all_imported.append(import_res)
                except Exception as e:
                    all_failed.append({"name": config.get('name', 'unknown'), "error": str(e), "file": file.filename})
        except Exception as e:
            all_failed.append({"name": "", "error": str(e), "file": file.filename})
    if all_imported:
        reload_config()
    return wrap_response({
        "imported": all_imported,
        "failed": all_failed,
        "count": len(all_imported)
    }, message=f"导入完成: 成功 {len(all_imported)} 个, 失败 {len(all_failed)} 个")
def handle_export_all(
    items: List[Dict[str, Any]],
    resource_name: str,
    filename_prefix: str
) -> Response:
    if not items:
        raise HTTPException(status_code=404, detail="无可导出的数据")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for item in items:
            name = item.get('name', 'unknown')
            export_data = {k: v for k, v in item.items() if k not in ['id', 'created_at', 'updated_at']}
            json_content = json.dumps(export_data, ensure_ascii=False, indent=2)
            zipf.writestr(f"{resource_name}s/{name}.json", json_content)
    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename_prefix}_all.zip"'}
    )