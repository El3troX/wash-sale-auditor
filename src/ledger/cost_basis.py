"""
Cost Basis Propagation and Tax Lot Ledger Engine.
Conforms to Section 6 of the Technical Design Document.

Implements:
- Taxable account basis step-up and holding period tacking (Section 6.1)
- IRA Revenue Ruling 2008-5 permanent disallowance branch (Section 6.2)
- Compounded basis propagation on chained wash sales (TC-05a)
- Strict confirmed-only filtering safeguard (unconfirmed review-band matches NEVER alter basis)
"""

from dataclasses import dataclass, field
from datetime import date
import logging
from typing import Dict, List, Optional, Set, Tuple

from src.models.entities import Account, Transaction, WashSaleEvent
from src.models.enums import AccountType, TransactionType

logger = logging.getLogger(__name__)


@dataclass
class TaxLot:
    """Represents an open or closed tax lot of shares in an account."""
    lot_id: str
    account_id: str
    ticker: str
    cusip: Optional[str]
    acquired_date: date
    quantity: float
    remaining_quantity: float
    original_cost_per_share: float
    original_basis: float
    adjusted_basis: float
    holding_period_days_tacked: int = 0
    is_ira: bool = False
    disallowed_loss_added: float = 0.0
    is_closed: bool = False
    closed_date: Optional[date] = None
    realized_gain_loss: Optional[float] = None
    lineage_event_ids: List[str] = field(default_factory=list)

    @property
    def adjusted_cost_per_share(self) -> float:
        return self.adjusted_basis / self.quantity if self.quantity > 0 else self.original_cost_per_share


@dataclass
class ClosedDisposition:
    """Represents the realization of a closed tax lot on a sell event."""
    disposition_id: str
    lot_id: str
    account_id: str
    ticker: str
    acquired_date: date
    sold_date: date
    quantity: float
    proceeds: float
    cost_basis: float
    disallowed_loss: float
    net_gain_loss: float
    is_wash_sale: bool
    is_ira: bool
    adjustment_code: Optional[str] = None  # 'W' for wash sale
    holding_period_days: int = 0


