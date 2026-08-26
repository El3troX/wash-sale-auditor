"""
Unit tests for the OFX/QFX Investment Statement Parser across multi-broker format variations
(Vanguard, Fidelity XML 2.x, Charles Schwab SGML 1.x, and malformed statements).
"""

from datetime import date
import pytest

from src.ingestion.ofx_parser import OFXParser
from src.models.enums import TransactionType


def test_parse_sample_vanguard_ofx() -> None:
    """Validates parsing standard Vanguard OFX statement."""
    txs = OFXParser.parse_ofx("data/sample_vanguard.ofx")
    assert len(txs) == 2

    buy_tx = txs[0]
    assert buy_tx.transaction_id == "VAN-TX-101"
    assert buy_tx.account_id == "VAN-ROTH-9988"
    assert buy_tx.ticker == "SPY"
    assert buy_tx.cusip == "78462F103"
    assert buy_tx.transaction_type == TransactionType.BUY
    assert buy_tx.quantity == 100.0
    assert buy_tx.price_per_share == 510.0
    assert buy_tx.trade_date == date(2024, 4, 2)

    sell_tx = txs[1]
    assert sell_tx.transaction_id == "VAN-TX-102"
    assert sell_tx.ticker == "SPY"
    assert sell_tx.transaction_type == TransactionType.SELL
    assert sell_tx.quantity == 50.0
    assert sell_tx.price_per_share == 505.0
    assert sell_tx.trade_date == date(2024, 4, 20)


def test_parse_sample_fidelity_ofx() -> None:
    """
    Validates parsing Fidelity OFX 2.x XML format with timezone strings,
    CUSIP security map, and <REINVEST> dividend reinvestment buy events.
    """
    txs = OFXParser.parse_ofx("data/sample_fidelity.ofx")
    assert len(txs) == 3

    # Transaction 1: BUY AAPL 100 shares @ $185
    t1 = txs[0]
    assert t1.transaction_id == "FID-TX-2024-001"
    assert t1.account_id == "FID-TAX-883311"
    assert t1.ticker == "AAPL"
    assert t1.cusip == "037833100"
    assert t1.transaction_type == TransactionType.BUY
    assert t1.quantity == 100.0
    assert t1.price_per_share == 185.0
    assert t1.trade_date == date(2024, 1, 15)

    # Transaction 2: SELL AAPL 100 shares @ $170 with realized loss -$1500
    t2 = txs[1]
    assert t2.transaction_id == "FID-TX-2024-002"
    assert t2.ticker == "AAPL"
    assert t2.transaction_type == TransactionType.SELL
    assert t2.quantity == 100.0
    assert t2.price_per_share == 170.0
    assert t2.realized_gain_loss == -1500.0
    assert t2.trade_date == date(2024, 2, 20)

    # Transaction 3: REINVEST VOO 10 shares @ $450 (treated as BUY)
    t3 = txs[2]
    assert t3.transaction_id == "FID-TX-2024-003"
    assert t3.ticker == "VOO"
    assert t3.cusip == "922908769"
    assert t3.transaction_type == TransactionType.BUY
    assert t3.quantity == 10.0
    assert t3.price_per_share == 450.0
    assert t3.trade_date == date(2024, 3, 15)


def test_parse_sample_schwab_ofx() -> None:
    """
    Validates parsing Charles Schwab OFX 1.x SGML format with unclosed tags,
    negative units on SELLSTOCK, <BUYMF> mutual fund buy, and price derived from TOTAL.
    """
    txs = OFXParser.parse_ofx("data/sample_schwab.ofx")
    assert len(txs) == 3

    # Transaction 1: BUY AAPL 50 @ $172.50
    t1 = txs[0]
    assert t1.transaction_id == "SCHW-TX-001"
    assert t1.account_id == "SCHW-TAX-772299"
    assert t1.ticker == "AAPL"
    assert t1.cusip == "037833100"
    assert t1.transaction_type == TransactionType.BUY
    assert t1.quantity == 50.0
    assert t1.price_per_share == 172.50
    assert t1.trade_date == date(2024, 3, 10)

    # Transaction 2: SELL AAPL 50 @ $160.00 with realized loss -$625
    t2 = txs[1]
    assert t2.transaction_id == "SCHW-TX-002"
    assert t2.ticker == "AAPL"
    assert t2.transaction_type == TransactionType.SELL
    assert t2.quantity == 50.0
    assert t2.price_per_share == 160.0
    assert t2.realized_gain_loss == -625.0
    assert t2.trade_date == date(2024, 4, 15)

    # Transaction 3: BUYMF IVV 20 units with TOTAL -9600.00 -> derived price $480.00
    t3 = txs[2]
    assert t3.transaction_id == "SCHW-TX-003"
    assert t3.ticker == "IVV"
    assert t3.cusip == "464287200"
    assert t3.transaction_type == TransactionType.BUY
    assert t3.quantity == 20.0
    assert t3.price_per_share == 480.0
    assert t3.trade_date == date(2024, 4, 25)


