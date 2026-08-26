"""
Unit tests for the Corporate Action Split Normalization Engine.
Conforms to Section 3.2: Q_adj = Q_raw * S(t), P_adj = P_raw / S(t).
"""

from datetime import date
import pytest

from src.corporate_actions.split_adjuster import SplitAdjuster, StockSplit
from src.models.entities import Transaction
from src.models.enums import TransactionType


def test_single_forward_stock_split() -> None:
    # 2-for-1 forward split on NVDA effective 2024-06-10
    adjuster = SplitAdjuster(include_known_splits=False)
    adjuster.register_split(StockSplit(ticker="NVDA", effective_date=date(2024, 6, 10), ratio=2.0))

    # Pre-split trade
    pre_tx = Transaction(
        transaction_id="TX-PRE",
        account_id="ACC-1",
        ticker="NVDA",
        cusip="67066G104",
        transaction_type=TransactionType.BUY,
        quantity=50.0,
        price_per_share=200.0,
        trade_date=date(2024, 5, 1),
        settlement_date=date(2024, 5, 3),
    )

    # Post-split trade
    post_tx = Transaction(
        transaction_id="TX-POST",
        account_id="ACC-1",
        ticker="NVDA",
        cusip="67066G104",
        transaction_type=TransactionType.BUY,
        quantity=100.0,
        price_per_share=100.0,
        trade_date=date(2024, 6, 15),
        settlement_date=date(2024, 6, 17),
    )

    adj_pre = adjuster.adjust_transaction(pre_tx)
    adj_post = adjuster.adjust_transaction(post_tx)

    # Pre-split quantity doubled, price halved; total dollar basis invariant
    assert adj_pre.quantity == 100.0
    assert adj_pre.price_per_share == 100.0
    assert adj_pre.unmatched_quantity == 100.0
    assert adj_pre.total_value == 10000.0
    assert pre_tx.total_value == 10000.0

    # Post-split trade unchanged
    assert adj_post.quantity == 100.0
    assert adj_post.price_per_share == 100.0


def test_multiple_cumulative_stock_splits() -> None:
    # Multi-split: 2-for-1 on 2024-03-01, then 3-for-1 on 2024-09-01 (total 6x multiplier for pre-March trades)
    adjuster = SplitAdjuster()
    adjuster.register_splits([
        StockSplit(ticker="XYZ", effective_date=date(2024, 3, 1), ratio=2.0),
        StockSplit(ticker="XYZ", effective_date=date(2024, 9, 1), ratio=3.0),
    ])

    tx_jan = Transaction(
        transaction_id="TX-JAN",
        account_id="ACC-1",
        ticker="XYZ",
        cusip=None,
        transaction_type=TransactionType.BUY,
        quantity=10.0,
        price_per_share=600.0,
        trade_date=date(2024, 1, 15),
        settlement_date=date(2024, 1, 17),
    )
    tx_jun = Transaction(
        transaction_id="TX-JUN",
        account_id="ACC-1",
        ticker="XYZ",
        cusip=None,
        transaction_type=TransactionType.BUY,
        quantity=20.0,
        price_per_share=300.0,
        trade_date=date(2024, 6, 1),
        settlement_date=date(2024, 6, 3),
    )
    tx_oct = Transaction(
        transaction_id="TX-OCT",
        account_id="ACC-1",
        ticker="XYZ",
        cusip=None,
        transaction_type=TransactionType.BUY,
        quantity=60.0,
        price_per_share=100.0,
        trade_date=date(2024, 10, 1),
        settlement_date=date(2024, 10, 3),
    )

    normalized = adjuster.normalize_transactions([tx_jan, tx_jun, tx_oct])

    assert normalized[0].quantity == 60.0  # 10 * 2 * 3
    assert normalized[0].price_per_share == 100.0  # 600 / 6

    assert normalized[1].quantity == 60.0  # 20 * 3
    assert normalized[1].price_per_share == 100.0  # 300 / 3

    assert normalized[2].quantity == 60.0  # 60 * 1
    assert normalized[2].price_per_share == 100.0


def test_reverse_stock_split() -> None:
    # 1-for-4 reverse split (ratio = 0.25)
    adjuster = SplitAdjuster()
    adjuster.register_split(StockSplit(ticker="REV", effective_date=date(2024, 5, 1), ratio=0.25))

    tx = Transaction(
        transaction_id="TX-1",
        account_id="ACC-1",
        ticker="REV",
        cusip=None,
        transaction_type=TransactionType.BUY,
        quantity=100.0,
        price_per_share=5.0,
        trade_date=date(2024, 4, 1),
        settlement_date=date(2024, 4, 3),
    )

    adj = adjuster.adjust_transaction(tx)
    assert adj.quantity == 25.0
    assert adj.price_per_share == 20.0
    assert adj.total_value == 500.0
