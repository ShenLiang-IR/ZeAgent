import json
import time
from loguru import logger
from typing import Optional
from utils.observability.metrics import CHAT_TOTAL, CHAT_DURATION
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from api.schemas import ChatRequest
from utils.config import get_config_db
from utils.common.constants import DEFAULT_SESSION_ID
from services import AgentService
from services.quota_guard import enforce_chat_quota, get_degrade_llm
from utils.llm.llm_factory import get_default_llm
from utils.db import get_chat_db
from .message_utils import convert_to_langchain_messages, extract_user_input_from_messages
from .sse_utils import send_sse_data
from .stream.execution_event_sender import ExecutionEventSender
from .command_handler import process_command
from utils.common.auth_dependencies import get_user_id_from_auth_header, get_effective_authorization, get_workspace_id_from_auth_header
from utils.common.memory_context import set_memory_context
from tools.external_tool import set_current_authorization
def _resolve_agent(agent_id: Optional[str]) -> tuple:
    if not agent_id:
        return None, None
    config_db = get_config_db()
    agent_config = config_db.get_effective_agent(agent_id)
    if not agent_config:
        logger.warning(f"[AgentResolver]  agent_id={agent_id}  Agent ")
        raise HTTPException(status_code=400, detail=f" Agent: {agent_id}")
    agent_name = agent_config.get('agent_name')
    if not agent_name:
        logger.warning(f"[AgentResolver] agent_id={agent_id}  Agent  agent_name")
        raise HTTPException(status_code=400, detail=f"Agent : {agent_id}")
    logger.debug(f"[AgentResolver] agent_id={agent_id} -> agent_name={agent_name}")
    return agent_name, agent_config
def _resolve_response_mode(pr_key_id: Optional[str]) -> Optional[str]:
    if not pr_key_id:
        return None
    if pr_key_id == '__preview__':
        return pr_key_id
    config_db = get_config_db()
    mode_config = config_db.modes.get_by_id(pr_key_id)
    if not mode_config:
        logger.warning(f"[ModeResolver] 响应模式不存在: response_mode={pr_key_id}")
        raise HTTPException(status_code=400, detail=f"响应模式不存在: {pr_key_id}")
    mode_name = mode_config.get('en_name') or mode_config.get('dclr_ptn_name')
    if not mode_name:
        logger.warning(f"[ModeResolver] 响应模式名称缺失: response_mode={pr_key_id}")
        raise HTTPException(status_code=400, detail=f"响应模式不存在: {pr_key_id}")
    logger.debug(f"[ModeResolver] response_mode={pr_key_id} -> mode_name={mode_name}")
    return mode_name
router = APIRouter()
def _resolve_session_id(user_id: str, frontend_session_id: Optional[str]) -> str:
    chat_db = get_chat_db()
    if not frontend_session_id or frontend_session_id == DEFAULT_SESSION_ID:
        new_session = chat_db.create_session(user_id=user_id, workspace_id=_ws_id)
        if new_session:
            session_id = new_session.get('pr_key_id')
            logger.debug(f"[SessionResolver] : session_id={session_id}")
            return session_id
    existing_session = chat_db.get_session(user_id=user_id, pr_key_id=frontend_session_id)
    if existing_session:
        session_id = existing_session.get('pr_key_id')
        logger.debug(f"[SessionResolver] : session_id={session_id}")
        return session_id
    else:
        new_session = chat_db.create_session(user_id=user_id, workspace_id=_ws_id)
        if new_session:
            session_id = new_session.get('pr_key_id')
            logger.info(f"[SessionResolver]  session_id : old={frontend_session_id}, new={session_id}")
            return session_id
    logger.warning(f"[SessionResolver]  session_id: {frontend_session_id}")
    return frontend_session_id
