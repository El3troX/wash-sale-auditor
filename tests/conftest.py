"""
Pytest fixtures providing reusable synthetic multi-account transaction datasets
strictly mapped to the test matrix in Section 8 of the Technical Design Document (TDD).

Covers:
- TC-01: IRS Pub 550 Baseline (Single account, loss sale + 14-day rebuy)
- TC-02: 30-Day Lookback Window (Pre-sale replacement buy 14 days before loss sale)
- TC-03: Cross-Broker ETF Swap (Sell VOO at loss in Fidelity, buy IVV in Schwab within 5 days)
- TC-04: IRA Revenue Ruling 2008-5 (Sell SPY at loss in taxable, buy SPY in Roth IRA 10 days later)
- TC-05 Sub-case A: Chained Wash Sales (B0 -> S0(loss) -> B1 -> S1(loss) -> B2)
- TC-05 Sub-case B: Two Loss Sales Competing for One Replacement Buy (S1 @ D1, S2 @ D2 > D1 competing for B @ D3)
- TC-06: Same-Day Same-Lot False Positive (Sell leg matching against its own buy lot/ID)
- Full Composite Portfolio: Multi-account comprehensive tax-year ledger
"""

from datetime import date
from typing import Dict, List
import pytest

from src.models.entities import Account, Transaction
from src.models.enums import AccountType, TransactionType


@pytest.fixture
def multi_accounts() -> Dict[str, Account]:
    """Standard multi-broker portfolio across taxable and retirement accounts."""
    return {
        "fidelity_taxable": Account(
            account_id="acct_fid_tax",
            broker_name="Fidelity",
            account_type=AccountType.TAXABLE,
        ),
        "schwab_taxable": Account(
            account_id="acct_schw_tax",
            broker_name="Charles Schwab",
            account_type=AccountType.TAXABLE,
        ),
        "vanguard_roth": Account(
            account_id="acct_van_roth",
            broker_name="Vanguard",
            account_type=AccountType.ROTH_IRA,
        ),
        "wealthfront_robo": Account(
            account_id="acct_wf_robo",
            broker_name="Wealthfront",
            account_type=AccountType.ROBO_MANAGED,
        ),
    }


@pytest.fixture
def tc01_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """
    TC-01: IRS Pub 550 Baseline
    Single taxable account: Buy 100 shares @ $100, sell @ $80 (loss $2,000), rebuy 100 @ $90 within 20 days.
    Expected: 100% loss ($2,000) disallowed; basis increased on replacement lot to $110/share.
    """
    fid = multi_accounts["fidelity_taxable"]
    return [
        Transaction(
            transaction_id="TC01-BUY-1",
            account_id=fid.account_id,
            ticker="AAPL",
            cusip="037833100",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=100.0,
            trade_date=date(2024, 1, 10),
            settlement_date=date(2024, 1, 12),
        ),
        Transaction(
            transaction_id="TC01-SELL-1",
            account_id=fid.account_id,
            ticker="AAPL",
            cusip="037833100",
            transaction_type=TransactionType.SELL,
            quantity=100.0,
            price_per_share=80.0,
            trade_date=date(2024, 2, 1),
            settlement_date=date(2024, 2, 3),
            realized_gain_loss=-2000.0,
        ),
        Transaction(
            transaction_id="TC01-BUY-2",
            account_id=fid.account_id,
            ticker="AAPL",
            cusip="037833100",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=90.0,
            trade_date=date(2024, 2, 15),  # 14 days after loss sale (inside +30 day window)
            settlement_date=date(2024, 2, 17),
        ),
    ]


@pytest.fixture
def tc02_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """
    TC-02: 30-Day Lookback Window
    Buy replacement 14 days BEFORE selling original lot at a loss.
    Expected: Wash sale triggered via pre-sale window capture (-30 days).
    """
    fid = multi_accounts["fidelity_taxable"]
    return [
        Transaction(
            transaction_id="TC02-BUY-ORIG",
            account_id=fid.account_id,
            ticker="MSFT",
            cusip="594918104",
            transaction_type=TransactionType.BUY,
            quantity=50.0,
            price_per_share=400.0,
            trade_date=date(2024, 1, 5),
            settlement_date=date(2024, 1, 7),
        ),
        Transaction(
            transaction_id="TC02-BUY-REPL",
            account_id=fid.account_id,
            ticker="MSFT",
            cusip="594918104",
            transaction_type=TransactionType.BUY,
            quantity=50.0,
            price_per_share=370.0,
            trade_date=date(2024, 3, 1),  # 14 days BEFORE sell
            settlement_date=date(2024, 3, 3),
        ),
        Transaction(
            transaction_id="TC02-SELL-LOSS",
            account_id=fid.account_id,
            ticker="MSFT",
            cusip="594918104",
            transaction_type=TransactionType.SELL,
            quantity=50.0,
            price_per_share=360.0,
            trade_date=date(2024, 3, 15),
            settlement_date=date(2024, 3, 17),
            realized_gain_loss=-2000.0,
        ),
    ]


