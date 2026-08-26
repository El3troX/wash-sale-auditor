"""
Unit tests for core data models, enums, and serialization.
"""

from datetime import date
import pytest

from src.models.entities import Account, Transaction, AssetProfile, WashSaleEvent
from src.models.enums import AccountType, TransactionType


def test_account_model() -> None:
    acc = Account(
        account_id="ACC-01",
        broker_name="Fidelity",
        account_type=AccountType.TAXABLE,
    )
    assert acc.account_id == "ACC-01"
    assert acc.broker_name == "Fidelity"
    assert acc.account_type == AccountType.TAXABLE
    assert not acc.account_type.is_tax_advantaged

    d = acc.to_dict()
    assert d["account_type"] == "taxable"
    reconstructed = Account.from_dict(d)
    assert reconstructed == acc


def test_account_type_tax_advantaged() -> None:
    assert AccountType.ROTH_IRA.is_tax_advantaged
    assert AccountType.TRADITIONAL_IRA.is_tax_advantaged
    assert not AccountType.TAXABLE.is_tax_advantaged
    assert not AccountType.ROBO_MANAGED.is_tax_advantaged


def test_transaction_model_initialization_and_properties() -> None:
    tx = Transaction(
        transaction_id="TX-100",
        account_id="ACC-01",
        ticker="AAPL",
        cusip="037833100",
        transaction_type=TransactionType.BUY,
        quantity=50.0,
        price_per_share=180.0,
        trade_date=date(2024, 1, 15),
        settlement_date=date(2024, 1, 17),
    )
    assert tx.total_value == 9000.0
    assert tx.unmatched_quantity == 50.0
    assert not tx.is_loss

    # Test sell with realized loss
    sell_loss = Transaction(
        transaction_id="TX-101",
        account_id="ACC-01",
        ticker="AAPL",
        cusip="037833100",
        transaction_type=TransactionType.SELL,
        quantity=50.0,
        price_per_share=160.0,
        trade_date=date(2024, 2, 1),
        settlement_date=date(2024, 2, 3),
        realized_gain_loss=-1000.0,
    )
    assert sell_loss.is_loss

    # Serialization roundtrip
    d = sell_loss.to_dict()
    reconstructed = Transaction.from_dict(d)
    assert reconstructed.transaction_id == sell_loss.transaction_id
    assert reconstructed.realized_gain_loss == -1000.0
    assert reconstructed.trade_date == date(2024, 2, 1)


def test_asset_profile_model() -> None:
    profile = AssetProfile(
        ticker="VOO",
        cusip="922908769",
        asset_type="etf",
        holdings_vector={"AAPL": 0.07, "MSFT": 0.065, "NVDA": 0.06},
        tracked_index="S&P 500",
        last_updated=date(2024, 3, 31),
    )
    assert profile.ticker == "VOO"
    assert profile.holdings_vector["AAPL"] == 0.07
    d = profile.to_dict()
    reconstructed = AssetProfile.from_dict(d)
    assert reconstructed.ticker == "VOO"
    assert reconstructed.last_updated == date(2024, 3, 31)


def test_wash_sale_event_model() -> None:
    ws = WashSaleEvent(
        event_id="WS-TX1-TX2",
        loss_transaction_id="TX1",
        replacement_transaction_id="TX2",
        matched_quantity=50.0,
        disallowed_loss=1000.0,
        similarity_score=1.0,
        window_days=14,
        is_ira_disallowance=False,
        rationale="Loss sale of AAPL matched with purchase of AAPL in Fidelity",
    )
    assert ws.matched_quantity == 50.0
    assert ws.disallowed_loss == 1000.0
    assert ws.rationale != ""

    d = ws.to_dict()
    reconstructed = WashSaleEvent.from_dict(d)
    assert reconstructed == ws
