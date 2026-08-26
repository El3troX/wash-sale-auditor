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


def build_default_accounts() -> Dict[str, Account]:
    """Builds standard multi-broker portfolio across taxable and retirement accounts."""
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


def build_tc01_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """TC-01: IRS Pub 550 Baseline."""
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
            trade_date=date(2024, 2, 15),
            settlement_date=date(2024, 2, 17),
        ),
    ]


def build_tc02_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """TC-02: 30-Day Lookback Window."""
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
            trade_date=date(2024, 3, 1),
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


def build_tc03_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """TC-03: Cross-Broker ETF Swap."""
    fid = multi_accounts["fidelity_taxable"]
    schw = multi_accounts["schwab_taxable"]
    return [
        Transaction(
            transaction_id="TC03-BUY-VOO-ORIG",
            account_id=fid.account_id,
            ticker="VOO",
            cusip="922908363",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=450.0,
            trade_date=date(2024, 2, 1),
            settlement_date=date(2024, 2, 3),
        ),
        Transaction(
            transaction_id="TC03-SELL-VOO",
            account_id=fid.account_id,
            ticker="VOO",
            cusip="922908363",
            transaction_type=TransactionType.SELL,
            quantity=100.0,
            price_per_share=420.0,
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
            price_per_share=422.0,
            trade_date=date(2024, 4, 15),
            settlement_date=date(2024, 4, 17),
        ),
    ]


def build_tc04_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """TC-04: IRA Repurchase (Rev. Rul. 2008-5)."""
    fid = multi_accounts["fidelity_taxable"]
    roth = multi_accounts["vanguard_roth"]
    return [
        Transaction(
            transaction_id="TC04-BUY-TAXABLE-ORIG",
            account_id=fid.account_id,
            ticker="SPY",
            cusip="78462F103",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=540.0,
            trade_date=date(2024, 3, 1),
            settlement_date=date(2024, 3, 3),
        ),
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
            account_id=roth.account_id,
            ticker="SPY",
            cusip="78462F103",
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=505.0,
            trade_date=date(2024, 5, 11),
            settlement_date=date(2024, 5, 13),
        ),
    ]


def build_tc05_chained_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """TC-05 Sub-case A: Chained Wash Sales."""
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


def build_tc05_competing_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """TC-05 Sub-case B: Competing Loss Sales."""
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


def build_tc06_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """TC-06: Same-Day Same-Lot False Positive Filter."""
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
            transaction_id="TC06-SELL-SAME-LOT",
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


def build_full_portfolio_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    """Builds comprehensive multi-account portfolio merging all TC scenarios."""
    all_txs = (
        build_tc01_dataset(multi_accounts)
        + build_tc02_dataset(multi_accounts)
        + build_tc03_dataset(multi_accounts)
        + build_tc04_dataset(multi_accounts)
        + build_tc05_chained_dataset(multi_accounts)
        + build_tc05_competing_dataset(multi_accounts)
        + build_tc06_dataset(multi_accounts)
    )
    all_txs.sort(key=lambda x: (x.trade_date, x.transaction_id))
    return all_txs


# ================= Pytest Fixtures =================

@pytest.fixture
def multi_accounts() -> Dict[str, Account]:
    return build_default_accounts()


@pytest.fixture
def tc01_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    return build_tc01_dataset(multi_accounts)


@pytest.fixture
def tc02_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    return build_tc02_dataset(multi_accounts)


@pytest.fixture
def tc03_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    return build_tc03_dataset(multi_accounts)


@pytest.fixture
def tc04_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    return build_tc04_dataset(multi_accounts)


@pytest.fixture
def tc05_chained_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    return build_tc05_chained_dataset(multi_accounts)


@pytest.fixture
def tc05_competing_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    return build_tc05_competing_dataset(multi_accounts)


@pytest.fixture
def tc06_dataset(multi_accounts: Dict[str, Account]) -> List[Transaction]:
    return build_tc06_dataset(multi_accounts)


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
