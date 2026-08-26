"""
Tier 2 Asset Equivalence: Index-Tracking Equivalence Lookup.
Conforms to Section 4.2 of the Technical Design Document.
Loads curated benchmark index families from an extensible JSON data file.
"""

import json
import os
from typing import Dict, List, Optional, Tuple


class Tier2IndexMatcher:
    """
    Evaluates Tier 2 equivalence: ETFs tracking identical underlying benchmark indices.
    For example: VOO, IVV, SPY, SPLG all track the S&P 500 Index.
    """

    def __init__(self, mapping_filepath: Optional[str] = None) -> None:
        self.ticker_to_index: Dict[str, str] = {}
        self.index_to_tickers: Dict[str, List[str]] = {}

        if mapping_filepath is None:
            # Default to etf_index_mappings.json in data/
            base_dir = os.path.dirname(__file__)
            mapping_filepath = os.path.join(base_dir, "data", "etf_index_mappings.json")

        self.load_mappings(mapping_filepath)

    def load_mappings(self, filepath: str) -> None:
        """Loads index mapping families from JSON file."""
        if not os.path.exists(filepath):
            return

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        families = data.get("index_families", {})
        for index_name, tickers in families.items():
            self.index_to_tickers[index_name] = [t.upper() for t in tickers]
            for ticker in tickers:
                self.ticker_to_index[ticker.upper()] = index_name

    def register_index_family(self, index_name: str, tickers: List[str]) -> None:
        """Dynamically registers or updates an index tracking family."""
        clean_tickers = [t.upper() for t in tickers]
        self.index_to_tickers[index_name] = clean_tickers
        for t in clean_tickers:
            self.ticker_to_index[t] = index_name

    def match(self, ticker1: str, ticker2: str) -> Tuple[bool, float, str]:
        """
        Checks if both tickers map to the same underlying benchmark index.
        Returns: (is_match: bool, similarity_score: float, rationale: str)
        """
        t1 = ticker1.strip().upper()
        t2 = ticker2.strip().upper()

        idx1 = self.ticker_to_index.get(t1)
        idx2 = self.ticker_to_index.get(t2)

        if idx1 and idx2 and idx1 == idx2:
            return (
                True,
                1.0,
                f"Tier 2 Index Tracking Equivalence: Both {t1} and {t2} track the '{idx1}' benchmark index",
            )

        return (False, 0.0, "No Tier 2 index equivalence match")
