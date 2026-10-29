from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.repositories.monitoring_rules import MonitoringRuleConfigRepository

RULE_CODE = "MON-011"
DEFAULT_THRESHOLD = Decimal("10000.00")
DEFAULT_CURRENCY = "USD"


@dataclass
class MonitoringResult:
    triggered: bool
    rule_version: int
    details: dict


async def evaluate_mon_011(session: AsyncSession, transaction: Transaction) -> MonitoringResult:
    """MON-011: deterministic single-transaction amount threshold rule.

    No ML, no LLM -- per plan.md §0 ("deterministic before AI"). Threshold
    is per-organization configurable via monitoring_rule_configs, falling
    back to a global default when no org-specific config is active.
    Currency mismatch between the transaction and the active config does
    not trigger the rule (no FX normalization yet -- out of scope).
    """
    config = await MonitoringRuleConfigRepository(session).get_active_config(
        transaction.organization_id, RULE_CODE
    )

    threshold = config.threshold_amount if config else DEFAULT_THRESHOLD
    currency = config.currency if config else DEFAULT_CURRENCY
    version = config.version if config else 0

    triggered = transaction.currency == currency and transaction.amount > threshold
    return MonitoringResult(
        triggered=triggered,
        rule_version=version,
        details={
            "threshold_amount": str(threshold),
            "currency": currency,
            "transaction_amount": str(transaction.amount),
        },
    )
