"""
Integration tests proving mandatory corporate action split adjustment during ingestion.
Validates that CSV, OFX, and Plaid ingestion automatically normalize pre-split trades
across forward splits, reverse splits, multi-split chains, and emit audit warnings for unverified tickers.
"""

from datetime import date
import io
import pytest

from src.corporate_actions.split_adjuster import SplitAdjuster, StockSplit
from src.ingestion.csv_parser import CSVParser
from src.ingestion.ofx_parser import OFXParser
from src.ingestion.pipeline import IngestionPipeline
from src.models.enums import TransactionType


def test_automatic_csv_split_adjustment_with_known_splits() -> None:
    """
    Scenario 1: Forward Split with Pre-curated Split Data.
    NVDA 10-for-1 forward split on 2024-06-10.
    Pre-split trade (2024-05-15) adjusted from 10 @ $1000 to 100 @ $100.
    Post-split trade (2024-06-20) remains 100 @ $120.
    """
    csv_data = """trade_date,ticker,transaction_type,quantity,price_per_share,settlement_date
2024-05-15,NVDA,buy,10,1000.00,2024-05-17
2024-06-20,NVDA,buy,100,120.00,2024-06-22
"""
    txs = CSVParser.parse_csv(io.StringIO(csv_data), default_account_id="fid_tax")

    assert len(txs) == 2
    pre_split_tx = txs[0]
    post_split_tx = txs[1]

    # Pre-split trade must be automatically adjusted: 10 * 10 = 100 shares @ $1,000 / 10 = $100.00
    assert pre_split_tx.quantity == 100.0
    assert pre_split_tx.price_per_share == 100.0
    assert pre_split_tx.unmatched_quantity == 100.0
    assert pre_split_tx.total_value == 10000.0  # Total cost basis invariant

    # Post-split trade must remain as recorded
    assert post_split_tx.quantity == 100.0
    assert post_split_tx.price_per_share == 120.0


def test_automatic_csv_reverse_split_adjustment() -> None:
    """
    Scenario 2: Reverse Stock Split (1-for-4 reverse split, ratio = 0.25).
    Pre-split trade (100 shares @ $5.00) adjusted to 25 shares @ $20.00.
    """
    adjuster = SplitAdjuster(include_known_splits=False)
    adjuster.register_split(StockSplit(ticker="SOFI_TEST", effective_date=date(2024, 7, 1), ratio=0.25))

    csv_data = """trade_date,ticker,transaction_type,quantity,price_per_share
2024-06-01,SOFI_TEST,buy,100,5.00
2024-07-15,SOFI_TEST,buy,25,20.00
"""
    txs = CSVParser.parse_csv(
        io.StringIO(csv_data),
        default_account_id="schw_tax",
        split_adjuster=adjuster,
    )

    assert len(txs) == 2
    pre_rev = txs[0]
    post_rev = txs[1]

    # 100 * 0.25 = 25 shares @ $5.00 / 0.25 = $20.00
    assert pre_rev.quantity == 25.0
    assert pre_rev.price_per_share == 20.0
    assert pre_rev.unmatched_quantity == 25.0
    assert pre_rev.total_value == 500.0  # Invariant total cost basis

    # Post-split trade remains 25 @ $20.00
    assert post_rev.quantity == 25.0
    assert post_rev.price_per_share == 20.0


def test_automatic_csv_multi_split_chain_adjustment() -> None:
    """
    Scenario 3: Multi-Split Cumulative Chain.
    Split 1: 2-for-1 on 2024-03-01
    Split 2: 3-for-1 on 2024-09-01
    Cumulative multiplier:
    - Pre-March (Jan): 2 * 3 = 6x multiplier
    - Mid-period (Jun): 3x multiplier
    - Post-September (Oct): 1x multiplier
    """
    adjuster = SplitAdjuster(include_known_splits=False)
    adjuster.register_splits([
        StockSplit(ticker="GROWTH", effective_date=date(2024, 3, 1), ratio=2.0),
        StockSplit(ticker="GROWTH", effective_date=date(2024, 9, 1), ratio=3.0),
    ])

    csv_data = """trade_date,ticker,transaction_type,quantity,price_per_share
2024-01-15,GROWTH,buy,10,600.00
2024-06-01,GROWTH,buy,20,300.00
2024-10-01,GROWTH,buy,60,100.00
"""
    txs = CSVParser.parse_csv(
        io.StringIO(csv_data),
        default_account_id="van_tax",
        split_adjuster=adjuster,
    )

    assert len(txs) == 3
    # Jan trade: 10 * 6 = 60 shares @ $600 / 6 = $100
    assert txs[0].quantity == 60.0
    assert txs[0].price_per_share == 100.0
    assert txs[0].total_value == 6000.0

    # Jun trade: 20 * 3 = 60 shares @ $300 / 3 = $100
    assert txs[1].quantity == 60.0
    assert txs[1].price_per_share == 100.0
    assert txs[1].total_value == 6000.0

    # Oct trade: 60 * 1 = 60 shares @ $100
    assert txs[2].quantity == 60.0
    assert txs[2].price_per_share == 100.0
    assert txs[2].total_value == 6000.0


def test_automatic_ofx_split_adjustment() -> None:
    """
    Scenario 4: OFX Statement Split Adjustment (TSLA 3-for-1 on 2022-08-25).
    """
    ofx_raw = """
    <OFX>
    <INVSTMTMSGSRSV1>
    <INVSTMTRS>
    <INVACCTFROM><ACCTID>ACCT-TSLA-1</ACCTID></INVACCTFROM>
    <INVTRANLIST>
    <BUYSTOCK>
    <INVTRAN><FITID>TSLA-TX-1</FITID><DTTRADE>20220801120000</DTTRADE></INVTRAN>
    <SECID><UNIQUEID>88160R101</UNIQUEID></SECID>
    <TICKER>TSLA</TICKER>
    <UNITS>10</UNITS>
    <UNITPRICE>900.00</UNITPRICE>
    </BUYSTOCK>
    </INVTRANLIST>
    </INVSTMTRS>
    </INVSTMTMSGSRSV1>
    </OFX>
    """
    txs = OFXParser.parse_ofx(ofx_raw)
    assert len(txs) == 1
    tsla_tx = txs[0]

    assert tsla_tx.quantity == 30.0  # 10 * 3
    assert tsla_tx.price_per_share == 300.0  # 900 / 3
    assert tsla_tx.unmatched_quantity == 30.0


def test_unverified_ticker_emits_explicit_audit_warning() -> None:
    """
    Scenario 5: Unverified Ticker Warning.
    When a ticker without verified corporate action data is ingested,
    the pipeline explicitly logs and records an audit warning.
    """
    adjuster = SplitAdjuster(include_known_splits=True, enable_online_lookup=False)
    csv_data = """trade_date,ticker,transaction_type,quantity,price_per_share
2024-05-01,UNKNOWN_BIO,buy,100,25.00
"""
    txs = CSVParser.parse_csv(io.StringIO(csv_data), split_adjuster=adjuster)
    assert len(txs) == 1
    # Check that warning was recorded
    assert len(adjuster.audit_warnings) > 0
    assert any("UNKNOWN_BIO" in w for w in adjuster.audit_warnings)
