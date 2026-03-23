"""
Region Mapper — Map user region input to effective search queries.
"""
import structlog

logger = structlog.get_logger("discovery.region")

# Common region expansions
REGION_EXPANSIONS = {
    "usa": "United States",
    "us": "United States",
    "uk": "United Kingdom",
    "uae": "United Arab Emirates",
    "india": "India",
    "gujarat": "Gujarat, India",
    "ahmedabad": "Ahmedabad, Gujarat, India",
    "mumbai": "Mumbai, Maharashtra, India",
    "bangalore": "Bangalore, Karnataka, India",
    "delhi": "Delhi, India",
    "pune": "Pune, Maharashtra, India",
    "hyderabad": "Hyderabad, Telangana, India",
    "chennai": "Chennai, Tamil Nadu, India",
    "silicon valley": "San Francisco Bay Area, California, USA",
    "bay area": "San Francisco Bay Area, California, USA",
    "nyc": "New York City, New York, USA",
    "la": "Los Angeles, California, USA",
}


class RegionMapper:
    """Map user region input to structured search queries."""

    def expand_region(self, region: str) -> str:
        """Expand shorthand region names to full form."""
        region_lower = region.strip().lower()
        expanded = REGION_EXPANSIONS.get(region_lower, region)
        logger.debug("region_expanded", input=region, output=expanded)
        return expanded

    def build_search_queries(self, icp_description: str, region: str, industry_tags: list[str] = None) -> list[str]:
        """
        Build search queries from ICP + region.
        Returns multiple query variations for better coverage.
        """
        expanded_region = self.expand_region(region)
        queries = []

        # Industry-specific queries
        if industry_tags:
            for tag in industry_tags[:3]:
                queries.append(f"{tag} companies in {expanded_region}")

        # ICP keyword extraction
        icp_keywords = self._extract_key_phrases(icp_description)
        for phrase in icp_keywords[:3]:
            queries.append(f"{phrase} companies in {expanded_region}")

        # Generic fallback
        if not queries:
            queries.append(f"top companies in {expanded_region}")

        logger.info("search_queries_built", region=expanded_region, queries=queries)
        return queries

    def _extract_key_phrases(self, text: str) -> list[str]:
        """Extract key industry phrases from ICP description."""
        # Simple keyword extraction — could be enhanced with NLP
        import re

        # Remove common stop words and get meaningful phrases
        stop_words = {
            "we", "our", "help", "looking", "for", "companies", "that",
            "are", "the", "and", "or", "in", "to", "with", "a", "an",
            "is", "it", "of", "who", "which", "they", "their", "need",
        }

        words = re.findall(r"\b\w+\b", text.lower())
        meaningful = [w for w in words if w not in stop_words and len(w) > 3]

        # Take top unique words as key phrases
        seen = set()
        phrases = []
        for w in meaningful:
            if w not in seen:
                seen.add(w)
                phrases.append(w)

        return phrases[:5]
