"""
Category Filter — Exclude generic capabilities from ICP scoring.
"""
import structlog

logger = structlog.get_logger("icp.filter")

# Generic capabilities that ALL companies have — should NOT count toward ICP score
GENERIC_CAPABILITIES = {
    "website", "social media", "digital presence", "online marketing",
    "seo", "content marketing", "email marketing", "mobile app",
    "facebook", "instagram", "twitter", "linkedin", "youtube",
    "google ads", "ppc", "digital advertising", "web presence",
    "online presence", "branding", "brand identity", "logo design",
    "business cards", "email", "newsletter", "blog",
}

# ICP keywords that indicate the ICP explicitly targets digital companies
DIGITAL_ICP_KEYWORDS = {
    "digital marketing agency", "web development", "seo agency",
    "social media agency", "digital agency", "marketing agency",
    "web design agency", "advertising agency", "performance marketing",
    "content agency", "creative agency",
}


class CategoryFilter:
    """Filter generic capabilities from company profiles before scoring."""

    def should_include_digital_signals(self, icp_description: str) -> bool:
        """
        Check if the ICP explicitly targets digital/marketing companies.
        If yes, digital signals SHOULD count toward the score.
        """
        icp_lower = icp_description.lower()
        return any(keyword in icp_lower for keyword in DIGITAL_ICP_KEYWORDS)

    def filter_services(
        self,
        services: list[str],
        icp_description: str,
    ) -> list[str]:
        """
        Remove generic capabilities from a service list.
        Exception: If ICP targets digital companies, keep digital services.
        """
        if self.should_include_digital_signals(icp_description):
            logger.debug("digital_signals_enabled", reason="ICP targets digital companies")
            return services

        filtered = []
        for service in services:
            service_lower = service.lower().strip()
            is_generic = any(
                generic in service_lower
                for generic in GENERIC_CAPABILITIES
            )
            if not is_generic:
                filtered.append(service)
            else:
                logger.debug("filtered_generic_capability", service=service)

        return filtered

    def filter_profile(
        self,
        profile: dict,
        icp_description: str,
    ) -> dict:
        """
        Filter a full company profile — remove generics from primary/secondary services.
        Returns a new dict with filtered service lists.
        """
        filtered = profile.copy()

        filtered["primary_services"] = self.filter_services(
            profile.get("primary_services", []), icp_description
        )
        filtered["secondary_services"] = self.filter_services(
            profile.get("secondary_services", []), icp_description
        )

        return filtered
