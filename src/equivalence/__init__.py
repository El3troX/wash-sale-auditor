"""
Asset Equivalence Engine (Tiers 1-3).
"""

from src.equivalence.tier1 import Tier1ExactMatcher
from src.equivalence.tier2 import Tier2IndexMatcher
from src.equivalence.tier3 import (
    Tier3CosineSimilarityMatcher,
    TIER3_AUTO_FLAG_THRESHOLD,
    TIER3_REVIEW_BAND_THRESHOLD,
)
from src.equivalence.engine import (
    EquivalenceEngine,
    EquivalenceResult,
    DEFAULT_EQUIVALENCE_ENGINE,
)

__all__ = [
    "Tier1ExactMatcher",
    "Tier2IndexMatcher",
    "Tier3CosineSimilarityMatcher",
    "TIER3_AUTO_FLAG_THRESHOLD",
    "TIER3_REVIEW_BAND_THRESHOLD",
    "EquivalenceEngine",
    "EquivalenceResult",
    "DEFAULT_EQUIVALENCE_ENGINE",
]
