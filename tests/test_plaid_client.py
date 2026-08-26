"""
Unit tests for Plaid client ingestion and payload normalization.
"""

from datetime import date
import pytest

from src.ingestion.plaid_client import PlaidClient
from src.models.enums import AccountType, TransactionType


def test_plaid_payload_normalization() -> None:
    sample_payload = {
        "accounts": [
            {
                "account_id": "plaid_acc_1",
                "name": "Fidelity Individual Brokerage",
                "institution_name": "Fidelity",
                "subtype": "brokerage",
            },
            {
                "account_id": "plaid_acc_2",
                "name": "Vanguard Roth IRA",
                "institution_name": "Vanguard",
                "subtype": "roth",
            },
        ],
        "securities": [
            {
                "security_id": "sec_aapl",
                "ticker_symbol": "AAPL",
                "cusip": "037833100",
                "name": "Apple Inc",
            },
            {
                "security_id": "sec_voo",
                "ticker_symbol": "VOO",
                "cusip": "922908769",
                "name": "Vanguard 500 Index Fund",
            },
        ],
        "investment_transactions": [
            {
                "investment_transaction_id": "plaid_tx_1",
                "account_id": "plaid_acc_1",
                "security_id": "sec_aapl",
                "date": "2024-02-15",
                "type": "buy",
                "quantity": 10.0,
                "price": 180.0,
                "amount": -1800.0,
            },
            {
                "investment_transaction_id": "plaid_tx_2",
                "account_id": "plaid_acc_2",
                "security_id": "sec_voo",
                "date": "2024-03-01",
                "type": "sell",
                "quantity": 5.0,
                "price": 450.0,
                "amount": 2250.0,
            },
        ],
    }

    accounts, transactions = PlaidClient.parse_plaid_payload(sample_payload)

    assert len(accounts) == 2
    acc_map = {a.account_id: a for a in accounts}
    assert acc_map["plaid_acc_1"].account_type == AccountType.TAXABLE
    assert acc_map["plaid_acc_2"].account_type == AccountType.ROTH_IRA
    assert acc_map["plaid_acc_2"].account_type.is_tax_advantaged

    assert len(transactions) == 2
    tx1, tx2 = transactions[0], transactions[1]
    assert tx1.ticker == "AAPL"
    assert tx1.cusip == "037833100"
    assert tx1.transaction_type == TransactionType.BUY
    assert tx1.quantity == 10.0
    assert tx1.price_per_share == 180.0
    assert tx1.trade_date == date(2024, 2, 15)

    assert tx2.ticker == "VOO"
    assert tx2.cusip == "922908769"
    assert tx2.transaction_type == TransactionType.SELL
    assert tx2.quantity == 5.0
    assert tx2.price_per_share == 450.0
    assert tx2.trade_date == date(2024, 3, 1)


def test_plaid_client_initialization() -> None:
    client = PlaidClient(client_id="test_id", secret="test_sec", environment="sandbox")
    assert client.client_id == "test_id"
    assert client.environment == "sandbox"
