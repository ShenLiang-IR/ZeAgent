"""QuotaService：配额检查 + 扣减。

设计参见 docs/specs/2026-07-19-usage-tracking-design.md §4。

第一期 MVP：
- warn 模式：超限不阻塞，仅记日志
- block 模式：超限阻塞（allowed=False）
- degrade 模式：第二期实施（切备用模型）
"""
from datetime import datetime

from loguru import logger


class QuotaService:
    """配额检查与扣减服务。"""

    def check_and_deduct(
        self,
        workspace_id: int,
        quota_type: str,
        estimated: int,
    ) -> tuple[bool, str]:
        """检查配额并累加 used_value。

        Args:
            workspace_id: workspace ID
            quota_type: monthly_token / daily_token / monthly_cost
            estimated: 预估用量（token 数或成本）

        Returns:
            (allowed, reason)：是否允许 + 原因说明
        """
        try:
            from infrastructure.database.repositories.usage_repository import QuotaRepository
            repo = QuotaRepository()
            quotas = repo.list_by_workspace(workspace_id)
            # 找当前 quota_type 的配额
            period = self._current_period(quota_type)
            matched = [q for q in quotas
                       if q.get("quota_type") == quota_type
                       and q.get("period") == period]
            if not matched:
                # 无配额配置：允许（不阻塞）
                return True, "no quota configured"

            quota = matched[0]
            used = quota.get("used_value", 0) or 0
            limit = quota.get("limit_value", 0) or 0
            action = quota.get("over_limit_action", "warn")

            degraded = False
            if used + estimated > limit:
                # 超限
                if action == "block":
                    logger.warning(
                        f"[Quota] BLOCK workspace={workspace_id} {quota_type}: "
                        f"used={used}+{estimated} > limit={limit}"
                    )
                    return False, f"quota exceeded (used={used}+{estimated} > limit={limit})"
                elif action == "degrade":
                    # degrade 模式：超限不阻塞，返回 degrade 信号让调用方切备用模型
                    logger.warning(
                        f"[Quota] DEGRADE workspace={workspace_id} {quota_type}: "
                        f"used={used}+{estimated} > limit={limit}"
                    )
                    degraded = True
                else:
                    # warn
                    logger.warning(
                        f"[Quota] WARN workspace={workspace_id} {quota_type}: "
                        f"used={used}+{estimated} > limit={limit}"
                    )

            # 累加 used_value（无论是否超限，warn/degrade 都累加；block 不累加）
            if action != "block" or used + estimated <= limit:
                repo.update_used(workspace_id, quota_type, period, estimated)

            return True, "degrade" if degraded else "ok"
        except Exception as e:
            logger.error(f"[Quota] check_and_deduct failed (allow): {e}", exc_info=True)
            # 出错时不阻塞主流程
            return True, f"quota check error: {e}"

    def _current_period(self, quota_type: str) -> str:
        """根据 quota_type 返回当前 period 字符串。"""
        now = datetime.now()
        if quota_type.startswith("daily"):
            return now.strftime("%Y-%m-%d")
        # monthly
        return now.strftime("%Y-%m")

    def get_quota_status(self, workspace_id: int) -> list:
        """返回 workspace 当前所有配额使用情况。"""
        try:
            from infrastructure.database.repositories.usage_repository import QuotaRepository
            return QuotaRepository().list_by_workspace(workspace_id)
        except Exception as e:
            logger.error(f"[Quota] get_quota_status failed: {e}")
            return []

    def create_default_quota(self, workspace_id: int, quota_type: str,
                             limit_value: int, over_limit_action: str = "warn"):
        """按当前 period 创建默认配额（幂等：已存在则跳过）。"""
        try:
            from infrastructure.database.repositories.usage_repository import QuotaRepository
            repo = QuotaRepository()
            period = self._current_period(quota_type)
            existing = repo.list_by_workspace(workspace_id)
            matched = [q for q in existing
                       if q.get("quota_type") == quota_type and q.get("period") == period]
            if matched:
                return
            repo.create(
                workspace_id=workspace_id,
                quota_type=quota_type,
                limit_value=limit_value,
                period=period,
                used_value=0,
                over_limit_action=over_limit_action,
                status="active",
            )
            logger.info(f"[Quota] auto-created default: workspace={workspace_id} {quota_type}={limit_value}")
        except Exception as e:
            logger.warning(f"[Quota] create_default failed: {e}")