@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    authorization: Optional[str] = Header(None)
):
    request_start = time.time()
    logger.info(f"[Chat Stream] ⏱️ =====  =====")
    # 配额预检（try 块外，超限抛 QuotaExceededError 直接冒泡 → server handler 返回 429；degrade 返回 degraded 信号）
    effective_auth = get_effective_authorization(authorization)
    quota_result = enforce_chat_quota(effective_auth, request.messages)
    success = False
    try:
        set_current_authorization(effective_auth)
        user_id = get_user_id_from_auth_header(effective_auth)
        _ws_id = get_workspace_id_from_auth_header(effective_auth)
        workspace_id = str(_ws_id) if _ws_id else None
        logger.info(f"[Chat Stream] user_id - authorization={'' if authorization else ''}, user_id={user_id}")
        frontend_session_id = request.session_id
        session_id = _resolve_session_id(user_id, frontend_session_id)
        set_memory_context(user_id=user_id, session_id=session_id)
        agent_id = request.agent_id
        agent, agent_config = _resolve_agent(agent_id)
        response_mode = _resolve_response_mode(request.response_mode)
        deep_thinking = request.deep_thinking
        logger.info(f"[Chat Stream]  - agent_id: {agent_id}, agent: {agent}, response_mode={request.response_mode}->mode={response_mode}, deep_thinking: {deep_thinking}, frontend_session_id={frontend_session_id}, resolved_session_id={session_id}")
        convert_start = time.time()
        # 诊断：记录 kb_refs 是否到达后端（帮助排查"AI 找不到片段"问题）
        _kb_ref_count = sum(len(getattr(m, 'kb_refs', None) or []) for m in request.messages)
        logger.info(f"[Chat Stream] kb_refs 到达后端: {_kb_ref_count} 条引用")
        langchain_messages = convert_to_langchain_messages(request.messages)
        convert_duration = time.time() - convert_start
        logger.info(f"[Chat Stream] ⏱️ : {convert_duration:.2f}")
        user_input = extract_user_input_from_messages(langchain_messages)
        # 内容安全审查
        if user_input:
            from core.security.content_filter import filter_content
            fr = filter_content(user_input)
            if fr.blocked:
                from core.security.content_filter import log_filter_event
                import asyncio as _aio
                _aio.create_task(_aio.to_thread(log_filter_event,
                    user_input, fr.matched, "input", str(user_id), "", _ws_id))
                async def filtered_stream():
                    yield send_sse_data({'content': f'[内容安全] {fr.reason}', 'done': True, 'filtered': True})
                return StreamingResponse(filtered_stream(), media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
        command_result = await process_command(user_input, session_id, user_id)
        if command_result.is_command:
            async def command_response():
                yield send_sse_data({
                    'content': command_result.message,
                    'done': True,
                    'command': command_result.command,
                    'success': command_result.success
                })
            return StreamingResponse(
                command_response(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        event_sender = ExecutionEventSender()
        is_preview_mode = response_mode == '__preview__'
        agent_service = AgentService(
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            llm_model=get_degrade_llm(quota_result.degrade_model_id) or get_default_llm(),
            skip_memory=is_preview_mode
        )
        async def generate():
            db_save_start = None
            try:
                yield send_sse_data({
                    'session_id': session_id,
                    'type': 'session_info'
                })
                collected_ai_content = []
                collected_ai_reasoning = []
                collected_workflow_tasks = []
                collected_workflow_mode = None
                collected_workflow_summary = None
                agent_execute_start = time.time()
                async for data in agent_service.chat_stream(
                    messages=langchain_messages,
                    agent=agent,
                    agent_config=agent_config,
                    response_mode=response_mode,
                    deep_thinking=deep_thinking,
                    event_sender=event_sender,
                    user_id=user_id,
                    request_messages=request.messages
                ):
                    # 防御：非 SSE 字符串（如 raw dict）包成 SSE 格式，防 plan_review 等事件前端收不到
                    if not isinstance(data, str):
                        data = send_sse_data(data)
                    yield data
                    if isinstance(data, str) and data.startswith('data: '):
                        try:
                            json_str = data[6:]
                            sse_data = json.loads(json_str)
                            if isinstance(sse_data, dict):
                                content = sse_data.get('content', '')
                                reasoning_content = sse_data.get('reasoning_content', '')
                                if content:
                                    collected_ai_content.append(content)
                                if reasoning_content:
                                    collected_ai_reasoning.append(reasoning_content)
                                event_type = sse_data.get('event')
                                event_data = sse_data.get('data')
                                if 'execution_event' in sse_data:
                                    exec_event = sse_data['execution_event']
                                    event_type = exec_event.get('event_type')
                                    event_data = exec_event.get('data')
                                if (event_type == 'plan' or event_type == 'workflow_planning') and event_data:
                                    workflow = event_data.get('workflow', {})
                                    if workflow and 'tasks' in workflow:
                                        collected_workflow_tasks = [
                                            {**t, 'status': t.get('status', 'pending')} for t in workflow['tasks']
                                        ]
                                        collected_workflow_mode = event_data.get('execution_mode') or workflow.get('mode')
                                elif event_type and event_type.startswith('task_') and event_data:
                                    task_id = event_data.get('task_id')
                                    if task_id:
                                        for task in collected_workflow_tasks:
                                            if task['id'] == task_id:
                                                task['status'] = event_data.get('status')
                                                task['result'] = event_data.get('output')
                                                task['error'] = event_data.get('error')
                                                if event_data.get('duration'):
                                                    task['duration'] = event_data.get('duration')
                                                break
                                elif (event_type == 'workflow_summary' or event_type == 'execution_complete') and event_data:
                                    collected_workflow_summary = event_data
                        except (json.JSONDecodeError, ValueError):
                            pass
                agent_execute_duration = time.time() - agent_execute_start
                logger.info(f"[Chat Stream] ⏱️ Agent: {agent_execute_duration:.2f}")
                final_ai_content = ''.join(collected_ai_content)
                final_ai_reasoning = ''.join(collected_ai_reasoning)
                has_content = final_ai_content.strip() or final_ai_reasoning.strip()
                has_workflow = collected_workflow_tasks and len(collected_workflow_tasks) > 0
                if has_content or has_workflow:
                    try:
                        from utils.db import get_chat_db
                        db_save_start = time.time()
                        chat_db = get_chat_db()
                        message_content = {
                            'text': final_ai_content,
                            'reasoning_content': final_ai_reasoning
                        }
                        if has_workflow:
                            message_content['workflow_tasks'] = collected_workflow_tasks
                            message_content['workflow_mode'] = collected_workflow_mode
                            if collected_workflow_summary:
                                message_content['workflow_summary'] = collected_workflow_summary
                        if not has_workflow and not final_ai_reasoning.strip():
                            message_content = final_ai_content
                        existing_messages = chat_db.get_messages(user_id, session_id)
                        if existing_messages is None:
                            logger.warning(f"[Chat Stream] : session_id={session_id}")
                        else:
                            message_order = len(existing_messages)
                            logger.debug(f"[Chat Stream] AI - user_id={user_id}, session_id={session_id}")
                            success = chat_db.save_message(
                                user_id=user_id,
                                session_id=session_id,
                                role='2',
                                content=message_content,
                                message_order=message_order
                            )
                            if success:
                                logger.debug(f"[Chat Stream]  AI : session_id={session_id}, content_length={len(final_ai_content)}, reasoning_length={len(final_ai_reasoning)}")
                                try:
                                    session = chat_db.get_session(user_id, session_id)
                                    if session and (not session.get('title') or session.get('title') == ''):
                                        user_input = extract_user_input_from_messages(langchain_messages)
                                        if user_input:
                                            auto_title = user_input[:50].strip()
                                            if not auto_title:
                                                auto_title = ''
                                            updated_session = chat_db.update_session(
                                                user_id=user_id,
                                                pr_key_id=session_id,
                                                title=auto_title
                                            )
                                            if updated_session:
                                                logger.debug(f"[Chat Stream] : session_id={session_id}, title={auto_title}")
                                except Exception as title_error:
                                    logger.warning(f"[Chat Stream] : {title_error}")
                            else:
                                logger.error(f"[Chat Stream]  AI : session_id={session_id}")
                    except Exception as e:
                        logger.error(f"[Chat Stream]  AI : {e}", exc_info=True)
                else:
                    logger.debug(f"[Chat Stream]  AI : session_id={session_id}")
                db_save_duration = time.time() - db_save_start if db_save_start else 0
                if db_save_start:
                    logger.info(f"[Chat Stream] ⏱️ : {db_save_duration:.2f}")
            except Exception as e:
                error_msg = str(e)
                logger.error("[Chat Stream] 流式失败: %s", error_msg, exc_info=True)
                # P2-5: 统一错误 schema，带 done=True，避免前端因缺 done 终止态判断挂起
                yield send_sse_data({'error': error_msg, 'done': True})
        success = True
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        logger.error(f"[Chat Stream] Endpoint : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        total_duration = time.time() - request_start
        CHAT_DURATION.observe(total_duration)
        CHAT_TOTAL.labels(status="success" if success else "failed").inc()
        logger.info(f"[Chat Stream] ⏱️ ===== : {total_duration:.2f} =====")
@router.get("/modes")
async def get_modes():
    try:
        config_db = get_config_db()
        modes = config_db.modes.get_all(enabled_only=True)
        result = []
        for mode in modes:
            mode_name = mode.get('mode_name') or mode.get('en_name', '')
            result.append({
                "key": mode_name,
                "name": mode_name,
                "description": mode.get('mode_description', ''),
                "response_style": mode.get('recommended_agents') or 'default'
            })
        return {"modes": result}
    except Exception as e:
        logger.error(f"[Modes] : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
def _convert_agent_to_frontend_format(agent_dict: dict) -> dict:
    agent_name = agent_dict.get('agent_name', '')
    pr_key_id = agent_dict.get('pr_key_id', '')
    return {
        'agent_id': pr_key_id,
        'name': agent_name,
        'display_name': agent_name,
        'description': agent_dict.get('agent_description', ''),
        'system_prompt': agent_dict.get('system_prompt', ''),
        'model': agent_dict.get('model_id'),
        'enabled': agent_dict.get('status') == '1',
        'tools': agent_dict.get('tools', []),
        'external_tools': agent_dict.get('external_tools', []),
        'mcp_tools': agent_dict.get('mcp_tools', []),
    }
@router.get("/subagents")
async def get_enabled_subagents():
    try:
        config_db = get_config_db()
        subagents = config_db.subagents.get_all(enabled_only=True)
        frontend_subagents = [_convert_agent_to_frontend_format(agent) for agent in subagents]
        logger.debug(f"[SubAgents] SubAgent: ={len(frontend_subagents)}")
        return {
            "subagents": frontend_subagents,
            "count": len(frontend_subagents)
        }
    except Exception as e:
        logger.error(f"[SubAgents] SubAgent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/chat")
async def chat(
    request: ChatRequest,
    authorization: Optional[str] = Header(None)
):
    effective_auth = get_effective_authorization(authorization)
    # 配额预检（try 块外，超限抛 QuotaExceededError 直接冒泡 → server handler 返回 429；degrade 返回 degraded 信号）
    quota_result = enforce_chat_quota(effective_auth, request.messages)
    try:
        set_current_authorization(effective_auth)
        user_id = get_user_id_from_auth_header(effective_auth)
        _ws_id = get_workspace_id_from_auth_header(effective_auth)
        workspace_id = str(_ws_id) if _ws_id else None
        frontend_session_id = request.session_id
        session_id = _resolve_session_id(user_id, frontend_session_id)
        set_memory_context(user_id=user_id, session_id=session_id)
        agent_id = request.agent_id
        agent, agent_config = _resolve_agent(agent_id)
        response_mode = _resolve_response_mode(request.response_mode)
        deep_thinking = request.deep_thinking
        logger.info(f"[Chat]  - agent_id: {agent_id}, agent: {agent}, response_mode={request.response_mode}->mode={response_mode}, deep_thinking: {deep_thinking}, frontend_session_id={frontend_session_id}, resolved_session_id={session_id}")
        langchain_messages = convert_to_langchain_messages(request.messages)
        user_input = extract_user_input_from_messages(langchain_messages)
        # 内容安全审查（非流式）
        if user_input:
            from core.security.content_filter import filter_content
            fr = filter_content(user_input)
            if fr.blocked:
                from core.security.content_filter import log_filter_event
                log_filter_event(user_input, fr.matched, "input", str(user_id), "", _ws_id)
                return {"content": f"[内容安全] {fr.reason}", "filtered": True}
        command_result = await process_command(user_input, session_id, user_id)
        if command_result.is_command:
            return {
                "content": command_result.message,
                "command": command_result.command,
                "success": command_result.success
            }
        is_preview_mode = response_mode == '__preview__'
        agent_service = AgentService(
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            llm_model=get_degrade_llm(quota_result.degrade_model_id) or get_default_llm(),
            skip_memory=is_preview_mode
        )
        result_messages = await agent_service.chat(
            messages=langchain_messages,
            agent=agent,
            agent_config=agent_config,
            response_mode=response_mode,
            deep_thinking=deep_thinking,
            user_id=user_id,
            request_messages=request.messages
        )
        from langchain_core.messages import AIMessage
        from utils.db import get_chat_db
        if result_messages and not is_preview_mode:
            chat_db = get_chat_db()
            try:
                last_ai_msg = None
                for msg in reversed(result_messages):
                    if isinstance(msg, AIMessage):
                        last_ai_msg = msg
                        break
                if last_ai_msg:
                    existing_messages = chat_db.get_messages(user_id, session_id)
                    if existing_messages is None:
                        logger.warning(f"[Chat] : session_id={session_id}")
                    else:
                        ai_content = last_ai_msg.content if hasattr(last_ai_msg, 'content') else str(last_ai_msg)
                        metadata = getattr(last_ai_msg, 'response_metadata', {}) or {}
                        message_payload = {
                            'text': ai_content
                        }
                        if metadata.get('workflow_tasks'):
                            message_payload['workflow_tasks'] = metadata.get('workflow_tasks')
                        if metadata.get('workflow_mode'):
                            message_payload['workflow_mode'] = metadata.get('workflow_mode')
                        if metadata.get('workflow_summary'):
                            message_payload['workflow_summary'] = metadata.get('workflow_summary')
                        if len(message_payload) == 1 and 'text' in message_payload:
                            final_save_content = ai_content
                        else:
                            final_save_content = message_payload
                        message_order = len(existing_messages)
                        success = chat_db.save_message(
                            user_id=user_id,
                            session_id=session_id,
                            role='2',
                            content=final_save_content,
                            message_order=message_order
                        )
                        if success:
                            logger.debug(f"[Chat]  AI : session_id={session_id}, content_length={len(ai_content)}")
                            try:
                                session = chat_db.get_session(user_id, session_id)
                                if session and (not session.get('title') or session.get('title') == ''):
                                    user_input = extract_user_input_from_messages(langchain_messages)
                                    if user_input:
                                        auto_title = user_input[:50].strip()
                                        if not auto_title:
                                            auto_title = ''
                                        updated_session = chat_db.update_session(
                                            user_id=user_id,
                                            pr_key_id=session_id,
                                            title=auto_title
                                        )
                                        if updated_session:
                                            logger.debug(f"[Chat] : session_id={session_id}, title={auto_title}")
                            except Exception as title_error:
                                logger.warning(f"[Chat] : {title_error}")
                        else:
                            logger.error(f"[Chat]  AI : session_id={session_id}")
            except Exception as e:
                logger.error(f"[Chat]  AI : {e}", exc_info=True)
        if not result_messages:
            return {"error": "", "session_id": session_id}
        last_message = result_messages[-1]
        content = last_message.content if hasattr(last_message, 'content') else str(last_message)
        metadata = getattr(last_message, 'response_metadata', {}) or {}
        if metadata.get('error'):
            return {
                "error": str(metadata.get('error')),
                "content": content,
                "session_id": session_id
            }
        summary = metadata.get('summary', {})
        return {
            "content": content,
            "reasoning_content": {},
            "workflow_summary": summary,
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Chat] Endpoint : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))