"""
Unified 3-Tier Asset Equivalence Engine.
Orchestrates Tier 1 (Exact CUSIP/Ticker) -> Tier 2 (Index Lookup) -> Tier 3 (N-PORT Cosine Similarity).
Conforms to Section 4 of the Technical Design Document.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from src.equivalence.tier1 import Tier1ExactMatcher
from src.equivalence.tier2 import Tier2IndexMatcher
from src.equivalence.tier3 import (
    Tier3CosineSimilarityMatcher,
    TIER3_AUTO_FLAG_THRESHOLD,
    TIER3_REVIEW_BAND_THRESHOLD,
)
from src.models.entities import AssetProfile


@dataclass
class EquivalenceResult:
    """Detailed outcome of an asset equivalence evaluation."""
    is_equivalent: bool
    tier: int
    similarity_score: float
    requires_manual_review: bool
    rationale: str


class EquivalenceEngine:
    """
    3-Tier Hierarchical Asset Equivalence Engine.
    Tier 1: CUSIP / Ticker exact match (Score 1.0)
    Tier 2: Index tracking lookup table (Score 1.0)
    Tier 3: Form N-PORT constituent cosine similarity (Score computed, with auto-flag and review bands)
    """

    def __init__(
        self,
        index_mapping_filepath: Optional[str] = None,
        auto_flag_threshold: float = TIER3_AUTO_FLAG_THRESHOLD,
        review_threshold: float = TIER3_REVIEW_BAND_THRESHOLD,
    ) -> None:
        self.tier1 = Tier1ExactMatcher()
        self.tier2 = Tier2IndexMatcher(index_mapping_filepath)
        self.tier3 = Tier3CosineSimilarityMatcher()
        self.auto_flag_threshold = auto_flag_threshold
        self.review_threshold = review_threshold
        self.profiles: Dict[str, AssetProfile] = {}

    def register_asset_profile(self, profile: AssetProfile) -> None:
        """Registers or caches an AssetProfile for Tier 3 evaluations."""
        self.profiles[profile.ticker.upper()] = profile
        if profile.cusip:
            self.profiles[profile.cusip.upper()] = profile

    def evaluate(
        self,
        ticker1: str,
        ticker2: str,
        cusip1: Optional[str] = None,
        cusip2: Optional[str] = None,
        profile1: Optional[AssetProfile] = None,
        profile2: Optional[AssetProfile] = None,
    ) -> EquivalenceResult:
        """
        Evaluates equivalence across Tier 1, Tier 2, and Tier 3 in strict priority order.
        """
        t1 = ticker1.strip().upper()
        t2 = ticker2.strip().upper()

        # 1. Tier 1: Exact CUSIP or Ticker match
        t1_match, t1_score, t1_rationale = self.tier1.match(t1, t2, cusip1, cusip2)
        if t1_match:
            return EquivalenceResult(
                is_equivalent=True,
                tier=1,
                similarity_score=t1_score,
                requires_manual_review=False,
                rationale=t1_rationale,
            )

        # 2. Tier 2: Index Tracking Equivalence Lookup Table
        t2_match, t2_score, t2_rationale = self.tier2.match(t1, t2)
        if t2_match:
            return EquivalenceResult(
                is_equivalent=True,
                tier=2,
                similarity_score=t2_score,
                requires_manual_review=False,
                rationale=t2_rationale,
            )

        # 3. Tier 3: Sparse N-PORT Cosine Similarity
        p1 = profile1 or self.profiles.get(t1) or (self.profiles.get(cusip1.upper()) if cusip1 else None)
        p2 = profile2 or self.profiles.get(t2) or (self.profiles.get(cusip2.upper()) if cusip2 else None)

        if p1 and p2:
            t3_match, t3_score, t3_review, t3_rationale = self.tier3.match(
                p1,
                p2,
                auto_flag_threshold=self.auto_flag_threshold,
                review_threshold=self.review_threshold,
            )
            if t3_match:
                return EquivalenceResult(
                    is_equivalent=True,
                    tier=3,
                    similarity_score=t3_score,
                    requires_manual_review=t3_review,
                    rationale=t3_rationale,
                )

        return EquivalenceResult(
            is_equivalent=False,
            tier=0,
            similarity_score=0.0,
            requires_manual_review=False,
            rationale=f"Securities {t1} and {t2} are not substantially identical across Tiers 1-3",
        )

    def are_equivalent(
        self,
        ticker1: str,
        ticker2: str,
        cusip1: Optional[str] = None,
        cusip2: Optional[str] = None,
        profile1: Optional[AssetProfile] = None,
        profile2: Optional[AssetProfile] = None,
    ) -> bool:
        """Convenience boolean check for equivalence."""
        res = self.evaluate(ticker1, ticker2, cusip1, cusip2, profile1, profile2)
        return res.is_equivalent

    def get_score(
        self,
        ticker1: str,
        ticker2: str,
        cusip1: Optional[str] = None,
        cusip2: Optional[str] = None,
        profile1: Optional[AssetProfile] = None,
        profile2: Optional[AssetProfile] = None,
    ) -> float:
        """Convenience method to retrieve the similarity score."""
        res = self.evaluate(ticker1, ticker2, cusip1, cusip2, profile1, profile2)
        return res.similarity_score


# Default singleton instance
DEFAULT_EQUIVALENCE_ENGINE = EquivalenceEngine()
