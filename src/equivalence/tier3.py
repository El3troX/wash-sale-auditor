"""
Tier 3 Asset Equivalence: Sparse N-PORT Cosine Similarity Engine.
Conforms to Section 4.3 of the Technical Design Document.

Computes cosine similarity over normalized fund holdings vectors extracted from SEC Form N-PORT filings:
S(u, v) = (u . v) / (||u|| * ||v||)

MODELING CHOICE NOTE (IRC §1091 / TDD Section 4.3):
The IRS statute does not define a mathematical threshold for "substantially identical" securities.
The numerical thresholds below (0.95 auto-flag, 0.80-0.95 review band) are deterministic engineering
heuristics selected based on empirical index overlap and mutual fund/ETF correlation.
They are NOT settled statutory tax law and must be presented as modeling choices in all audit trails.
"""

import math
from typing import Dict, Optional, Tuple

from src.models.entities import AssetProfile


# Engineering heuristic thresholds defined in TDD Section 4.3
TIER3_AUTO_FLAG_THRESHOLD: float = 0.95  # Score >= 0.95: Auto-flag as wash sale
TIER3_REVIEW_BAND_THRESHOLD: float = 0.80  # 0.80 <= Score < 0.95: Flag for manual CPA review only (NO auto-disallowance)


class Tier3CosineSimilarityMatcher:
    """
    Evaluates Tier 3 asset equivalence using sparse cosine similarity across holdings vectors.
    """

    @staticmethod
    def compute_cosine_similarity(
        vector_a: Dict[str, float],
        vector_b: Dict[str, float],
    ) -> float:
        """
        Calculates cosine similarity between two sparse constituent weight vectors.
        Vectors map security identifiers (CUSIP or Ticker) -> float weight.
        """
        if not vector_a or not vector_b:
            return 0.0

        # Dot product over shared keys
        dot_product = 0.0
        # Iterate over smaller dictionary for efficiency
        smaller, larger = (vector_a, vector_b) if len(vector_a) <= len(vector_b) else (vector_b, vector_a)
        for key, val in smaller.items():
            if key in larger:
                dot_product += val * larger[key]

        # Norms
        norm_a = math.sqrt(sum(v * v for v in vector_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vector_b.values()))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        similarity = dot_product / (norm_a * norm_b)
        # Numerical guard: clamp between 0.0 and 1.0
        return max(0.0, min(1.0, float(similarity)))

    @classmethod
    def match(
        cls,
        profile_a: Optional[AssetProfile],
        profile_b: Optional[AssetProfile],
        auto_flag_threshold: float = TIER3_AUTO_FLAG_THRESHOLD,
        review_threshold: float = TIER3_REVIEW_BAND_THRESHOLD,
    ) -> Tuple[bool, float, bool, str]:
        """
        Evaluates Tier 3 similarity between two AssetProfiles.
        Returns: (is_candidate: bool, similarity_score: float, requires_manual_review: bool, rationale: str)

        Crucial architectural rule:
        - If score >= auto_flag_threshold (0.95): is_candidate=True, requires_manual_review=False
        - If review_threshold <= score < auto_flag_threshold (0.80 - 0.95): is_candidate=True, requires_manual_review=True
          (Signals a potential wash sale for review, but MUST NOT be automatically disallowed by default)
        - If score < review_threshold: is_candidate=False, requires_manual_review=False
        """
        if profile_a is None or profile_b is None:
            return (False, 0.0, False, "Tier 3: Missing AssetProfile for comparison")

        if not profile_a.holdings_vector or not profile_b.holdings_vector:
            return (False, 0.0, False, "Tier 3: Empty holdings vector in AssetProfile")

        score = cls.compute_cosine_similarity(profile_a.holdings_vector, profile_b.holdings_vector)

        if score >= auto_flag_threshold:
            return (
                True,
                score,
                False,
                f"Tier 3 Cosine Similarity ({score:.4f} >= {auto_flag_threshold}): Substantially identical constituent overlap",
            )
        elif score >= review_threshold:
            # Modeling choice note: Mid-band matches require manual human/CPA review and are NOT auto-disallowed
            return (
                True,
                score,
                True,
                f"Tier 3 Review Band ({score:.4f}): Constituent overlap in review band [{review_threshold}, {auto_flag_threshold}). Manual review required; no automatic disallowance.",
            )

        return (
            False,
            score,
            False,
            f"Tier 3 Insufficient Similarity ({score:.4f} < {review_threshold}): Funds are not substantially identical",
        )