@pytest.fixture
def tc03_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """
    TC-03: Cross-Broker ETF Swap
    Sell VOO at a loss in Fidelity, buy IVV in Charles Schwab 5 days later.
    Expected: Tier 2 equivalence match (both track S&P 500), cross-account loss disallowed.
    """
    fid = multi_accounts["fidelity_taxable"]
    schw = multi_accounts["schwab_taxable"]
    return [
        Transaction(
            transaction_id="TC03-SELL-VOO",
            account_id=fid.account_id,
            ticker="VOO",
            cusip="922908769",
            transaction_type=TransactionType.SELL,
            quantity=100.0,
            price_per_share=450.0,
            trade_date=date(2024, 4, 10),
            settlement_date=date(2024, 4, 12),
            realized_gain_loss=-3000.0,
        ),
        Transaction(
            transaction_id="TC03-BUY-IVV",
            account_id=schw.account_id,
            ticker="IVV",
            cusip="464287200",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=452.0,
            trade_date=date(2024, 4, 15),  # 5 days later in Schwab
            settlement_date=date(2024, 4, 17),
        ),
    ]


@pytest.fixture
def tc04_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """
    TC-04: IRA Revenue Ruling 2008-5
    Sell SPY at a loss in Fidelity Taxable, buy SPY in Vanguard Roth IRA 10 days later.
    Expected: Loss permanently disallowed, $0 basis adjustment added to Roth IRA asset.
    """
    fid = multi_accounts["fidelity_taxable"]
    van_roth = multi_accounts["vanguard_roth"]
    return [
        Transaction(
            transaction_id="TC04-SELL-TAXABLE",
            account_id=fid.account_id,
            ticker="SPY",
            cusip="78462F103",
            transaction_type=TransactionType.SELL,
            quantity=100.0,
            price_per_share=500.0,
            trade_date=date(2024, 5, 1),
            settlement_date=date(2024, 5, 3),
            realized_gain_loss=-4000.0,
        ),
        Transaction(
            transaction_id="TC04-BUY-ROTH",
            account_id=van_roth.account_id,
            ticker="SPY",
            cusip="78462F103",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=505.0,
            trade_date=date(2024, 5, 11),  # 10 days later in Roth IRA
            settlement_date=date(2024, 5, 13),
        ),
    ]


@pytest.fixture
def tc05_chained_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """
    TC-05 Sub-case A: Chained Wash Sales
    Buy B0 -> Sell S0 at loss -> Rebuy B1 (wash sale 1) -> Sell S1 at loss -> Rebuy B2 (wash sale 2).
    Expected: Disallowed loss from S0 propagates to basis of B1; when B1 sold at loss in S1,
    cumulative disallowed loss propagates forward to B2.
    """
    fid = multi_accounts["fidelity_taxable"]
    return [
        Transaction(
            transaction_id="TC05-BUY-B0",
            account_id=fid.account_id,
            ticker="NVDA",
            cusip="67066G104",
            transaction_type=TransactionType.BUY,
            quantity=50.0,
            price_per_share=120.0,
            trade_date=date(2024, 6, 1),
            settlement_date=date(2024, 6, 3),
        ),
        Transaction(
            transaction_id="TC05-SELL-S0",
            account_id=fid.account_id,
            ticker="NVDA",
            cusip="67066G104",
            transaction_type=TransactionType.SELL,
            quantity=50.0,
            price_per_share=100.0,
            trade_date=date(2024, 6, 15),
            settlement_date=date(2024, 6, 17),
            realized_gain_loss=-1000.0,
        ),
        Transaction(
            transaction_id="TC05-BUY-B1",
            account_id=fid.account_id,
            ticker="NVDA",
            cusip="67066G104",
            transaction_type=TransactionType.BUY,
            quantity=50.0,
            price_per_share=105.0,
            trade_date=date(2024, 6, 25),
            settlement_date=date(2024, 6, 27),
        ),
        Transaction(
            transaction_id="TC05-SELL-S1",
            account_id=fid.account_id,
            ticker="NVDA",
            cusip="67066G104",
            transaction_type=TransactionType.SELL,
            quantity=50.0,
            price_per_share=95.0,
            trade_date=date(2024, 7, 10),
            settlement_date=date(2024, 7, 12),
            realized_gain_loss=-500.0,
        ),
        Transaction(
            transaction_id="TC05-BUY-B2",
            account_id=fid.account_id,
            ticker="NVDA",
            cusip="67066G104",
            transaction_type=TransactionType.BUY,
            quantity=50.0,
            price_per_share=98.0,
            trade_date=date(2024, 7, 20),
            settlement_date=date(2024, 7, 22),
        ),
    ]


