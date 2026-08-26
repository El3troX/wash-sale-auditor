"""
Tier 1 Asset Equivalence: CUSIP Exact Match & Normalized Ticker Match.
Conforms to Section 4.1 of the Technical Design Document.
"""

from typing import Optional, Tuple


class Tier1ExactMatcher:
    """
    Evaluates Tier 1 exact security equivalence.
    CUSIP match takes absolute precedence. Ticker match is fallback when CUSIP is unavailable.
    Returns: (is_match: bool, similarity_score: float, rationale: str)
    """

    @staticmethod
    def match(
        ticker1: str,
        ticker2: str,
        cusip1: Optional[str] = None,
        cusip2: Optional[str] = None,
    ) -> Tuple[bool, float, str]:
        # 1. CUSIP comparison (Primary Identifier)
        if cusip1 and cusip2 and len(cusip1.strip()) == 9 and len(cusip2.strip()) == 9:
            if cusip1.strip().upper() == cusip2.strip().upper():
                return (
                    True,
                    1.0,
                    f"Tier 1 Exact CUSIP match ({cusip1.strip().upper()})",
                )
            # If both have valid non-matching CUSIPs, they are distinct securities
            return (False, 0.0, "Tier 1 CUSIP mismatch")

        # 2. Ticker comparison (Fallback)
        t1_norm = ticker1.strip().upper()
        t2_norm = ticker2.strip().upper()
        if t1_norm == t2_norm and t1_norm != "" and t1_norm != "UNKNOWN":
            return (
                True,
                1.0,
                f"Tier 1 Exact Ticker match ({t1_norm})",
            )

        return (False, 0.0, "No Tier 1 exact match")
