"""评测 repository：EvalDatasetRepository + EvalResultRepository + FeedbackRepository。

参照 audit_repository.py 风格：BaseRepository[Model, Dict] + 业务查询方法。
"""
from typing import Any

from loguru import logger
from sqlalchemy import select

from infrastructure.database.models.eval import EvalDataset, EvalResult, Feedback
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class EvalDatasetRepository(BaseRepository[EvalDataset, dict[str, Any]]):
    """评测数据集 repository。"""
    _session_factory = get_config_session
    _model_class = EvalDataset
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: EvalDataset, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'dataset_id': entity.dataset_id,
            'name': entity.name,
            'question': entity.question,
            'expected_output': entity.expected_output,
            'scoring_criteria': entity.scoring_criteria,
            'tags': entity.tags,
            'workspace_id': entity.workspace_id,
            'enabled': entity.enabled,
            'create_time': str(entity.create_time) if entity.create_time else None,
            'update_time': str(entity.update_time) if entity.update_time else None,
        }

    def get_by_dataset_id(self, dataset_id: str) -> dict[str, Any] | None:
        """按业务 ID 查询。"""
        try:
            with self._get_session() as session:
                stmt = select(EvalDataset).where(EvalDataset.dataset_id == dataset_id)
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"EvalDatasetRepository.get_by_dataset_id ({dataset_id}): {e}", exc_info=True)
            return None

    def list_enabled(self, workspace_id: int | None = None) -> list[dict[str, Any]]:
        """列出启用的数据集（可选 workspace 过滤）。"""
        try:
            with self._get_session() as session:
                stmt = select(EvalDataset).where(EvalDataset.enabled == "1")
                if workspace_id is not None:
                    stmt = stmt.where(EvalDataset.workspace_id == workspace_id)
                stmt = stmt.order_by(EvalDataset.pr_key_id.desc())
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"EvalDatasetRepository.list_enabled: {e}", exc_info=True)
            return []


class EvalResultRepository(BaseRepository[EvalResult, dict[str, Any]]):
    """评测结果 repository。"""
    _session_factory = get_config_session
    _model_class = EvalResult
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: EvalResult, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'result_id': entity.result_id,
            'dispatch_id': entity.dispatch_id,
            'dataset_id': entity.dataset_id,
            'question': entity.question,
            'response': entity.response,
            'expected_output': entity.expected_output,
            'score': entity.score,
            'judge_feedback': entity.judge_feedback,
            'judge_model': entity.judge_model,
            'workspace_id': entity.workspace_id,
            'create_time': str(entity.create_time) if entity.create_time else None,
        }

    def list_by_dispatch(self, dispatch_id: str) -> list[dict[str, Any]]:
        """按 dispatch_id 查询评测结果。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(EvalResult)
                    .where(EvalResult.dispatch_id == dispatch_id)
                    .order_by(EvalResult.pr_key_id.desc())
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"EvalResultRepository.list_by_dispatch ({dispatch_id}): {e}", exc_info=True)
            return []

    def list_by_dataset(self, dataset_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """按 dataset_id 查询评测结果。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(EvalResult)
                    .where(EvalResult.dataset_id == dataset_id)
                    .order_by(EvalResult.pr_key_id.desc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"EvalResultRepository.list_by_dataset ({dataset_id}): {e}", exc_info=True)
            return []


class FeedbackRepository(BaseRepository[Feedback, dict[str, Any]]):
    """用户反馈 repository。"""
    _session_factory = get_config_session
    _model_class = Feedback
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: Feedback, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'feedback_id': entity.feedback_id,
            'dispatch_id': entity.dispatch_id,
            'thumbs_up': entity.thumbs_up,
            'comment': entity.comment,
            'user_id': entity.user_id,
            'workspace_id': entity.workspace_id,
            'create_time': str(entity.create_time) if entity.create_time else None,
        }

    def list_by_dispatch(self, dispatch_id: str) -> list[dict[str, Any]]:
        """按 dispatch_id 查询反馈。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(Feedback)
                    .where(Feedback.dispatch_id == dispatch_id)
                    .order_by(Feedback.pr_key_id.desc())
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"FeedbackRepository.list_by_dispatch ({dispatch_id}): {e}", exc_info=True)
            return []
