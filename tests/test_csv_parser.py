"""
Unit tests for the Broker CSV Parser.
"""

from datetime import date
import io
import pytest

from src.ingestion.csv_parser import CSVParser
from src.models.enums import TransactionType


def test_parse_fidelity_csv() -> None:
    csv_content = """Run Date,Action,Symbol,Security Description,Security Type,Quantity,Price ($),Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date,Realized Gain/Loss ($)
01/15/2024,YOU BOUGHT,AAPL,APPLE INC,Cash,100,185.00,0.00,0.00,0.00,-18500.00,01/17/2024,
02/20/2024,YOU SOLD,AAPL,APPLE INC,Cash,100,170.00,0.00,0.00,0.00,17000.00,02/22/2024,-1500.00
"""
    txs = CSVParser.parse_csv(io.StringIO(csv_content), default_account_id="fidelity_act")
    assert len(txs) == 2
    buy_tx, sell_tx = txs[0], txs[1]

    assert buy_tx.ticker == "AAPL"
    assert buy_tx.transaction_type == TransactionType.BUY
    assert buy_tx.quantity == 100.0
    assert buy_tx.price_per_share == 185.0
    assert buy_tx.trade_date == date(2024, 1, 15)

    assert sell_tx.ticker == "AAPL"
    assert sell_tx.transaction_type == TransactionType.SELL
    assert sell_tx.quantity == 100.0
    assert sell_tx.price_per_share == 170.0
    assert sell_tx.realized_gain_loss == -1500.0
    assert sell_tx.trade_date == date(2024, 2, 20)


def test_parse_schwab_csv() -> None:
    csv_content = """"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount","Gain/Loss"
"03/10/2024","Buy","AAPL","APPLE INC","50","$172.50","$0.00","-$8,625.00",""
"04/15/2024","Sell","AAPL","APPLE INC","50","$160.00","$0.00","$8,000.00","-$625.00"
"""
    txs = CSVParser.parse_csv(io.StringIO(csv_content), default_account_id="schwab_act")
    assert len(txs) == 2
    assert txs[0].ticker == "AAPL"
    assert txs[0].transaction_type == TransactionType.BUY
    assert txs[0].price_per_share == 172.50
    assert txs[1].realized_gain_loss == -625.0


def test_parse_canonical_csv() -> None:
    csv_content = """transaction_id,account_id,ticker,cusip,transaction_type,quantity,price_per_share,trade_date,settlement_date,realized_gain_loss
TX-1,acct_1,VOO,922908769,buy,100,450.00,2024-01-10,2024-01-12,
TX-2,acct_1,VOO,922908769,sell,100,430.00,2024-02-15,2024-02-17,-2000.00
"""
    txs = CSVParser.parse_csv(io.StringIO(csv_content))
    assert len(txs) == 2
    assert txs[0].cusip == "922908769"
    assert txs[1].realized_gain_loss == -2000.0


def test_parse_sample_file_paths() -> None:
    fidelity_txs = CSVParser.parse_csv("data/sample_fidelity.csv", default_account_id="fid_1")
    assert len(fidelity_txs) == 4
    assert fidelity_txs[0].ticker == "AAPL"
    assert fidelity_txs[2].ticker == "VOO"

    schwab_txs = CSVParser.parse_csv("data/sample_schwab.csv", default_account_id="schw_1")
    assert len(schwab_txs) == 3
    assert schwab_txs[1].ticker == "IVV"
