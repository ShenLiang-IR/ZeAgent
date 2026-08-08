"""端到端评测 API：dataset CRUD + LLM-as-Judge + 用户反馈 + 结果查询。

设计参见 当前文档分析.md §3.7。

路径前缀 /api/admin/eval/*（注册在 admin_router 下）：
- POST   /eval/datasets      创建 golden set 数据集
- GET    /eval/datasets       列出数据集
- GET    /eval/datasets/{id}  查询单个数据集
- POST   /eval/judge          单条 LLM-as-Judge 评分（传 question+response+expected+criteria）
- POST   /eval/feedback       用户反馈（thumbs up/down + 文本，匿名可提交）
- GET    /eval/results        查询评测结果（按 dispatch_id 或 dataset_id）
"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .permissions import require_read, require_write

router = APIRouter(prefix="/eval", tags=["evaluation"])


class EvalDatasetCreate(BaseModel):
    name: str
    question: str
    expected_output: str = ""
    scoring_criteria: str = ""
    tags: str = ""
    workspace_id: int | None = None


class JudgeRequest(BaseModel):
    question: str
    response: str
    expected_output: str = ""
    scoring_criteria: str = ""
    dispatch_id: str | None = None
    dataset_id: str | None = None
    workspace_id: int | None = None


class FeedbackCreate(BaseModel):
    dispatch_id: str | None = None
    thumbs_up: bool
    comment: str = ""
    user_id: str | None = None
    workspace_id: int | None = None


@router.post("/datasets")
async def create_dataset(
    data: EvalDatasetCreate,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """创建评测数据集（golden set）。"""
    from infrastructure.database.repositories.eval_repository import EvalDatasetRepository
    from services.eval_service import EvalService
    from utils.id_generator import generate_uuid

    EvalService()._ensure_table()
    repo = EvalDatasetRepository()
    entity = repo.create(
        dataset_id=f"EVAL_DS_{generate_uuid()[:16]}",
        name=data.name,
        question=data.question,
        expected_output=data.expected_output,
        scoring_criteria=data.scoring_criteria,
        tags=data.tags,
        workspace_id=data.workspace_id,
        enabled="1",
    )
    if not entity:
        raise HTTPException(status_code=500, detail="创建 dataset 失败")
    return wrap_response(repo._entity_to_dict(entity, None))


@router.get("/datasets")
async def list_datasets(
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """列出启用的评测数据集。"""
    from infrastructure.database.repositories.eval_repository import EvalDatasetRepository
    from services.eval_service import EvalService

    EvalService()._ensure_table()  # 确保表存在（幂等）
    repo = EvalDatasetRepository()
    datasets = repo.list_enabled()
    return wrap_response({"datasets": datasets, "total": len(datasets)})


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """查询单个数据集。"""
    from infrastructure.database.repositories.eval_repository import EvalDatasetRepository
    from services.eval_service import EvalService

    EvalService()._ensure_table()  # 确保表存在（幂等）
    repo = EvalDatasetRepository()
    dataset = repo.get_by_dataset_id(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} 不存在")
    return wrap_response(dataset)


@router.post("/judge")
async def judge(
    req: JudgeRequest,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """LLM-as-Judge 评分单条 Agent 回复。

    传 question + response + expected_output + scoring_criteria，
    返回 {score, feedback, judge_model}。若传 dispatch_id/dataset_id 则同时存 result。
    """
    from services.eval_service import EvalService

    svc = EvalService()
    result = await svc.judge_response(
        question=req.question,
        response=req.response,
        expected_output=req.expected_output,
        scoring_criteria=req.scoring_criteria,
    )
    # 若关联 dispatch/dataset，存评测结果
    if req.dispatch_id or req.dataset_id:
        try:
            saved = await svc.save_result(
                dispatch_id=req.dispatch_id,
                dataset_id=req.dataset_id,
                question=req.question,
                response=req.response,
                expected_output=req.expected_output,
                score=result["score"],
                judge_feedback=result["feedback"],
                judge_model=result["judge_model"],
                workspace_id=req.workspace_id,
            )
            if saved:
                result["result_id"] = saved.get("result_id")
        except Exception as e:
            logger.warning(f"[eval/judge] save_result failed (non-fatal): {e}")
    return wrap_response(result)


class RunDatasetRequest(BaseModel):
    dataset_id: str
    responses: list[dict] = []  # [{question, response, expected_output?}]


@router.post("/run-dataset")
async def run_dataset(
    req: RunDatasetRequest,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """离线评测：对 dataset 批量 judge（调用方提供 responses 列表）。

    每个 response 用 dataset 的 scoring_criteria + expected_output 评分，存 result。
    """
    from infrastructure.database.repositories.eval_repository import EvalDatasetRepository
    from services.eval_service import EvalService

    dataset = EvalDatasetRepository().get_by_dataset_id(req.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset {req.dataset_id} 不存在")
    svc = EvalService()
    results = []
    for item in req.responses:
        question = item.get("question", dataset.get("question", ""))
        response = item.get("response", "")
        expected = item.get("expected_output", dataset.get("expected_output", ""))
        judged = await svc.judge_response(
            question=question, response=response,
            expected_output=expected, scoring_criteria=dataset.get("scoring_criteria", ""),
        )
        saved = await svc.save_result(
            dispatch_id=None, dataset_id=req.dataset_id,
            question=question, response=response, expected_output=expected,
            score=judged["score"], judge_feedback=judged["feedback"],
            judge_model=judged["judge_model"],
        )
        results.append({
            "question": question, "response": response,
            "score": judged["score"], "feedback": judged["feedback"],
            "judge_model": judged["judge_model"],
            "result_id": saved.get("result_id") if saved else None,
        })
    return wrap_response({"results": results, "total": len(results)})


@router.post("/feedback")
async def submit_feedback(req: FeedbackCreate):
    """提交用户反馈（thumbs up/down + 文本）。匿名可提交（不强制鉴权）。"""
    from infrastructure.database.repositories.eval_repository import FeedbackRepository
    from services.eval_service import EvalService
    from utils.id_generator import generate_uuid

    EvalService()._ensure_table()
    repo = FeedbackRepository()
    entity = repo.create(
        feedback_id=f"FB_{generate_uuid()[:16]}",
        dispatch_id=req.dispatch_id,
        thumbs_up=req.thumbs_up,
        comment=req.comment,
        user_id=req.user_id or "anonymous",
        workspace_id=req.workspace_id,
    )
    if not entity:
        raise HTTPException(status_code=500, detail="提交反馈失败")
    return wrap_response(repo._entity_to_dict(entity, None))


@router.get("/results")
async def list_results(
    dispatch_id: str | None = None,
    dataset_id: str | None = None,
    limit: int = 50,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """查询评测结果（按 dispatch_id 或 dataset_id）。"""
    from infrastructure.database.repositories.eval_repository import EvalResultRepository
    from services.eval_service import EvalService

    EvalService()._ensure_table()  # 确保表存在（幂等）
    repo = EvalResultRepository()
    if dispatch_id:
        results = repo.list_by_dispatch(dispatch_id)
    elif dataset_id:
        results = repo.list_by_dataset(dataset_id, limit=limit)
    else:
        results = []
    return wrap_response({"results": results, "total": len(results)})
