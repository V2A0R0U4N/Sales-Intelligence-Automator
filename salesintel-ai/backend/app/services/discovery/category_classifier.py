"""
Category Classifier — Classify discovered companies into industry categories.
"""
import re
import structlog
from typing import Optional

logger = structlog.get_logger("discovery.classifier")

# Category definitions with keyword patterns
CATEGORY_PATTERNS = {
    "technology": {
        "keywords": [
            "software", "saas", "tech", "it services", "cloud", "api",
            "data", "analytics", "artificial intelligence", "ai", "ml",
            "cybersecurity", "devops", "erp", "crm", "fintech", "iot",
            "automation", "platform", "infrastructure", "managed services",
            "it consulting", "system integration",
        ],
        "label": "Technology",
        "icon": "💻",
    },
    "digital_marketing": {
        "keywords": [
            "digital marketing", "seo", "ppc", "social media marketing",
            "content marketing", "web design", "web development",
            "digital agency", "creative agency", "branding agency",
            "marketing automation", "email marketing", "advertising",
            "performance marketing", "growth marketing",
        ],
        "label": "Digital / Marketing",
        "icon": "📱",
    },
    "design_cad": {
        "keywords": [
            "cad", "drafting", "design", "architectural", "engineering design",
            "3d modeling", "bim", "autocad", "cnc", "estimation",
            "blueprint", "millwork", "fabrication design", "industrial design",
            "product design", "mechanical design",
        ],
        "label": "Design / CAD",
        "icon": "🎨",
    },
    "manufacturing": {
        "keywords": [
            "manufacturing", "production", "factory", "industrial",
            "supply chain", "logistics", "warehouse", "assembly",
            "fabrication", "machining", "tooling", "quality control",
            "lean manufacturing", "oem",
        ],
        "label": "Manufacturing",
        "icon": "🏭",
    },
    "healthcare": {
        "keywords": [
            "healthcare", "health", "medical", "pharma", "biotech",
            "hospital", "clinic", "telemedicine", "healthtech",
            "diagnostics", "patient care", "clinical",
        ],
        "label": "Healthcare",
        "icon": "🏥",
    },
    "finance": {
        "keywords": [
            "finance", "banking", "insurance", "investment", "fintech",
            "accounting", "audit", "tax", "wealth management",
            "payment", "lending", "financial services",
        ],
        "label": "Finance",
        "icon": "💰",
    },
    "consulting": {
        "keywords": [
            "consulting", "advisory", "strategy", "management consulting",
            "business consulting", "hr consulting", "operations",
            "transformation", "process improvement",
        ],
        "label": "Consulting",
        "icon": "📊",
    },
    "education": {
        "keywords": [
            "education", "edtech", "training", "learning", "university",
            "school", "e-learning", "lms", "curriculum", "tutoring",
        ],
        "label": "Education",
        "icon": "🎓",
    },
    "retail": {
        "keywords": [
            "retail", "ecommerce", "e-commerce", "store", "shop",
            "marketplace", "consumer goods", "d2c", "direct to consumer",
        ],
        "label": "Retail / E-commerce",
        "icon": "🛒",
    },
}


class CategoryClassifier:
    """Classify companies into industry categories based on title + snippet."""

    def classify(self, title: str, snippet: str, url: str = "") -> str:
        """
        Classify a company into a category.
        Returns the category key (e.g., "technology", "digital_marketing").
        """
        combined = f"{title} {snippet} {url}".lower()

        scores = {}
        for category, config in CATEGORY_PATTERNS.items():
            score = sum(
                1 for kw in config["keywords"]
                if kw in combined
            )
            if score > 0:
                scores[category] = score

        if scores:
            return max(scores, key=scores.get)

        return "other"

    def classify_batch(self, companies: list[dict]) -> dict[str, list[dict]]:
        """
        Classify a batch of companies and group by category.
        Returns: {category: [companies]}
        """
        grouped = {}
        for company in companies:
            category = self.classify(
                title=company.get("title", ""),
                snippet=company.get("snippet", ""),
                url=company.get("link", ""),
            )
            if category not in grouped:
                grouped[category] = []
            grouped[category].append({
                **company,
                "category": category,
            })

        logger.info(
            "batch_classified",
            total=len(companies),
            categories={k: len(v) for k, v in grouped.items()},
        )
        return grouped

    @staticmethod
    def get_category_label(category_key: str) -> str:
        """Get the display label for a category."""
        config = CATEGORY_PATTERNS.get(category_key)
        if config:
            return config["label"]
        return "Other"

    @staticmethod
    def get_category_icon(category_key: str) -> str:
        """Get the emoji icon for a category."""
        config = CATEGORY_PATTERNS.get(category_key)
        if config:
            return config["icon"]
        return "🏢"

    @staticmethod
    def get_all_categories() -> list[dict]:
        """Return list of all available categories."""
        categories = [
            {"key": k, "label": v["label"], "icon": v["icon"]}
            for k, v in CATEGORY_PATTERNS.items()
        ]
        categories.append({"key": "other", "label": "Other", "icon": "🏢"})
        return categories
