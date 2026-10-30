import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MonitoringRuleConfig


class MonitoringRuleConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_config(
        self, organization_id: uuid.UUID, rule_code: str
    ) -> MonitoringRuleConfig | None:
        org_specific = await self._session.execute(
            select(MonitoringRuleConfig)
            .where(
                MonitoringRuleConfig.organization_id == organization_id,
                MonitoringRuleConfig.rule_code == rule_code,
                MonitoringRuleConfig.is_active.is_(True),
            )
            .order_by(MonitoringRuleConfig.version.desc())
            .limit(1)
        )
        row = org_specific.scalar_one_or_none()
        if row is not None:
            return row

        global_default = await self._session.execute(
            select(MonitoringRuleConfig)
            .where(
                MonitoringRuleConfig.organization_id.is_(None),
                MonitoringRuleConfig.rule_code == rule_code,
                MonitoringRuleConfig.is_active.is_(True),
            )
            .order_by(MonitoringRuleConfig.version.desc())
            .limit(1)
        )
        return global_default.scalar_one_or_none()
