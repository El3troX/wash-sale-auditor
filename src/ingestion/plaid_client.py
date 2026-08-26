"""
Plaid Sandbox Connector for Investment Transaction and Holding Ingestion.
Translates Plaid API investment responses into canonical Account and Transaction entities.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import plaid
from plaid.api import plaid_api
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
from plaid.model.investments_transactions_get_request_options import InvestmentsTransactionsGetRequestOptions
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest

from src.models.entities import Account, Transaction
from src.models.enums import AccountType, TransactionType
from src.corporate_actions.split_adjuster import SplitAdjuster, DEFAULT_SPLIT_ADJUSTER


class PlaidClient:
    """Connects to Plaid Sandbox/Production API and normalizes investment data."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        secret: Optional[str] = None,
        environment: str = "sandbox",
    ) -> None:
        self.client_id = client_id or "sandbox_client_id"
        self.secret = secret or "sandbox_secret"
        self.environment = environment

        # Map environment string to Plaid host
        if environment == "production":
            host = plaid.Environment.Production
        elif environment == "development":
            host = plaid.Environment.Development
        else:
            host = plaid.Environment.Sandbox

        configuration = plaid.Configuration(
            host=host,
            api_key={
                "clientId": self.client_id,
                "secret": self.secret,
            },
        )
        api_client = plaid.ApiClient(configuration)
        self.client = plaid_api.PlaidApi(api_client)

    @classmethod
    def _map_account_subtype(cls, subtype: Optional[str]) -> AccountType:
        """Maps Plaid account subtype to our canonical AccountType."""
        if not subtype:
            return AccountType.TAXABLE
        s = subtype.lower()
        if "roth" in s:
            return AccountType.ROTH_IRA
        elif "ira" in s or "401k" in s or "retirement" in s:
            return AccountType.TRADITIONAL_IRA
        elif "robo" in s or "managed" in s or "betterment" in s or "wealthfront" in s:
            return AccountType.ROBO_MANAGED
        return AccountType.TAXABLE

    @classmethod
    def parse_plaid_payload(
        cls,
        payload: Dict[str, Any],
        broker_override: Optional[str] = None,
        split_adjuster: Optional[SplitAdjuster] = None,
        auto_split_adjust: bool = True,
    ) -> Tuple[List[Account], List[Transaction]]:
        """
        Transforms a raw Plaid /investments/transactions/get or /investments/holdings/get
        response payload dictionary into canonical Account and Transaction entities.
        Automatically normalizes transactions for corporate stock splits (Section 3.2).
        """
        # 1. Parse accounts
        accounts_map: Dict[str, Account] = {}
        for acc_dict in payload.get("accounts", []):
            acc_id = acc_dict.get("account_id", "unknown_acc")
            acc_name = acc_dict.get("name", "Brokerage Account")
            broker = broker_override or acc_dict.get("institution_name") or acc_name.split()[0]
            subtype = acc_dict.get("subtype")
            acc_type = cls._map_account_subtype(subtype)

            accounts_map[acc_id] = Account(
                account_id=acc_id,
                broker_name=broker,
                account_type=acc_type,
            )

        # 2. Build security reference lookup (security_id -> (ticker, cusip))
        sec_map: Dict[str, Tuple[str, Optional[str]]] = {}
        for sec in payload.get("securities", []):
            sec_id = sec.get("security_id")
            ticker = sec.get("ticker_symbol") or sec.get("name") or "UNKNOWN"
            cusip = sec.get("cusip")
            if cusip and len(str(cusip).strip()) != 9:
                cusip = None
            if sec_id:
                sec_map[sec_id] = (str(ticker).upper(), cusip)

        # 3. Parse investment transactions
        transactions: List[Transaction] = []
        for tx_dict in payload.get("investment_transactions", []):
            raw_type = str(tx_dict.get("type", "")).lower()
            raw_subtype = str(tx_dict.get("subtype", "")).lower()

            if raw_type in ("buy",) or "buy" in raw_subtype:
                tx_type = TransactionType.BUY
            elif raw_type in ("sell",) or "sell" in raw_subtype:
                tx_type = TransactionType.SELL
            else:
                # Non-trade cash/fee events ignored
                continue

            sec_id = tx_dict.get("security_id")
            ticker, cusip = sec_map.get(sec_id, ("UNKNOWN", None))
            if ticker == "UNKNOWN" and tx_dict.get("name"):
                ticker = str(tx_dict["name"]).split()[0].upper()

            tx_date_raw = tx_dict.get("date")
            if isinstance(tx_date_raw, date):
                t_date = tx_date_raw
            elif isinstance(tx_date_raw, str):
                t_date = datetime.strptime(tx_date_raw[:10], "%Y-%m-%d").date()
            else:
                continue

            qty = abs(float(tx_dict.get("quantity") or 0.0))
            price = abs(float(tx_dict.get("price") or 0.0))
            if price == 0.0 and qty > 0 and tx_dict.get("amount"):
                price = abs(float(tx_dict["amount"])) / qty

            if qty <= 0:
                continue

            acc_id = tx_dict.get("account_id", "default_account")
            # Ensure account exists
            if acc_id not in accounts_map:
                accounts_map[acc_id] = Account(
                    account_id=acc_id,
                    broker_name=broker_override or "Plaid Broker",
                    account_type=AccountType.TAXABLE,
                )

            transactions.append(Transaction(
                transaction_id=str(tx_dict.get("investment_transaction_id", f"PLD-{len(transactions)}")),
                account_id=acc_id,
                ticker=ticker,
                cusip=cusip,
                transaction_type=tx_type,
                quantity=qty,
                price_per_share=price,
                trade_date=t_date,
                settlement_date=t_date,
                realized_gain_loss=None,
                unmatched_quantity=qty,
            ))

        transactions.sort(key=lambda x: (x.trade_date, x.transaction_id))

        if auto_split_adjust:
            adjuster = split_adjuster if split_adjuster is not None else DEFAULT_SPLIT_ADJUSTER
            transactions = adjuster.normalize_transactions(transactions)

        return list(accounts_map.values()), transactions

    def fetch_sandbox_transactions(
        self,
        access_token: str,
        start_date: date,
        end_date: date,
        account_ids: Optional[List[str]] = None,
        split_adjuster: Optional[SplitAdjuster] = None,
        auto_split_adjust: bool = True,
    ) -> Tuple[List[Account], List[Transaction]]:
        """
        Fetches live transactions from Plaid Sandbox Investments API.
        """
        options = InvestmentsTransactionsGetRequestOptions()
        if account_ids:
            options.account_ids = account_ids

        request = InvestmentsTransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=options,
        )

        response = self.client.investments_transactions_get(request)
        return self.parse_plaid_payload(
            response.to_dict(),
            split_adjuster=split_adjuster,
            auto_split_adjust=auto_split_adjust,
        )
