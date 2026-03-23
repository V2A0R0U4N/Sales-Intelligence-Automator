"""
Tests for the scraping engine.
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock

# ─── Content Extractor Tests ───

class TestContentExtractor:
    """Test the content extraction logic."""

    def test_extract_basic_html(self):
        from app.services.scraping.content_extractor import ContentExtractor
        extractor = ContentExtractor()

        html = """
        <html>
        <head><title>Acme Corporation</title>
        <meta name="description" content="Leading software company">
        </head>
        <body>
        <h1>Welcome to Acme</h1>
        <h2>Our Services</h2>
        <p>We provide enterprise software solutions for manufacturing companies.
        Our platform helps streamline operations and improve efficiency.
        With over 200 employees across 5 offices, we serve clients globally.</p>
        <h2>Industries</h2>
        <p>Manufacturing, automotive, aerospace, and defense industries
        rely on our solutions for their critical operations.</p>
        </body></html>
        """

        result = extractor.extract(html, "https://acme.com")

        assert result["word_count"] > 20
        assert "Acme" in result["text"]
        assert result["meta"]["title"] == "Acme Corporation"
        assert "Leading software" in result["meta"]["description"]
        assert not result["flags"]["parked_domain"]

    def test_detect_parked_domain(self):
        from app.services.scraping.content_extractor import ContentExtractor
        extractor = ContentExtractor()

        html = """<html><body>
        <h1>This domain is for sale</h1>
        <p>Buy this domain at GoDaddy. Domain parked by the owner.</p>
        </body></html>"""

        result = extractor.extract(html, "https://example.com")
        assert result["flags"]["parked_domain"] is True

    def test_detect_login_wall(self):
        from app.services.scraping.content_extractor import ContentExtractor
        extractor = ContentExtractor()

        html = """<html><body>
        <h1>Login Required</h1>
        <p>Please log in to access this content. Authentication required.</p>
        </body></html>"""

        result = extractor.extract(html, "https://example.com")
        assert result["flags"]["login_required"] is True

    def test_extract_headings(self):
        from app.services.scraping.content_extractor import ContentExtractor
        extractor = ContentExtractor()

        html = """<html><body>
        <h1>Main Title</h1>
        <h2>Section One</h2>
        <p>Content here</p>
        <h2>Section Two</h2>
        <p>More content</p>
        <h3>Subsection</h3>
        </body></html>"""

        result = extractor.extract(html, "https://example.com")
        assert "Main Title" in result["headings"]
        assert "Section One" in result["headings"]


# ─── Category Filter Tests ───

class TestCategoryFilter:
    """Test the generic capability filter."""

    def test_filter_generic_services(self):
        from app.services.icp.category_filter import CategoryFilter
        f = CategoryFilter()

        services = [
            "Custom ERP Development",
            "Social Media Marketing",
            "Cloud Infrastructure",
            "SEO Services",
            "AI/ML Solutions",
        ]

        filtered = f.filter_services(services, "B2B SaaS for manufacturing")
        assert "Custom ERP Development" in filtered
        assert "Cloud Infrastructure" in filtered
        assert "AI/ML Solutions" in filtered
        assert "Social Media Marketing" not in filtered
        assert "SEO Services" not in filtered

    def test_keep_digital_for_digital_icp(self):
        from app.services.icp.category_filter import CategoryFilter
        f = CategoryFilter()

        services = ["SEO Services", "PPC Management", "Content Marketing"]
        filtered = f.filter_services(services, "digital marketing agency targeting small businesses")

        # Should keep ALL services since ICP targets digital companies
        assert len(filtered) == 3


# ─── ICP Scorer Tests ───

class TestICPScorer:
    """Test the multi-dimensional scoring formula."""

    def test_weights_sum_to_one(self):
        from app.services.icp.scorer import ICPScorer
        scorer = ICPScorer()
        assert abs(sum(scorer.WEIGHTS.values()) - 1.0) < 0.001

    def test_score_bounds(self):
        from app.services.icp.scorer import ICPScorer
        scorer = ICPScorer()

        # With zero vectors, should get minimum scores
        result = scorer.compute_score(
            icp_embedding=[0.0] * 3072,
            services_embedding=[0.0] * 3072,
            industries_embedding=[0.0] * 3072,
            company_profile={"primary_services": [], "industries_served": []},
            icp_description="test",
        )
        assert 0.0 <= result["final_score"] <= 1.0
        assert result["grade"] in ("A", "B", "C", "D")


# ─── Category Classifier Tests ───

class TestCategoryClassifier:
    """Test company category classification."""

    def test_classify_tech_company(self):
        from app.services.discovery.category_classifier import CategoryClassifier
        c = CategoryClassifier()

        result = c.classify(
            title="Acme Software Solutions",
            snippet="Leading SaaS platform for enterprise data analytics and cloud infrastructure",
        )
        assert result == "technology"

    def test_classify_design_company(self):
        from app.services.discovery.category_classifier import CategoryClassifier
        c = CategoryClassifier()

        result = c.classify(
            title="CAD Solutions Inc",
            snippet="Professional AutoCAD drafting and 3D modeling services for architecture",
        )
        assert result == "design_cad"

    def test_classify_unknown(self):
        from app.services.discovery.category_classifier import CategoryClassifier
        c = CategoryClassifier()

        result = c.classify(
            title="Random Company",
            snippet="We do random things that don't fit any category",
        )
        assert result == "other"

    def test_batch_classify(self):
        from app.services.discovery.category_classifier import CategoryClassifier
        c = CategoryClassifier()

        companies = [
            {"title": "TechCorp", "snippet": "Software development and cloud services", "link": ""},
            {"title": "DesignPro", "snippet": "CAD drafting and engineering design", "link": ""},
            {"title": "MarketMax", "snippet": "Digital marketing and SEO agency", "link": ""},
        ]

        grouped = c.classify_batch(companies)
        assert "technology" in grouped
        assert "design_cad" in grouped
        assert "digital_marketing" in grouped


# ─── Region Mapper Tests ───

class TestRegionMapper:
    """Test region expansion and query building."""

    def test_expand_shorthand(self):
        from app.services.discovery.region_mapper import RegionMapper
        mapper = RegionMapper()

        assert "India" in mapper.expand_region("india")
        assert "Gujarat" in mapper.expand_region("Gujarat")
        assert "San Francisco" in mapper.expand_region("silicon valley")

    def test_build_queries(self):
        from app.services.discovery.region_mapper import RegionMapper
        mapper = RegionMapper()

        queries = mapper.build_search_queries(
            icp_description="Manufacturing automation software companies",
            region="Gujarat",
            industry_tags=["manufacturing", "automation"],
        )
        assert len(queries) > 0
        assert any("Gujarat" in q or "India" in q for q in queries)