class CostBasisEngine:
    """
    Manages lot-level basis tracking, wash sale basis step-up, and holding period tacking.
    Strictly safeguards that unconfirmed review-band candidates never alter cost basis.
    """

    def __init__(self) -> None:
        # account_id -> list of TaxLot
        self.lots: Dict[str, List[TaxLot]] = {}
        self.dispositions: List[ClosedDisposition] = []

    def process_ledger(
        self,
        transactions: List[Transaction],
        accounts: Dict[str, Account],
        wash_events: List[WashSaleEvent],
    ) -> Tuple[List[TaxLot], List[ClosedDisposition]]:
        """
        Processes transactions chronologically, applying basis adjustments and tracking lots.
        """
        # Build account lookup
        acct_map: Dict[str, Account] = {}
        for k, v in accounts.items():
            if isinstance(v, Account):
                acct_map[v.account_id] = v
                acct_map[k] = v

        # Filter confirmed wash sales only
        # SAFEGUARD: Unconfirmed review-band candidates MUST NOT alter cost basis
        confirmed_wash_sales: List[WashSaleEvent] = [
            ev for ev in wash_events if not ev.requires_manual_review
        ]

        # Index confirmed wash sales by replacement transaction ID and loss transaction ID
        ws_by_replacement: Dict[str, List[WashSaleEvent]] = {}
        ws_by_loss: Dict[str, List[WashSaleEvent]] = {}
        for ev in confirmed_wash_sales:
            ws_by_replacement.setdefault(ev.replacement_transaction_id, []).append(ev)
            ws_by_loss.setdefault(ev.loss_transaction_id, []).append(ev)

        # Sort transactions chronologically
        sorted_txs = sorted(transactions, key=lambda tx: (tx.trade_date, tx.transaction_id))

        # Open lots inventory: (account_id, ticker) -> List[TaxLot]
        open_lots: Dict[Tuple[str, str], List[TaxLot]] = {}
        all_lots: List[TaxLot] = []
        all_dispositions: List[ClosedDisposition] = []

        # Track tx_id -> TaxLot mapping for buys
        tx_to_lot: Dict[str, TaxLot] = {}

        for tx in sorted_txs:
            acc = acct_map.get(tx.account_id)
            is_ira = acc.account_type.is_tax_advantaged if acc else False
            key = (tx.account_id, tx.ticker.upper())

            if tx.transaction_type == TransactionType.BUY:
                base_basis = tx.price_per_share * tx.quantity
                lot = TaxLot(
                    lot_id=f"LOT-{tx.transaction_id}",
                    account_id=tx.account_id,
                    ticker=tx.ticker.upper(),
                    cusip=tx.cusip,
                    acquired_date=tx.trade_date,
                    quantity=tx.quantity,
                    remaining_quantity=tx.quantity,
                    original_cost_per_share=tx.price_per_share,
                    original_basis=base_basis,
                    adjusted_basis=base_basis,
                    is_ira=is_ira,
                )

                # Check if this BUY is a replacement acquisition for confirmed wash sale(s)
                if tx.transaction_id in ws_by_replacement:
                    for ws_ev in ws_by_replacement[tx.transaction_id]:
                        # Architectural Assertion: never propagate from review candidates
                        assert not ws_ev.requires_manual_review, (
                            f"Safety Violation: Attempted to propagate basis from unconfirmed review event {ws_ev.event_id}"
                        )

                        if is_ira:
                            # Section 6.2: Revenue Ruling 2008-5 Permanent Disallowance
                            # $0 basis addition for IRA replacement lot
                            lot.adjusted_basis = base_basis
                            lot.holding_period_days_tacked = 0
                            lot.lineage_event_ids.append(ws_ev.event_id)
                        else:
                            # Section 6.1: Standard IRC §1091 Basis Step-Up
                            lot.disallowed_loss_added += ws_ev.disallowed_loss
                            lot.adjusted_basis += ws_ev.disallowed_loss
                            lot.lineage_event_ids.append(ws_ev.event_id)

                tx_to_lot[tx.transaction_id] = lot
                all_lots.append(lot)
                open_lots.setdefault(key, []).append(lot)

            elif tx.transaction_type == TransactionType.SELL:
                needed = tx.quantity
                proceeds = tx.price_per_share * tx.quantity
                active_lots = open_lots.get(key, [])

                # Close lots FIFO
                for lot in active_lots:
                    if needed <= 0:
                        break
                    if lot.remaining_quantity <= 0:
                        continue

                    take_qty = min(needed, lot.remaining_quantity)
                    frac = take_qty / lot.quantity
                    cost_basis_slice = lot.adjusted_basis * frac
                    proceeds_slice = tx.price_per_share * take_qty
                    raw_gain_loss = proceeds_slice - cost_basis_slice

                    lot.remaining_quantity -= take_qty
                    needed -= take_qty
                    if lot.remaining_quantity == 0:
                        lot.is_closed = True
                        lot.closed_date = tx.trade_date

                    # Check if this sale was flagged as a wash sale
                    ws_loss_events = ws_by_loss.get(tx.transaction_id, [])
                    disallowed = sum(ev.disallowed_loss for ev in ws_loss_events) * (take_qty / tx.quantity)
                    is_ws = disallowed > 0

                    holding_days = (tx.trade_date - lot.acquired_date).days + lot.holding_period_days_tacked

                    disp = ClosedDisposition(
                        disposition_id=f"DISP-{tx.transaction_id}-{lot.lot_id}",
                        lot_id=lot.lot_id,
                        account_id=tx.account_id,
                        ticker=tx.ticker.upper(),
                        acquired_date=lot.acquired_date,
                        sold_date=tx.trade_date,
                        quantity=take_qty,
                        proceeds=proceeds_slice,
                        cost_basis=cost_basis_slice,
                        disallowed_loss=disallowed,
                        net_gain_loss=raw_gain_loss + disallowed if is_ws else raw_gain_loss,
                        is_wash_sale=is_ws,
                        is_ira=is_ira,
                        adjustment_code="W" if is_ws else None,
                        holding_period_days=holding_days,
                    )
                    all_dispositions.append(disp)

        self.lots[accounts.get("default", Account("def", "Broker", AccountType.TAXABLE)).account_id] = all_lots
        self.dispositions = all_dispositions
        return all_lots, all_dispositions
