"""
Enumeration definitions for account and transaction classification.
"""

from enum import Enum


class AccountType(Enum):
    """Tax classification of brokerage accounts under IRC §1091 & Rev. Rul. 2008-5."""
    TAXABLE = "taxable"
    ROTH_IRA = "roth_ira"
    TRADITIONAL_IRA = "traditional_ira"
    ROBO_MANAGED = "robo_managed"

    @property
    def is_tax_advantaged(self) -> bool:
        """Returns True if the account is an IRA subject to Rev. Rul. 2008-5 permanent disallowance."""
        return self in (AccountType.ROTH_IRA, AccountType.TRADITIONAL_IRA)


class TransactionType(Enum):
    """Type of transaction leg."""
    BUY = "buy"
    SELL = "sell"
