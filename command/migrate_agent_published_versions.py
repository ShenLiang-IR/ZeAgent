"""回填：为已发布(release_status=1)但无 published 版本记录的 agent 补一条 published 快照。

背景：黄金规则"线上读已发布版本快照"——对存量已发布 agent，若无 published 版本行，
运行态会回退读工作副本，导致编辑这些 agent 仍即时影响线上（管控失效）。
本脚本一次性回填：用当前配置生成 published 快照，使黄金规则对存量数据生效。

用法：python command/migrate_agent_published_versions.py
幂等：已有 published 版本的 agent 跳过。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_backfill(agent_repo, version_repo, snapshot_fn, log=print):
    """对每个 release_status=1 的 agent，若无 published 版本则回填一条。

    Args:
        agent_repo: 提供 get_all(release_status=...) 的仓储
        version_repo: 提供 get_published / create 的版本仓储
        snapshot_fn: (agent_id:int) -> dict|None，读取 agent 可变配置快照
        log: 日志函数
    Returns: (created, skipped)
    """
    from utils.id_generator import generate_uuid

    agents = agent_repo.get_all(release_status="1")
    created, skipped = 0, 0
    for a in agents:
        aid = a.get("pr_key_id")
        if aid is None:
            continue
        if version_repo.get_published(int(aid)):
            skipped += 1
            continue
        snap = snapshot_fn(int(aid))
        if not snap:
            log(f"skip agent {aid}: snapshot failed")
            continue
        vno = a.get("version_no") or "1.0.0"
        version_repo.create(
            version_id=f"AGV_{generate_uuid()[:16]}",
            agent_pr_key_id=int(aid),
            version_no=vno,
            version_description="回填：存量已发布版本",
            snapshot=json.dumps(snap, ensure_ascii=False, default=str),
            status="published",
        )
        created += 1
        log(f"backfilled agent {aid} ({a.get('agent_name')}) -> v{vno} published")
    return created, skipped


def main():
    from infrastructure.database.repositories.agent_repository import AgentRepository
    from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
    from services.agent_version_service import AgentVersionService

    svc = AgentVersionService()
    svc._ensure_table()
    created, skipped = run_backfill(
        AgentRepository(), AgentVersionRepository(), svc._snapshot_agent,
    )
    print(f"done: {created} backfilled, {skipped} already had published")


if __name__ == "__main__":
    main()