def test_malformed_ofx_missing_dttrade_fails_loudly() -> None:
    """Validates that a transaction block missing DTTRADE raises a ValueError loudly rather than silently dropping data."""
    malformed_ofx = """
    <OFX>
    <INVSTMTMSGSRSV1><INVSTMTRS><INVACCTFROM><ACCTID>TEST-ACC</ACCTID></INVACCTFROM>
    <INVTRANLIST>
    <BUYSTOCK>
    <INVTRAN><FITID>BAD-TX-1</FITID></INVTRAN>
    <SECID><UNIQUEID>037833100</UNIQUEID></SECID>
    <UNITS>10</UNITS>
    <UNITPRICE>150.00</UNITPRICE>
    </BUYSTOCK>
    </INVTRANLIST>
    </INVSTMTRS></INVSTMTMSGSRSV1>
    </OFX>
    """
    with pytest.raises(ValueError, match="Missing required <DTTRADE>"):
        OFXParser.parse_ofx(malformed_ofx)


def test_malformed_ofx_missing_units_fails_loudly() -> None:
    """Validates that a transaction block with missing units and total raises a ValueError loudly."""
    malformed_ofx = """
    <OFX>
    <INVSTMTMSGSRSV1><INVSTMTRS><INVACCTFROM><ACCTID>TEST-ACC</ACCTID></INVACCTFROM>
    <INVTRANLIST>
    <BUYSTOCK>
    <INVTRAN><FITID>BAD-TX-2</FITID><DTTRADE>20240101</DTTRADE></INVTRAN>
    <SECID><UNIQUEID>037833100</UNIQUEID></SECID>
    <UNITPRICE>150.00</UNITPRICE>
    </BUYSTOCK>
    </INVTRANLIST>
    </INVSTMTRS></INVSTMTMSGSRSV1>
    </OFX>
    """
    with pytest.raises(ValueError, match="neither <UNITS> nor <TOTAL>"):
        OFXParser.parse_ofx(malformed_ofx)


def test_parse_raw_ofx_string() -> None:
    raw_ofx = """
    <OFX>
    <INVSTMTMSGSRSV1>
    <INVSTMTRS>
    <INVACCTFROM><ACCTID>ACCT-TEST-1</INVACCTFROM>
    <INVTRANLIST>
    <BUYSTOCK>
    <INVTRAN><FITID>TX-999</FITID><DTTRADE>20240301120000</DTTRADE></INVTRAN>
    <SECID><UNIQUEID>037833100</UNIQUEID></SECID>
    <UNITS>25</UNITS>
    <UNITPRICE>180.00</UNITPRICE>
    </BUYSTOCK>
    </INVTRANLIST>
    </INVSTMTRS>
    </INVSTMTMSGSRSV1>
    <SECLISTMSGSRSV1><SECLIST><STOCKINFO><SECINFO>
    <SECID><UNIQUEID>037833100</UNIQUEID></SECID>
    <TICKER>AAPL</TICKER>
    </SECINFO></STOCKINFO></SECLIST></SECLISTMSGSRSV1>
    </OFX>
    """
    txs = OFXParser.parse_ofx(raw_ofx)
    assert len(txs) == 1
    assert txs[0].ticker == "AAPL"
    assert txs[0].cusip == "037833100"
    assert txs[0].quantity == 25.0
    assert txs[0].trade_date == date(2024, 3, 1)
