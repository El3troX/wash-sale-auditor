"""
Core data entities for the Multi-Broker Wash Sale Auditor.
Strictly conforms to Section 3.1 of the Technical Design Document.
"""

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Dict, Optional

from src.models.enums import AccountType, TransactionType


@dataclass
class Account:
    """Represents a discrete brokerage account with a specific tax classification."""
    account_id: str
    broker_name: str
    account_type: AccountType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "broker_name": self.broker_name,
            "account_type": self.account_type.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        return cls(
            account_id=data["account_id"],
            broker_name=data["broker_name"],
            account_type=AccountType(data["account_type"]) if isinstance(data["account_type"], str) else data["account_type"],
        )


@dataclass
class Transaction:
    """Represents an execution leg in a security."""
    transaction_id: str
    account_id: str
    ticker: str
    cusip: Optional[str]
    transaction_type: TransactionType
    quantity: float
    price_per_share: float
    trade_date: date
    settlement_date: date
    realized_gain_loss: Optional[float] = None
    unmatched_quantity: float = 0.0
    adjusted_basis: Optional[float] = None  # Lot basis adjustment after wash sale propagation

    def __post_init__(self) -> None:
        if self.unmatched_quantity == 0.0 and self.quantity > 0:
            self.unmatched_quantity = float(self.quantity)

    @property
    def total_value(self) -> float:
        """Gross transaction value."""
        return self.quantity * self.price_per_share

    @property
    def is_loss(self) -> bool:
        """Returns True if transaction is a sell with a realized loss."""
        return (
            self.transaction_type == TransactionType.SELL
            and self.realized_gain_loss is not None
            and self.realized_gain_loss < 0
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "ticker": self.ticker,
            "cusip": self.cusip,
            "transaction_type": self.transaction_type.value,
            "quantity": self.quantity,
            "price_per_share": self.price_per_share,
            "trade_date": self.trade_date.isoformat() if isinstance(self.trade_date, date) else self.trade_date,
            "settlement_date": self.settlement_date.isoformat() if isinstance(self.settlement_date, date) else self.settlement_date,
            "realized_gain_loss": self.realized_gain_loss,
            "unmatched_quantity": self.unmatched_quantity,
            "adjusted_basis": self.adjusted_basis,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transaction":
        t_type = TransactionType(data["transaction_type"]) if isinstance(data["transaction_type"], str) else data["transaction_type"]
        t_date = date.fromisoformat(data["trade_date"]) if isinstance(data["trade_date"], str) else data["trade_date"]
        s_date = date.fromisoformat(data["settlement_date"]) if isinstance(data["settlement_date"], str) else data["settlement_date"]
        return cls(
            transaction_id=data["transaction_id"],
            account_id=data["account_id"],
            ticker=data["ticker"],
            cusip=data.get("cusip"),
            transaction_type=t_type,
            quantity=float(data["quantity"]),
            price_per_share=float(data["price_per_share"]),
            trade_date=t_date,
            settlement_date=s_date,
            realized_gain_loss=float(data["realized_gain_loss"]) if data.get("realized_gain_loss") is not None else None,
            unmatched_quantity=float(data.get("unmatched_quantity", data["quantity"])),
            adjusted_basis=float(data["adjusted_basis"]) if data.get("adjusted_basis") is not None else None,
        )


@dataclass
class AssetProfile:
    """Security reference metadata and portfolio constituent weights."""
    ticker: str
    cusip: Optional[str] = None
    asset_type: str = "equity"  # equity, etf, mutual_fund
    holdings_vector: Dict[str, float] = field(default_factory=dict)  # constituent_ticker/cusip -> weight (0.0 - 1.0)
    tracked_index: Optional[str] = None
    last_updated: Optional[date] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "cusip": self.cusip,
            "asset_type": self.asset_type,
            "holdings_vector": self.holdings_vector,
            "tracked_index": self.tracked_index,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssetProfile":
        l_date = date.fromisoformat(data["last_updated"]) if data.get("last_updated") else None
        return cls(
            ticker=data["ticker"],
            cusip=data.get("cusip"),
            asset_type=data["asset_type"],
            holdings_vector=data.get("holdings_vector", {}),
            tracked_index=data.get("tracked_index"),
            last_updated=l_date,
        )


@dataclass
class WashSaleEvent:
    """
    Represents a matched wash sale violation between a loss sale and replacement acquisition.
    Conforms to Section 3.1 & 4.3 of the Technical Design Document.
    """
    event_id: str
    loss_transaction_id: str
    replacement_transaction_id: str
    matched_quantity: float
    disallowed_loss: float
    similarity_score: float
    window_days: int
    is_ira_disallowance: bool
    rationale: str
    requires_manual_review: bool = False
    tier: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WashSaleEvent":
        return cls(
            event_id=data["event_id"],
            loss_transaction_id=data["loss_transaction_id"],
            replacement_transaction_id=data["replacement_transaction_id"],
            matched_quantity=float(data["matched_quantity"]),
            disallowed_loss=float(data["disallowed_loss"]),
            similarity_score=float(data["similarity_score"]),
            window_days=int(data["window_days"]),
            is_ira_disallowance=bool(data["is_ira_disallowance"]),
            rationale=data["rationale"],
            requires_manual_review=bool(data.get("requires_manual_review", False)),
            tier=int(data.get("tier", 1)),
        )
