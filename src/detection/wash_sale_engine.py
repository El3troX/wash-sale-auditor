"""
Wash Sale Detection Engine.
Conforms to Section 5 of the Technical Design Document.
Executes 61-day sliding-window temporal graph matching across multi-broker account streams.

MODELING CHOICE NOTE (IRC §1091 / TDD Section 5.2):
When multiple loss sales compete for a limited pool of replacement shares, this engine processes
loss sales in strict chronological order, greedily consuming available replacement quantities.
An earlier-dated loss sale claims replacement shares first, leaving residual shares for later sales.
"""

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Dict, List, Optional, Set, Tuple, Union

from src.equivalence.engine import EquivalenceEngine, DEFAULT_EQUIVALENCE_ENGINE
from src.models.entities import Account, Transaction, WashSaleEvent
from src.models.enums import TransactionType

logger = logging.getLogger(__name__)


@dataclass
class _LotRecord:
    tx: Transaction
    remaining: float


class WashSaleDetectionEngine:
    """
    Deterministic rules engine detecting cross-account wash sales under IRC §1091 and Rev. Rul. 2008-5.
    """

    def __init__(
        self,
        equivalence_engine: Optional[EquivalenceEngine] = None,
        lookback_days: int = 30,
        lookforward_days: int = 30,
    ) -> None:
        self.equivalence_engine = equivalence_engine if equivalence_engine is not None else DEFAULT_EQUIVALENCE_ENGINE
        self.lookback_days = lookback_days
        self.lookforward_days = lookforward_days

    @staticmethod
    def _normalize_accounts_map(accounts: Union[Dict[str, Account], List[Account]]) -> Dict[str, Account]:
        """Maps account_id and any dict aliases to Account instances."""
        acct_map: Dict[str, Account] = {}
        if isinstance(accounts, dict):
            for k, v in accounts.items():
                if isinstance(v, Account):
                    acct_map[v.account_id] = v
                    acct_map[k] = v
        elif isinstance(accounts, list):
            for acc in accounts:
                acct_map[acc.account_id] = acc
        return acct_map

    @classmethod
    def _map_disposed_lots(cls, sorted_txs: List[Transaction]) -> Dict[str, Set[str]]:
        """
        Determines the source BUY lots that established the position being closed by each SELL (FIFO).
        The acquisition of the shares being sold cannot be treated as a replacement purchase for its own disposition.
        Returns: sell_transaction_id -> set of source buy_transaction_ids
        """
        inventory: Dict[Tuple[str, str], List[_LotRecord]] = {}
        disposed_lots: Dict[str, Set[str]] = {}

        for tx in sorted_txs:
            key = (tx.account_id, tx.ticker.upper())
            if tx.transaction_type == TransactionType.BUY:
                if key not in inventory:
                    inventory[key] = []
                inventory[key].append(_LotRecord(tx=tx, remaining=tx.quantity))
            elif tx.transaction_type == TransactionType.SELL:
                disposed_lots[tx.transaction_id] = set()
                needed = tx.quantity
                lots = inventory.get(key, [])
                for lot in lots:
                    if needed <= 0:
                        break
                    if lot.remaining <= 0:
                        continue
                    take = min(needed, lot.remaining)
                    lot.remaining -= take
                    needed -= take
                    disposed_lots[tx.transaction_id].add(lot.tx.transaction_id)

        return disposed_lots

    def detect_wash_sales(
        self,
        transactions: List[Transaction],
        accounts: Union[Dict[str, Account], List[Account]],
    ) -> List[WashSaleEvent]:
        """
        Executes 61-day temporal sliding window matching algorithm on a transaction stream.
        """
        # Build robust account resolution dictionary
        acct_map = self._normalize_accounts_map(accounts)

        # Sort transactions chronologically
        sorted_txs = sorted(transactions, key=lambda tx: (tx.trade_date, tx.transaction_id))

        # Reset unmatched quantities to full quantity
        for tx in sorted_txs:
            tx.unmatched_quantity = tx.quantity

        # Map which buy lots were disposed of by each sell
        disposed_lots = self._map_disposed_lots(sorted_txs)

        loss_sales = [
            tx for tx in sorted_txs
            if tx.transaction_type == TransactionType.SELL
            and tx.realized_gain_loss is not None
            and tx.realized_gain_loss < 0
        ]

        wash_events: List[WashSaleEvent] = []

        for sell in loss_sales:
            if sell.unmatched_quantity <= 0 or sell.realized_gain_loss is None:
                continue

            window_start = sell.trade_date - timedelta(days=self.lookback_days)
            window_end = sell.trade_date + timedelta(days=self.lookforward_days)
            source_buy_ids = disposed_lots.get(sell.transaction_id, set())

            # Candidate replacement acquisitions within 61-day window
            candidate_buys = [
                tx for tx in sorted_txs
                if tx.transaction_type == TransactionType.BUY
                and window_start <= tx.trade_date <= window_end
                and tx.unmatched_quantity > 0
                and tx.transaction_id != sell.transaction_id  # Same-lot / duplicate-leg exclusion (TC-06)
                and tx.transaction_id not in source_buy_ids  # Cannot match the buy that established the sold lot
            ]

            for buy in candidate_buys:
                if sell.unmatched_quantity <= 0:
                    break
                if buy.unmatched_quantity <= 0:
                    continue

                eval_result = self.equivalence_engine.evaluate(
                    ticker1=sell.ticker,
                    ticker2=buy.ticker,
                    cusip1=sell.cusip,
                    cusip2=buy.cusip,
                )

                if not eval_result.is_equivalent:
                    continue

                match_qty = min(sell.unmatched_quantity, buy.unmatched_quantity)
                sell_account = acct_map.get(sell.account_id)
                buy_account = acct_map.get(buy.account_id)

                sell_broker = sell_account.broker_name if sell_account else "Unknown Broker"
                buy_broker = buy_account.broker_name if buy_account else "Unknown Broker"
                is_ira = buy_account.account_type.is_tax_advantaged if buy_account else False

                window_delta = abs((buy.trade_date - sell.trade_date).days)
                timing_str = (
                    f"{window_delta} days before sell"
                    if buy.trade_date < sell.trade_date
                    else (f"{window_delta} days after sell" if buy.trade_date > sell.trade_date else "same day")
                )

                # Route Tier 3 Review-Band candidates (0.80 <= score < 0.95) to manual review (NO auto-disallowance)
                if eval_result.requires_manual_review:
                    review_event = WashSaleEvent(
                        event_id=f"WS-REV-{sell.transaction_id}-{buy.transaction_id}",
                        loss_transaction_id=sell.transaction_id,
                        replacement_transaction_id=buy.transaction_id,
                        matched_quantity=match_qty,
                        disallowed_loss=0.0,  # CRITICAL: 0.0 disallowed loss for unconfirmed review candidates
                        similarity_score=eval_result.similarity_score,
                        window_days=window_delta,
                        is_ira_disallowance=is_ira,
                        rationale=(
                            f"[MANUAL CPA REVIEW REQUIRED] Potential wash sale flagged: Loss sale of {sell.quantity} {sell.ticker} "
                            f"in {sell_broker} ({sell.trade_date}) correlated with purchase of {buy.quantity} {buy.ticker} in "
                            f"{buy_broker} ({buy.trade_date}, {timing_str}). {eval_result.rationale}"
                        ),
                        requires_manual_review=True,
                        tier=eval_result.tier,
                    )
                    wash_events.append(review_event)
                    # Note: We do NOT deduct unmatched_quantity so lot is not consumed by unconfirmed match
                    continue

                # Confirmed Wash Sale Match (Tier 1, Tier 2, or Tier 3 >= 0.95)
                unit_loss = abs(sell.realized_gain_loss) / sell.quantity
                disallowed = match_qty * unit_loss

                ira_notice = (
                    " [PERMANENT DISALLOWANCE: Replacement purchased in IRA under Rev. Rul. 2008-5 - $0 basis relief]"
                    if is_ira
                    else ""
                )

                rationale_str = (
                    f"Wash sale under IRC §1091: Realized loss on {sell.ticker} ({sell.trade_date} in {sell_broker}) "
                    f"matched with replacement purchase of {buy.ticker} ({buy.trade_date} in {buy_broker}, {timing_str}). "
                    f"{eval_result.rationale}. Matched {match_qty:.2f} shares, disallowing ${disallowed:.2f} loss.{ira_notice}"
                )

                event = WashSaleEvent(
                    event_id=f"WS-{sell.transaction_id}-{buy.transaction_id}",
                    loss_transaction_id=sell.transaction_id,
                    replacement_transaction_id=buy.transaction_id,
                    matched_quantity=match_qty,
                    disallowed_loss=disallowed,
                    similarity_score=eval_result.similarity_score,
                    window_days=window_delta,
                    is_ira_disallowance=is_ira,
                    rationale=rationale_str,
                    requires_manual_review=False,
                    tier=eval_result.tier,
                )
                wash_events.append(event)

                sell.unmatched_quantity -= match_qty
                buy.unmatched_quantity -= match_qty

        return wash_events