@pytest.fixture
def tc05_competing_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """
    TC-05 Sub-case B: Two Loss Sales Competing for One Replacement Buy
    Loss Sell S1 (trade_date 2024-08-01, qty 50) and Loss Sell S2 (trade_date 2024-08-10, qty 50)
    both fall within the 30-day window of a single Buy B1 (trade_date 2024-08-15, qty 50).
    Expected: S1 claims the 50 replacement shares first due to strict chronological ordering (Section 5.2).
    S2 receives 0 matched shares and remains a fully deductible loss.
    """
    fid = multi_accounts["fidelity_taxable"]
    return [
        Transaction(
            transaction_id="TC05B-SELL-S1",
            account_id=fid.account_id,
            ticker="AMD",
            cusip="007903107",
            transaction_type=TransactionType.SELL,
            quantity=50.0,
            price_per_share=150.0,
            trade_date=date(2024, 8, 1),
            settlement_date=date(2024, 8, 3),
            realized_gain_loss=-1500.0,
        ),
        Transaction(
            transaction_id="TC05B-SELL-S2",
            account_id=fid.account_id,
            ticker="AMD",
            cusip="007903107",
            transaction_type=TransactionType.SELL,
            quantity=50.0,
            price_per_share=140.0,
            trade_date=date(2024, 8, 10),
            settlement_date=date(2024, 8, 12),
            realized_gain_loss=-1000.0,
        ),
        Transaction(
            transaction_id="TC05B-BUY-B1",
            account_id=fid.account_id,
            ticker="AMD",
            cusip="007903107",
            transaction_type=TransactionType.BUY,
            quantity=50.0,
            price_per_share=145.0,
            trade_date=date(2024, 8, 15),
            settlement_date=date(2024, 8, 17),
        ),
    ]


@pytest.fixture
def tc06_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """
    TC-06: Same-Day Same-Lot False Positive Prevention
    A sell transaction should not match against its own acquisition leg or duplicate transaction ID
    reported on the same day.
    """
    fid = multi_accounts["fidelity_taxable"]
    return [
        Transaction(
            transaction_id="TC06-ORIG-BUY",
            account_id=fid.account_id,
            ticker="GOOGL",
            cusip="02079K305",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=170.0,
            trade_date=date(2024, 9, 1),
            settlement_date=date(2024, 9, 3),
        ),
        Transaction(
            transaction_id="TC06-SELL-SAME-LOT",
            account_id=fid.account_id,
            ticker="GOOGL",
            cusip="02079K305",
            transaction_type=TransactionType.SELL,
            quantity=100.0,
            price_per_share=160.0,
            trade_date=date(2024, 9, 1),
            settlement_date=date(2024, 9, 3),
            realized_gain_loss=-1000.0,
        ),
        Transaction(
            transaction_id="TC06-SELL-SAME-LOT",  # Duplicate reporting of same trade leg
            account_id=fid.account_id,
            ticker="GOOGL",
            cusip="02079K305",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=160.0,
            trade_date=date(2024, 9, 1),
            settlement_date=date(2024, 9, 3),
        ),
    ]


@pytest.fixture
def full_portfolio_dataset(
    tc01_dataset: List[Transaction],
    tc02_dataset: List[Transaction],
    tc03_dataset: List[Transaction],
    tc04_dataset: List[Transaction],
    tc05_chained_dataset: List[Transaction],
    tc05_competing_dataset: List[Transaction],
    tc06_dataset: List[Transaction],
) -> List[Transaction]:
    """
    Comprehensive multi-account annual trade ledger aggregating all test matrix scenarios
    sorted chronologically.
    """
    all_txs = (
        tc01_dataset
        + tc02_dataset
        + tc03_dataset
        + tc04_dataset
        + tc05_chained_dataset
        + tc05_competing_dataset
        + tc06_dataset
    )
    all_txs.sort(key=lambda x: (x.trade_date, x.transaction_id))
    return all_txs
