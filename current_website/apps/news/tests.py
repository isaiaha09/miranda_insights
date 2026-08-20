import tempfile
from datetime import datetime, time, timezone as datetime_timezone
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.templatetags.static import static

from .admin import HasAccountListFilter, NewsletterCampaignAdmin, NewsletterSubscriberAdmin
from .newsletter_blocks import normalize_blocks
from .models import NewsletterBlockTemplate, NewsletterCampaign, NewsletterImageAsset, NewsletterSendLog, NewsletterSubscriber
from .services import process_due_automated_campaigns, send_campaign


TEMP_MEDIA_ROOT = tempfile.mkdtemp()
User = get_user_model()


class PublicPageTests(TestCase):
	DISCOVERY_URL = "https://calendar.notion.so/meet/mirandalegacy/discovery"

	def _shared_navigation_blocks(self, response):
		content = response.content.decode()
		primary_start = content.index('<div class="nav-center" id="nav-menu">')
		primary_end = content.index("</div>", primary_start)
		actions_start = content.index('<div class="nav-right">')
		actions_end = content.index("</div>", actions_start)
		footer_start = content.index('<footer class="site-footer">')
		footer_end = content.index("</footer>", footer_start)
		return (
			content[primary_start:primary_end],
			content[actions_start:actions_end],
			content[footer_start:footer_end],
		)

	def test_homepage_renders_redesign_sections_in_order(self):
		response = self.client.get(reverse("home"))

		self.assertEqual(response.status_code, 200)
		content = response.content.decode()
		section_headings = [
			"Operational Intelligence for People, Organizations, and Communities",
			"Our Five Pillars",
			"Who We Work With",
			"Why Miranda Insights",
			"Let&rsquo;s Build Something Better Together",
			"Subscribe to Miranda Insights Newsletter",
		]
		section_positions = [content.index(heading) for heading in section_headings]

		self.assertEqual(section_positions, sorted(section_positions))
		for pillar in (
			"Personal Development",
			"Professional Development",
			"Physical Development",
			"Academic Development",
			"Operational Development",
		):
			self.assertContains(response, pillar)
		self.assertContains(response, "The right support should fit the goal.")
		self.assertContains(response, "Building stronger habits, organization, accountability, confidence")
		self.assertContains(response, "Improving the systems, processes, technology, data, documentation")
		self.assertContains(response, "Students &amp; Athletes", html=False)
		self.assertContains(response, "Professional &amp; Transparent", html=False)
		self.assertNotContains(response, ">Operational Services<", html=False)
		self.assertNotContains(response, ">Digital Presence<", html=False)
		self.assertNotContains(response, ">Intelligence Application Development<", html=False)
		self.assertNotContains(response, ">Operational Partnership<", html=False)

	def test_homepage_uses_existing_routes_and_approved_discovery_link(self):
		response = self.client.get(reverse("home"))

		self.assertContains(response, f'href="{self.DISCOVERY_URL}"', count=3, html=False)
		self.assertContains(response, f'href="{reverse("services")}"', html=False)
		self.assertContains(response, f'href="{reverse("contact_support")}"', html=False)
		self.assertContains(response, "Download Miranda Insights Mobile on the App Store")

	def test_homepage_preserves_newsletter_hooks_and_removes_retired_sections(self):
		response = self.client.get(reverse("home"))

		self.assertContains(response, 'id="newsletter-signup"', html=False)
		self.assertContains(response, "data-subscribe-form", html=False)
		self.assertContains(response, "data-subscribe-messages", html=False)
		self.assertContains(response, f'action="{reverse("newsletter_subscribe")}"', html=False)
		self.assertNotContains(response, "miranda-insights.circlecal.app", html=False)
		self.assertNotContains(response, ">Our Process<", html=False)
		self.assertNotContains(response, ">Client Access<", html=False)
		self.assertNotContains(response, ">What We Do<", html=False)

	def test_shared_primary_navigation_uses_current_public_destinations(self):
		expected_links = [
			f'href="{reverse("about")}"',
			f'href="{reverse("operational_partnership")}"',
			f'href="{reverse("services")}"',
			f'href="{reverse("individual_services")}"',
			f'href="{reverse("contact_support")}"',
			f'href="{reverse("dashboard")}"',
		]

		for route_name in (
			"home",
			"about",
			"operational_partnership",
			"services",
			"individual_services",
			"contact_support",
			"login",
			"signup",
		):
			with self.subTest(route_name=route_name):
				response = self.client.get(reverse(route_name))
				primary_nav, navigation_actions, _footer = self._shared_navigation_blocks(response)
				link_positions = [primary_nav.index(link) for link in expected_links]

				self.assertEqual(link_positions, sorted(link_positions))
				self.assertNotIn(">Products</a>", primary_nav)
				self.assertNotIn(">FAQ</a>", primary_nav)
				self.assertNotIn(">Client Portal</a>", navigation_actions)

	def test_shared_navigation_preserves_anonymous_portal_and_signup_behavior(self):
		response = self.client.get(reverse("home"))
		primary_nav, navigation_actions, _footer = self._shared_navigation_blocks(response)

		self.assertIn(f'<a href="{reverse("dashboard")}">Client Portal</a>', primary_nav)
		self.assertIn(f'<a class="signup" href="{reverse("signup")}">Sign Up</a>', navigation_actions)
		self.assertNotIn(">Logout</button>", navigation_actions)

		dashboard_response = self.client.get(reverse("dashboard"))
		self.assertRedirects(
			dashboard_response,
			f'{reverse("login")}?next={reverse("dashboard")}',
			fetch_redirect_response=False,
		)

	def test_shared_navigation_preserves_authenticated_logout_behavior(self):
		user = User.objects.create_user(username="navclient", email="navclient@example.com", password="test-pass-123")
		self.client.force_login(user)

		response = self.client.get(reverse("home"))
		primary_nav, navigation_actions, _footer = self._shared_navigation_blocks(response)

		self.assertIn(f'<a href="{reverse("dashboard")}">Client Portal</a>', primary_nav)
		self.assertIn(f'<form class="auth-action-form" action="{reverse("logout")}" method="post">', navigation_actions)
		self.assertIn('name="csrfmiddlewaretoken"', navigation_actions)
		self.assertIn(">Logout</button>", navigation_actions)
		self.assertNotIn(">Sign Up</a>", navigation_actions)

	def test_shared_navigation_marks_the_current_public_page(self):
		for route_name, label in (
			("about", "About"),
			("operational_partnership", "Partnerships"),
			("services", "Services"),
			("individual_services", "Individual Support"),
			("contact_support", "Resources"),
		):
			with self.subTest(route_name=route_name):
				response = self.client.get(reverse(route_name))
				primary_nav, _navigation_actions, _footer = self._shared_navigation_blocks(response)

				self.assertIn(
					f'<a href="{reverse(route_name)}" aria-current="page">{label}</a>',
					primary_nav,
				)
				self.assertEqual(primary_nav.count('aria-current="page"'), 1)

	def test_shared_footer_uses_current_architecture(self):
		response = self.client.get(reverse("home"))
		primary_nav, _navigation_actions, footer = self._shared_navigation_blocks(response)

		self.assertNotIn(f'href="{reverse("products")}"', primary_nav)
		self.assertNotIn(f'href="{reverse("faq")}"', primary_nav)
		self.assertNotIn(f'href="{reverse("products")}"', footer)
		self.assertNotIn(f'href="{reverse("faq")}"', footer)
		for heading in ("Explore", "Client", "Support / Contact", "Legal"):
			self.assertIn(f">{heading}</h2>", footer)
		for route_name in (
			"about",
			"operational_partnership",
			"services",
			"individual_services",
			"contact_support",
			"dashboard",
			"privacy",
			"terms",
		):
			self.assertIn(f'href="{reverse(route_name)}"', footer)
		self.assertIn(f'href="{self.DISCOVERY_URL}"', footer)
		self.assertIn('target="_blank" rel="noopener noreferrer"', footer)
		self.assertIn("Miranda Insights LLC. All rights reserved.", footer)
		self.assertEqual(self.client.get(reverse("products")).status_code, 200)
		self.assertEqual(self.client.get(reverse("faq")).status_code, 200)

	def test_shared_branding_uses_current_logo_and_favicon(self):
		response = self.client.get(reverse("home"))

		self.assertContains(response, f'href="{static("pwa/icon-32.png")}"', html=False)
		self.assertContains(response, f'src="{static("img/miranda-logo.png")}"', html=False)
		self.assertContains(response, 'alt="" width="40" height="40"', html=False)
		self.assertNotContains(response, f'href="{static("favicon.svg")}"', html=False)

	def test_shared_mobile_menu_hooks_remain_available(self):
		response = self.client.get(reverse("home"))

		self.assertContains(response, 'id="nav-menu"', html=False)
		self.assertContains(response, 'id="nav-hamburger"', html=False)
		self.assertContains(response, 'aria-controls="nav-menu"', html=False)
		self.assertContains(response, 'aria-expanded="false"', html=False)
		self.assertContains(response, 'id="nav-overlay"', html=False)

	def test_about_page_renders_approved_sections_in_order(self):
		response = self.client.get(reverse("about"))

		self.assertEqual(response.status_code, 200)
		content = response.content.decode()
		section_headings = [
			"About Miranda Insights",
			"Our Story",
			"Mission, Vision &amp; Core Values",
			"Meet the Founder",
			"How We Work",
			"Let’s Start the Conversation",
		]
		section_positions = [content.index(heading) for heading in section_headings]

		self.assertEqual(section_positions, sorted(section_positions))
		self.assertContains(
			response,
			"Miranda Insights is a purpose-driven Operational Intelligence and Systems Development firm focused on creating practical, sustainable solutions that help individuals and organizations learn, build, and grow.",
		)

	def test_about_page_contains_approved_content_and_founder_profile(self):
		response = self.client.get(reverse("about"))

		for value in (
			"Integrity",
			"Service",
			"Continuous Improvement",
			"Collaboration",
			"Practical Innovation",
			"Stewardship",
		):
			self.assertContains(response, value)
		for step in ("Discover", "Design", "Develop", "Grow"):
			self.assertContains(response, step)
		for credential in (
			"B.A. in Psychology",
			"B.S. in Mathematics (Applied Mathematics &amp; Statistics)",
			"Founder of Miranda Insights",
			"Operational Intelligence &amp; Systems Development",
			"Research &amp; Program Evaluation",
			"Digital Systems &amp; Process Improvement",
		):
			self.assertContains(response, credential)
		self.assertContains(response, static("img/kyle-adam-miranda-founder.jpg"))
		self.assertContains(response, 'alt="Kyle-Adam Miranda, founder of Miranda Insights"', html=False)

	def test_about_page_uses_approved_ctas_and_removes_retired_content(self):
		response = self.client.get(reverse("about"))

		self.assertContains(response, f'href="{self.DISCOVERY_URL}"', count=2, html=False)
		self.assertContains(response, 'target="_blank"', html=False)
		self.assertContains(response, 'rel="noopener noreferrer"', html=False)
		self.assertContains(response, f'href="{reverse("services")}"', html=False)
		self.assertNotContains(response, "What the work is built around")
		self.assertNotContains(response, "Best aligned with mission-driven teams")
		self.assertNotContains(response, "What Makes Us Different")

	def test_about_stylesheet_is_isolated_to_about_page(self):
		about_response = self.client.get(reverse("about"))
		home_response = self.client.get(reverse("home"))
		services_response = self.client.get(reverse("services"))
		about_stylesheet = static("css/about.css")

		self.assertContains(about_response, about_stylesheet)
		self.assertNotContains(home_response, about_stylesheet)
		self.assertNotContains(services_response, about_stylesheet)

	def test_operational_partnership_route_and_sections(self):
		self.assertEqual(reverse("operational_partnership"), "/operational-partnership/")

		response = self.client.get(reverse("operational_partnership"))

		self.assertEqual(response.status_code, 200)
		content = response.content.decode()
		section_headings = [
			"Build better systems through an ongoing partnership.",
			"What is an Operational Partnership?",
			"Who Can Benefit?",
			"What Your Partnership May Include",
			"Choose the Partnership That Fits Your Goals",
			"Why Continue the Partnership?",
			"Frequently Asked Questions",
			"Let’s Grow Together",
		]
		section_positions = [content.index(heading) for heading in section_headings]
		self.assertEqual(section_positions, sorted(section_positions))

	def test_operational_partnership_renders_approved_cards_and_benefits(self):
		response = self.client.get(reverse("operational_partnership"))

		for audience in (
			"Individuals",
			"Entrepreneurs",
			"Small Businesses",
			"Schools &amp; Educational Organizations",
			"Community Organizations &amp; Nonprofits",
			"Returning Clients",
		):
			self.assertContains(response, audience)

		for benefit in (
			"Goal Planning &amp; Accountability",
			"Strategic Guidance",
			"Operational Consulting",
			"Workflow &amp; Process Improvement",
			"Project Planning",
			"Digital Organization",
			"Website &amp; Technology Support",
			"Research &amp; Problem Solving",
			"System Maintenance",
			"Document Development",
			"Resource Recommendations",
			"Ongoing Communication",
			"Progress Reviews",
			"Implementation Support",
		):
			self.assertContains(response, benefit)

		for level in (
			"Essential Partnership",
			"Growth Partnership",
			"Professional Partnership",
			"Executive Partnership",
		):
			self.assertContains(response, level)
		for monthly_time in ("Up to 2 hours", "Up to 4 hours", "Up to 8 hours"):
			self.assertContains(response, monthly_time)

		for reason in (
			"Consistent Accountability",
			"Trusted Guidance",
			"Flexible Support",
			"Continued Improvement",
			"Organized Progress",
			"Long-Term Relationship",
		):
			self.assertContains(response, reason)

	def test_operational_partnership_presents_two_flexible_paths(self):
		response = self.client.get(reverse("operational_partnership"))

		self.assertContains(response, "Flexible Ways to Work")
		self.assertContains(response, "Project-Based Support")
		self.assertContains(response, "Ongoing Partnership")
		self.assertContains(response, "Begin with either path and move between them as your goals evolve.")
		self.assertContains(response, f'href="{reverse("services")}"', html=False)
		self.assertContains(response, 'href="#partnership-levels"', html=False)
		self.assertNotContains(response, "Start with a Project")
		self.assertNotContains(response, "Continue with an Operational Partnership")

	def test_operational_partnership_uses_approved_ctas_and_semantic_faq(self):
		response = self.client.get(reverse("operational_partnership"))

		self.assertContains(response, f'href="{self.DISCOVERY_URL}"', count=3, html=False)
		self.assertContains(response, 'target="_blank"', count=3, html=False)
		self.assertContains(response, 'rel="noopener noreferrer"', count=3, html=False)
		self.assertContains(
			response,
			f'<a class="btn btn-ghost" href="{reverse("contact_support")}">Contact Miranda Insights</a>',
			html=False,
		)
		self.assertContains(response, "<details", count=4, html=False)
		self.assertContains(response, "Operational Partnership Agreement")
		self.assertNotContains(response, "retainer")
		self.assertNotContains(response, "subscription")

	def test_operational_partnership_styles_are_isolated_and_products_remain(self):
		partnership_response = self.client.get(reverse("operational_partnership"))
		home_response = self.client.get(reverse("home"))
		products_response = self.client.get(reverse("products"))
		partnership_stylesheet = static("css/operational-partnership.css")

		self.assertContains(partnership_response, partnership_stylesheet)
		self.assertContains(partnership_response, 'class="dark-mode operational-partnership-page"', html=False)
		self.assertNotContains(home_response, partnership_stylesheet)
		self.assertNotContains(products_response, partnership_stylesheet)
		self.assertContains(products_response, "Current assessment and framework IDs")
		self.assertContains(products_response, "CaliSchools Insights")

	def test_operational_partnership_renders_in_mobile_webview_context(self):
		response = self.client.get(reverse("operational_partnership"), {"mobile_app": "1"})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Build better systems through an ongoing partnership.")
		self.assertContains(response, static("css/operational-partnership.css"))

	def test_services_page_route_and_sections_render_in_order(self):
		self.assertEqual(reverse("services"), "/services/")

		response = self.client.get(reverse("services"))

		self.assertEqual(response.status_code, 200)
		content = response.content.decode()
		section_headings = [
			"Operational Services",
			"Our Service Areas",
			"Our Process",
			"Possible Deliverables",
			"Frequently Asked Questions",
			"Let’s Build a Solution Together",
		]
		section_positions = [content.index(heading) for heading in section_headings]
		self.assertEqual(section_positions, sorted(section_positions))
		self.assertContains(response, "Project-Based Professional Services")
		self.assertContains(
			response,
			"Miranda Insights provides professional consulting and systems development services designed to help individuals, businesses, schools, nonprofits, and community organizations operate more effectively.",
		)
		self.assertContains(
			response,
			"Whether you’re looking to organize operations, analyze information, improve digital infrastructure, or develop a custom solution",
		)

	def test_services_page_renders_four_formal_service_areas(self):
		response = self.client.get(reverse("services"))

		for service_code, service_name in (
			("INT-001", "Operational Intelligence"),
			("INT-002", "Operational Services"),
			("DGT-001", "Digital Presence Systems"),
			("DGT-002", "Intelligence Application Development"),
		):
			self.assertContains(response, service_code)
			self.assertContains(response, service_name)

		for example_service in (
			"Research &amp; Analysis",
			"Standard Operating Procedures (SOPs)",
			"Cloud Storage Organization",
			"Professional Websites",
			"Business Information Systems",
			"Custom Web Applications",
			"API Integrations",
		):
			self.assertContains(response, example_service, html=False)
		self.assertContains(response, "Ideal For", count=4)

	def test_services_page_renders_approved_process_and_partnership_path(self):
		response = self.client.get(reverse("services"))
		content = response.content.decode()
		steps = ["Discovery", "Planning", "Development", "Review", "Ongoing Support"]
		step_positions = [content.index(f">{step}<") for step in steps]

		self.assertEqual(step_positions, sorted(step_positions))
		self.assertContains(response, "Clients may conclude the project or continue through an")
		self.assertContains(response, f'href="{reverse("operational_partnership")}"', count=5, html=False)

	def test_services_page_features_exactly_four_real_deliverables(self):
		response = self.client.get(reverse("services"))

		self.assertContains(response, 'class="services-deliverable-card"', count=4, html=False)
		for title in (
			"Dashboard",
			"Data Analysis Workbook",
			"Dashboard Presentation",
			"Project Documentation",
		):
			self.assertContains(response, title)
		self.assertContains(
			response,
			"Interactive HTML dashboard example showing how processed data can be delivered in a browser-ready format.",
		)
		self.assertNotContains(response, ">Student Dashboard<", html=False)
		self.assertNotContains(response, ">Student Data Analysis Workbook<", html=False)
		self.assertNotContains(response, ">Student Dashboard Presentation<", html=False)
		self.assertContains(response, 'alt="Cover page of the Project Documentation technical report"', html=False)

		for asset_path in (
			"deliverables/student-dashboard.html",
			"deliverables/student-data-analysis.png",
			"deliverables/student-data-analysis.xlsx",
			"deliverables/student-dashboard-presentation.pdf",
			"deliverables/deliverable-documentation.pdf",
			"img/services/student-dashboard-preview.png",
			"img/services/student-data-analysis-preview.png",
			"img/services/student-dashboard-presentation-preview.png",
			"img/services/project-documentation-preview.png",
		):
			self.assertContains(response, static(asset_path))

		self.assertContains(
			response,
			"Other possible deliverables include SOPs, workflow diagrams, websites, client portals, and digital organization systems.",
			count=1,
		)
		self.assertNotContains(response, "services-deliverables__additional-card")

	def test_services_page_uses_approved_faq_and_calls_to_action(self):
		response = self.client.get(reverse("services"))

		self.assertContains(response, "<details", count=5, html=False)
		self.assertContains(response, '<details class="faq-item services-faq__item" open>', count=1, html=False)
		for question in (
			"Do you offer standardized service packages?",
			"Can multiple services be combined?",
			"Do you work with individuals as well as organizations?",
			"How are projects priced?",
			"Do you provide ongoing support?",
		):
			self.assertContains(response, question)
		self.assertContains(response, f'href="{self.DISCOVERY_URL}"', count=3, html=False)
		self.assertContains(response, 'target="_blank"', count=11, html=False)
		self.assertContains(response, 'rel="noopener noreferrer"', count=11, html=False)
		self.assertContains(response, 'href="#service-areas"', html=False)
		self.assertContains(response, ">Learn About Operational Partnership</a>", html=False)

	def test_services_page_removes_legacy_catalog_and_keeps_separate_concepts_out(self):
		response = self.client.get(reverse("services"))

		for retired_text in (
			"S-001",
			"S-002",
			"S-003",
			"S-004",
			"S-005",
			"S-006",
			"S-007",
			"S-008",
			"R-001",
			"Retainer",
			"InsightSurveys",
			"SurveyHQ",
			"Personal Development",
			"Professional Development",
			"Physical Development",
			"Academic Development",
			"Operational Development",
		):
			self.assertNotContains(response, retired_text)

	def test_services_stylesheet_is_isolated_and_page_supports_mobile_context(self):
		services_response = self.client.get(reverse("services"), {"mobile_app": "1"})
		home_response = self.client.get(reverse("home"))
		products_response = self.client.get(reverse("products"))
		partnership_response = self.client.get(reverse("operational_partnership"))
		services_stylesheet = static("css/services.css")

		self.assertEqual(services_response.status_code, 200)
		self.assertContains(services_response, services_stylesheet)
		self.assertContains(services_response, 'class="dark-mode services-page"', html=False)
		self.assertNotContains(home_response, services_stylesheet)
		self.assertNotContains(products_response, services_stylesheet)
		self.assertNotContains(partnership_response, services_stylesheet)
		self.assertContains(products_response, "Current assessment and framework IDs")
		self.assertContains(partnership_response, "Build better systems through an ongoing partnership.")

	def test_individual_services_route_and_sections_render_in_order(self):
		self.assertEqual(reverse("individual_services"), "/individual-services/")

		response = self.client.get(reverse("individual_services"))

		self.assertEqual(response.status_code, 200)
		content = response.content.decode()
		section_markers = [
			"Focused Individual Support",
			"Focused Support. Built Around Your Goals.",
			"Three Ways to Work Together",
			"Support That Meets You Where You Are",
			"What Kind of Support Fits Your Goal?",
			"Simple, Focused, Personal",
			"Frequently Asked Questions",
			"Let’s Build Support Around Your Goals.",
		]
		section_positions = [content.index(marker) for marker in section_markers]
		self.assertEqual(section_positions, sorted(section_positions))
		self.assertContains(
			response,
			"Sometimes you don’t need a complete operational system. You need focused support in one area.",
		)
		self.assertContains(response, "The right support should fit the goal.")

	def test_individual_services_renders_three_unified_service_panels(self):
		response = self.client.get(reverse("individual_services"))

		self.assertContains(response, 'class="individual-service-card individual-service-card--', count=3, html=False)
		self.assertContains(response, "<svg", count=3, html=False)
		for service, area, description in (
			(
				"Academic Tutoring",
				"Academic Development",
				"Personalized academic support designed to strengthen understanding, organization, confidence, and independent learning.",
			),
			(
				"Fitness Coaching",
				"Physical Development",
				"Structured fitness support designed around consistency, performance, sustainable habits, and individual goals.",
			),
			(
				"Mentorship &amp; Accountability",
				"Personal · Professional · Operational",
				"Practical guidance and accountability for people working toward goals that benefit from greater structure, organization, and consistent follow-through.",
			),
		):
			self.assertContains(response, service, html=False)
			self.assertContains(response, area, html=False)
			self.assertContains(response, description)
		self.assertContains(response, "Direction · Structure · Accountability")

	def test_individual_services_renders_approved_support_areas_and_audiences(self):
		response = self.client.get(reverse("individual_services"))

		for support_area in (
			"Mathematics &amp; Quantitative Subjects",
			"Homework &amp; Assignment Support within Agreed Subject Areas",
			"Study Planning",
			"Test Preparation",
			"Training Structure",
			"Strength Development",
			"Performance Development",
			"Progress Tracking",
			"Personal Organization",
			"Professional Development",
			"Routine Development",
			"Resource Organization",
			"Digital Organization",
		):
			self.assertContains(response, support_area, html=False)
		self.assertContains(response, "Subject availability is confirmed during Discovery")

		for audience in (
			"Students",
			"Athletes",
			"Professionals",
			"Entrepreneurs",
			"Individuals",
			"People Navigating New Goals or Projects",
		):
			self.assertContains(response, audience)
		self.assertContains(response, "If you have a goal and believe greater structure, support, or accountability could help you move it forward, we can start there.")

	def test_individual_services_uses_approved_links_comparison_and_process(self):
		response = self.client.get(reverse("individual_services"))
		content = response.content.decode()
		steps = ["Connect", "Define the Goal", "Work Together", "Adjust as You Grow"]
		step_positions = [content.index(f">{step}<") for step in steps]

		self.assertEqual(step_positions, sorted(step_positions))
		self.assertContains(response, f'href="{self.DISCOVERY_URL}"', count=6, html=False)
		self.assertContains(response, 'target="_blank"', count=6, html=False)
		self.assertContains(response, 'rel="noopener noreferrer"', count=6, html=False)
		self.assertContains(response, 'href="#individual-services"', count=2, html=False)
		self.assertContains(response, "Either model can be your starting point.")
		self.assertContains(response, f'href="{reverse("operational_partnership")}"', html=False)
		self.assertContains(response, ">Explore Operational Partnership</a>", count=2, html=False)

	def test_individual_services_uses_semantic_faq_and_pricing_fallback(self):
		response = self.client.get(reverse("individual_services"))

		self.assertContains(response, "<details", count=6, html=False)
		self.assertContains(response, '<details class="faq-item individual-faq__item" open>', count=1, html=False)
		for question in (
			"Who can use Individual Services?",
			"Do I need an Operational Partnership first?",
			"Can I use more than one Individual Service?",
			"How are sessions scheduled?",
			"Are Individual Services customized?",
			"Where can I find current pricing?",
		):
			self.assertContains(response, question)
		self.assertContains(response, "Current service pricing and engagement details can be discussed during a Discovery Session.")
		self.assertNotContains(response, "/resources/", html=False)

	def test_individual_services_excludes_unapproved_and_regulated_offerings(self):
		response = self.client.get(reverse("individual_services"))

		for excluded_text in (
			"SurveyHQ",
			"InsightSurveys",
			"A-001",
			"A-002",
			"F-001",
			"F-002",
			"Therapy",
			"Medical Advice",
			"Physical Therapy",
			"Injury Diagnosis",
			"Financial Advising",
			"Nutrition Treatment",
			"Clinical Services",
			"Add to Cart",
			"Checkout",
		):
			self.assertNotContains(response, excluded_text)

	def test_individual_services_stylesheet_is_isolated_and_mobile_context_renders(self):
		individual_response = self.client.get(reverse("individual_services"), {"mobile_app": "1"})
		individual_stylesheet = static("css/individual-services.css")

		self.assertEqual(individual_response.status_code, 200)
		self.assertContains(individual_response, individual_stylesheet)
		self.assertContains(individual_response, 'class="dark-mode individual-services-page"', html=False)
		for route_name in ("home", "about", "services", "operational_partnership", "products"):
			with self.subTest(route_name=route_name):
				response = self.client.get(reverse(route_name))
				self.assertEqual(response.status_code, 200)
				self.assertNotContains(response, individual_stylesheet)

	def test_resources_page_keeps_contact_route_and_renders_sections_in_order(self):
		self.assertEqual(reverse("contact_support"), "/contact/")

		response = self.client.get(reverse("contact_support"))

		self.assertEqual(response.status_code, 200)
		content = response.content.decode()
		section_markers = [
			'class="resources-hero"',
			'id="resources-library-heading"',
			'id="client-process"',
			'id="resources-faq"',
			'id="resources-connect-heading"',
			'id="contact-form"',
			'id="resources-final-cta-heading"',
		]
		positions = [content.index(marker) for marker in section_markers]
		self.assertEqual(positions, sorted(positions))
		self.assertContains(response, '<h1 id="resources-hero-heading">Resources</h1>', html=False)
		self.assertContains(
			response,
			"Miranda Insights provides useful information, practical answers, and direct ways to connect",
		)

	def test_resources_page_has_only_current_public_resources(self):
		response = self.client.get(reverse("contact_support"))

		self.assertContains(response, 'class="resource-card"', count=2, html=False)
		self.assertContains(response, 'href="#resources-faq"', count=1, html=False)
		self.assertContains(response, 'href="#client-process"', count=1, html=False)
		self.assertContains(response, "Frequently Asked Questions")
		self.assertContains(response, "Client Process")
		for unavailable_resource in (
			"Pricing Catalog",
			"Service Overview PDF",
			"Client Documents",
			"Coming Soon",
		):
			self.assertNotContains(response, unavailable_resource)

	def test_resources_client_process_links_each_engagement_model(self):
		response = self.client.get(reverse("contact_support"))
		content = response.content.decode()
		steps = ["Connect", "Clarify", "Choose the Fit", "Move Forward"]
		positions = [content.index(f">{step}<") for step in steps]

		self.assertEqual(positions, sorted(positions))
		self.assertContains(response, 'class="resources-process-card"', count=4, html=False)
		self.assertContains(response, f'href="{reverse("individual_services")}"', html=False)
		self.assertContains(response, f'href="{reverse("services")}"', html=False)
		self.assertContains(response, f'href="{reverse("operational_partnership")}"', html=False)

	def test_resources_page_uses_current_semantic_faq(self):
		response = self.client.get(reverse("contact_support"))

		self.assertContains(response, "<details", count=7, html=False)
		self.assertContains(response, '<details class="faq-item resources-faq__item" open>', count=1, html=False)
		for question in (
			"What types of clients do you work with?",
			"How do I get started?",
			"Are services customized?",
			"What is the difference between Operational Services, Individual Services, and Operational Partnership?",
			"Can multiple services be combined?",
			"Where will I track my project?",
			"How is pricing determined?",
		):
			self.assertContains(response, question)
		for retired_text in ("R-001", "Retainer Agreement", "InsightSurveys"):
			self.assertNotContains(response, retired_text)

	def test_resources_page_uses_approved_calls_to_action_and_anchors(self):
		response = self.client.get(reverse("contact_support"))

		self.assertContains(response, f'href="{self.DISCOVERY_URL}"', count=4, html=False)
		self.assertContains(response, 'target="_blank"', count=4, html=False)
		self.assertContains(response, 'rel="noopener noreferrer"', count=4, html=False)
		self.assertContains(response, 'href="#contact-form"', count=2, html=False)
		self.assertContains(response, f'href="{reverse("dashboard")}"', html=False)
		self.assertContains(response, 'id="client-process"', html=False)
		self.assertContains(response, 'id="resources-faq"', html=False)
		self.assertContains(response, 'id="contact-form"', html=False)

	def test_resources_page_preserves_contact_form_and_turnstile_hooks(self):
		with override_settings(TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="secret-key"):
			response = self.client.get(reverse("contact_support"))

		for field_id in (
			"id_name",
			"id_organization",
			"id_email",
			"id_phone",
			"id_business_location",
			"id_subject_choice",
			"id_subject_other",
			"id_message",
		):
			self.assertContains(response, f'id="{field_id}"', html=False)
		self.assertContains(response, 'name="csrfmiddlewaretoken"', html=False)
		self.assertContains(response, "data-loading-form", html=False)
		self.assertContains(response, "data-submit-button", html=False)
		self.assertContains(response, "data-subject-other-row", html=False)
		self.assertContains(response, 'class="cf-turnstile"', html=False)
		self.assertContains(response, 'data-sitekey="site-key"', html=False)
		self.assertContains(response, "challenges.cloudflare.com/turnstile/v0/api.js", html=False)

	@override_settings(SUPPORT_EMAIL="support@example.com", CONTACT_RECIPIENT="support@example.com")
	def test_resources_page_displays_configured_support_email(self):
		response = self.client.get(reverse("contact_support"))

		self.assertContains(response, "support@example.com", count=3)
		self.assertContains(response, 'href="mailto:support%40example.com"', count=3, html=False)

	@override_settings(SUPPORT_EMAIL="", CONTACT_RECIPIENT=None)
	def test_resources_page_omits_unconfigured_support_email_from_page_content(self):
		response = self.client.get(reverse("contact_support"))
		content = response.content.decode()
		page_start = content.index('<div class="resources-shell">')
		page_end = content.index("</main>", page_start)
		resources_content = content[page_start:page_end]

		self.assertNotIn("mailto:", resources_content)
		self.assertNotIn("None", resources_content)

	def test_resources_stylesheet_is_isolated_and_mobile_context_renders(self):
		resources_response = self.client.get(reverse("contact_support"), {"mobile_app": "1"})
		resources_stylesheet = static("css/contact.css")

		self.assertEqual(resources_response.status_code, 200)
		self.assertContains(resources_response, f'{resources_stylesheet}?v=4', html=False)
		self.assertContains(resources_response, static("css/marketing-pages.css"))
		self.assertContains(resources_response, 'class="dark-mode contact-page"', html=False)
		for route_name in (
			"home",
			"about",
			"services",
			"operational_partnership",
			"individual_services",
			"products",
			"faq",
		):
			with self.subTest(route_name=route_name):
				response = self.client.get(reverse(route_name))
				self.assertEqual(response.status_code, 200)
				self.assertNotContains(response, resources_stylesheet)

	def test_homepage_contact_action_still_resolves_to_resources_page(self):
		home_response = self.client.get(reverse("home"))
		resources_response = self.client.get(reverse("contact_support"))

		self.assertContains(home_response, f'href="{reverse("contact_support")}"', html=False)
		self.assertEqual(resources_response.status_code, 200)


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	CONTACT_RECIPIENT="support@example.com",
	DEFAULT_FROM_EMAIL="no-reply@example.com",
	SITE_URL="https://mirandainsights.com",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class ContactSupportFlowTests(TestCase):
	def setUp(self):
		self.payload = {
			"name": "Taylor Client",
			"organization": "Northwind",
			"email": "taylor@example.com",
			"phone": "",
			"business_location": "",
			"subject_choice": "support",
			"message": "Need help with the portal.",
		}

	def test_contact_support_redirects_back_to_contact_for_website(self):
		response = self.client.post(reverse("contact_support"), self.payload)

		self.assertRedirects(response, reverse("contact_support"))
		self.assertEqual(len(mail.outbox), 2)
		self.assertEqual(mail.outbox[0].to, ["support@example.com"])
		self.assertEqual(mail.outbox[0].reply_to, ["taylor@example.com"])
		self.assertEqual(mail.outbox[1].to, ["taylor@example.com"])
		self.assertEqual(mail.outbox[1].reply_to, ["support@mirandainsights.com"])
		messages = list(get_messages(response.wsgi_request))
		self.assertEqual(len(messages), 1)
		self.assertEqual(
			str(messages[0]),
			"Thanks, your support request has been received. A confirmation message has been sent to your email.",
		)

	def test_mobile_app_contact_support_redirects_to_dashboard_with_success_message(self):
		user = User.objects.create_user(
			username="mobileclient",
			email="taylor@example.com",
			password="test-pass-123",
			first_name="Taylor",
		)
		self.client.force_login(user)

		response = self.client.post(reverse("contact_support"), {**self.payload, "mobile_app": "1"}, follow=True)

		self.assertRedirects(response, reverse("dashboard"))
		self.assertEqual(len(mail.outbox), 2)
		self.assertContains(
			response,
			"Thanks, your support request has been received. A confirmation message has been sent to your email.",
		)
		self.assertContains(response, "Welcome back, Taylor")

	def test_contact_support_preserves_accessible_validation_errors(self):
		response = self.client.post(reverse("contact_support"), {})

		self.assertEqual(response.status_code, 200)
		for field_name in ("name", "organization", "email", "subject_choice", "message"):
			self.assertContains(response, f'id="id_{field_name}_error"', html=False)
			self.assertContains(response, f'aria-describedby="id_{field_name}_error"', html=False)
		self.assertContains(response, 'aria-live="polite"', html=False)


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	SITE_URL="https://mirandainsights.com",
	MEDIA_ROOT=TEMP_MEDIA_ROOT,
	MEDIA_URL="/media/",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class NewsletterSendCampaignTests(TestCase):
	def create_campaign(self, **overrides):
		defaults = {
			"name": "Test campaign",
			"subject": "Hello from test",
			"body": "Body text",
			"include_subscribers": True,
			"direct_recipients": "",
		}
		defaults.update(overrides)
		return NewsletterCampaign.objects.create(**defaults)

	def test_send_campaign_direct_recipients_only(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(
			include_subscribers=False,
			direct_recipients="direct1@example.com, direct2@example.com",
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 2)
		self.assertEqual(failed, 0)
		logged = list(
			NewsletterSendLog.objects.filter(campaign=campaign, status=NewsletterSendLog.STATUS_SENT)
			.values_list("recipient_email", flat=True)
		)
		self.assertCountEqual(logged, ["direct1@example.com", "direct2@example.com"])

	def test_send_campaign_deduplicates_subscribers_and_direct_recipients(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		NewsletterSubscriber.objects.create(email="sub2@example.com", is_active=True)
		campaign = self.create_campaign(
			include_subscribers=True,
			direct_recipients="sub1@example.com, extra@example.com",
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 3)
		self.assertEqual(failed, 0)
		logged = list(
			NewsletterSendLog.objects.filter(campaign=campaign, status=NewsletterSendLog.STATUS_SENT)
			.values_list("recipient_email", flat=True)
		)
		self.assertCountEqual(logged, ["sub1@example.com", "sub2@example.com", "extra@example.com"])

	def test_send_campaign_logs_invalid_direct_recipient(self):
		campaign = self.create_campaign(
			include_subscribers=False,
			direct_recipients="good@example.com, not-an-email",
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 1)
		failed_log = NewsletterSendLog.objects.get(
			campaign=campaign,
			recipient_email="not-an-email",
			status=NewsletterSendLog.STATUS_FAILED,
		)
		self.assertIn("Invalid email", failed_log.error_message)

	def test_send_campaign_adds_unsubscribe_footer_and_headers(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(body="Body text")

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 0)
		self.assertEqual(len(mail.outbox), 1)
		message = mail.outbox[0]
		self.assertIn(
			"If you wish to not receive anymore newsletters from us, click Unsubscribe.",
			message.body,
		)
		self.assertIn("https://mirandainsights.com/newsletter/unsubscribe/?token=", message.body)
		self.assertEqual(len(message.alternatives), 1)
		html_body, mime_type = message.alternatives[0]
		self.assertEqual(mime_type, "text/html")
		self.assertIn(
			"If you wish to not receive anymore newsletters from us, click <a href=\"https://mirandainsights.com/newsletter/unsubscribe/?token=",
			html_body,
		)
		self.assertIn(">Unsubscribe</a>.", html_body)
		self.assertEqual(message.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
		self.assertTrue(
			message.extra_headers["List-Unsubscribe"].startswith(
				"<https://mirandainsights.com/newsletter/unsubscribe/?token="
			)
		)

	def test_subscribe_ajax_returns_json_without_redirect(self):
		response = self.client.post(
			reverse("newsletter_subscribe"),
			{"email": "person@example.com"},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["level"], "success")
		self.assertEqual(response.json()["sectionId"], "newsletter-signup")
		self.assertTrue(NewsletterSubscriber.objects.filter(email="person@example.com", is_active=True).exists())

	def test_home_renders_turnstile_widget_when_enabled(self):
		with override_settings(TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="secret-key"):
			response = self.client.get(reverse("home"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'class="cf-turnstile"', html=False)
		self.assertContains(response, 'data-sitekey="site-key"', html=False)
		self.assertNotContains(response, 'challenges.cloudflare.com/turnstile/v0/api.js', html=False)

	def test_subscribe_requires_turnstile_when_enabled(self):
		with override_settings(TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="secret-key"):
			response = self.client.post(
				reverse("newsletter_subscribe"),
				{"email": "person@example.com"},
				HTTP_X_REQUESTED_WITH="XMLHttpRequest",
			)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.json()["level"], "error")
		self.assertEqual(response.json()["message"], "Security verification failed. Please try again.")
		self.assertFalse(NewsletterSubscriber.objects.filter(email="person@example.com").exists())

	@patch("apps.news.views.verify_turnstile_for_request", return_value=(True, []))
	def test_subscribe_accepts_valid_turnstile_when_enabled(self, verify_turnstile_for_request_mock):
		with override_settings(TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="secret-key"):
			response = self.client.post(
				reverse("newsletter_subscribe"),
				{
					"email": "person@example.com",
					"cf-turnstile-response": "token-value",
				},
				HTTP_X_REQUESTED_WITH="XMLHttpRequest",
			)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["level"], "success")
		self.assertTrue(NewsletterSubscriber.objects.filter(email="person@example.com", is_active=True).exists())
		verify_turnstile_for_request_mock.assert_called_once()

	def test_unsubscribe_link_deletes_subscriber(self):
		subscriber = NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(body="Body text")

		send_campaign(campaign)

		unsubscribe_url = mail.outbox[0].extra_headers["List-Unsubscribe"].strip("<>")
		parsed_url = urlsplit(unsubscribe_url)
		response = self.client.get(f"{parsed_url.path}?{parsed_url.query}", follow=True)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.redirect_chain)
		self.assertIn("newsletter_status=unsubscribed#newsletter-signup", response.redirect_chain[0][0])
		self.assertFalse(NewsletterSubscriber.objects.filter(pk=subscriber.pk).exists())
		self.assertContains(response, "You have been unsubscribed from newsletter emails.")

	@patch("apps.operations.services.dispatch_newsletter_campaign")
	@patch("apps.news.services.connections.close_all")
	@patch("apps.news.services.NewsletterCampaign.objects.filter")
	def test_process_due_automated_campaigns_retries_once_after_operational_error(
		self,
		filter_mock,
		close_all_mock,
		dispatch_newsletter_campaign_mock,
	):
		campaign = self.create_campaign(
			mode=NewsletterCampaign.MODE_AUTOMATED,
			is_active=True,
			next_send_at=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
		)

		filter_mock.side_effect = [OperationalError("timeout"), [campaign]]

		processed = process_due_automated_campaigns()

		self.assertEqual(processed, 1)
		close_all_mock.assert_called_once()
		dispatch_newsletter_campaign_mock.assert_called_once_with(campaign)

	@patch("apps.news.services.connections.close_all")
	@patch("apps.news.services.NewsletterCampaign.objects.filter", side_effect=OperationalError("timeout"))
	def test_process_due_automated_campaigns_returns_zero_when_database_stays_unavailable(
		self,
		filter_mock,
		close_all_mock,
	):
		processed = process_due_automated_campaigns()

		self.assertEqual(processed, 0)
		self.assertEqual(filter_mock.call_count, 2)
		close_all_mock.assert_called_once()

	def test_send_campaign_renders_structured_blocks(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(
			body="",
			preheader="Quarterly highlights",
			content_blocks=[
				{"type": "heading", "text": "Q1 Highlights", "level": "1", "align": "left"},
				{"type": "paragraph", "text": "A polished newsletter without raw HTML.", "style": "lead", "align": "left"},
				{"type": "button", "text": "Read more", "url": "https://mirandainsights.com/services/", "style": "primary", "align": "center"},
			],
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 0)
		self.assertEqual(len(mail.outbox), 1)
		message = mail.outbox[0]
		self.assertIn("Q1 Highlights", message.body)
		html_body, _ = message.alternatives[0]
		self.assertIn("Quarterly highlights", html_body)
		self.assertIn("Read more", html_body)
		self.assertIn("https://mirandainsights.com/services/", html_body)

	def test_normalize_blocks_rejects_invalid_image_url(self):
		with self.assertRaises(ValidationError):
			normalize_blocks([
				{"type": "image", "image_url": "notaurl", "alt_text": "Chart"},
			])

	def test_send_campaign_renders_uploaded_image_asset(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		asset = NewsletterImageAsset.objects.create(
			name="Hero Chart",
			alt_text="Growth chart",
			default_caption="Monthly growth snapshot",
			image=SimpleUploadedFile(
				"chart.gif",
				b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;",
				content_type="image/gif",
			),
		)
		campaign = self.create_campaign(
			body="",
			content_blocks=[
				{"type": "image", "image_asset_id": asset.pk, "caption": "", "link_url": "", "width": "wide", "alt_text": ""},
			],
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 0)
		self.assertIn("Growth chart", mail.outbox[0].body)
		self.assertIn("Monthly growth snapshot", mail.outbox[0].body)
		html_body, _ = mail.outbox[0].alternatives[0]
		self.assertIn("https://mirandainsights.com/media/newsletter/images/", html_body)
		self.assertIn("Growth chart", html_body)
		self.assertIn("Monthly growth snapshot", html_body)

	def test_normalize_blocks_accepts_uploaded_image_without_url(self):
		blocks = normalize_blocks([
			{"type": "image", "image_asset_id": 7, "alt_text": "", "caption": "", "link_url": "", "width": "full"},
		])
		self.assertEqual(blocks[0]["image_asset_id"], 7)

	def test_default_templates_exist(self):
		self.assertTrue(NewsletterBlockTemplate.objects.filter(slug="hero-spotlight", is_builtin=True).exists())
		self.assertTrue(NewsletterBlockTemplate.objects.filter(slug="event-announcement", is_builtin=True).exists())
		self.assertTrue(NewsletterBlockTemplate.objects.filter(slug="article-digest", is_builtin=True).exists())

	@override_settings(TIME_ZONE="UTC", NEWSLETTER_TIME_ZONE="America/Los_Angeles")
	def test_compute_next_send_at_uses_newsletter_timezone(self):
		campaign = self.create_campaign(
			mode=NewsletterCampaign.MODE_AUTOMATED,
			frequency=NewsletterCampaign.FREQ_DAILY,
			send_time=time(15, 0),
		)

		next_send_at = campaign.compute_next_send_at(
			datetime(2026, 4, 30, 19, 0, tzinfo=datetime_timezone.utc)
		)

		self.assertEqual(
			next_send_at,
			datetime(2026, 4, 30, 22, 0, tzinfo=datetime_timezone.utc),
		)


@override_settings(NEWSLETTER_SCHEDULER_TOKEN="test-newsletter-scheduler-token")
class NewsletterSchedulerTests(TestCase):
	@patch("apps.news.views.process_due_automated_campaigns", return_value=2)
	def test_scheduler_accepts_query_token_and_processes_due_campaigns(self, process_mock):
		response = self.client.get(
			reverse("newsletter_scheduler"),
			{"token": "test-newsletter-scheduler-token"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {"status": "ok", "processed": 2})
		process_mock.assert_called_once_with()

	@patch("apps.news.views.process_due_automated_campaigns")
	def test_scheduler_rejects_invalid_token(self, process_mock):
		response = self.client.get(reverse("newsletter_scheduler"), {"token": "wrong-token"})

		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.json(), {"status": "unauthorized"})
		process_mock.assert_not_called()

	@override_settings(NEWSLETTER_SCHEDULER_TOKEN="")
	@patch("apps.news.views.process_due_automated_campaigns")
	def test_scheduler_fails_closed_when_token_is_not_configured(self, process_mock):
		response = self.client.get(reverse("newsletter_scheduler"), {"token": "any-token"})

		self.assertEqual(response.status_code, 503)
		self.assertEqual(response.json(), {"status": "not_configured"})
		process_mock.assert_not_called()


class NewsletterSubscriberAdminTests(TestCase):
	def setUp(self):
		self.site = AdminSite()
		self.admin = NewsletterSubscriberAdmin(NewsletterSubscriber, self.site)
		self.factory = RequestFactory()

	def test_get_queryset_annotates_has_account(self):
		NewsletterSubscriber.objects.create(email="with-account@example.com", is_active=True)
		NewsletterSubscriber.objects.create(email="without-account@example.com", is_active=True)
		User.objects.create_user(username="withaccount", email="with-account@example.com", password="test-pass-123")

		request = self.factory.get("/admin/news/newslettersubscriber/")
		queryset = self.admin.get_queryset(request)

		results = {subscriber.email: subscriber.has_account for subscriber in queryset}
		self.assertTrue(results["with-account@example.com"])
		self.assertFalse(results["without-account@example.com"])

	def test_has_account_filter_returns_only_matching_rows(self):
		NewsletterSubscriber.objects.create(email="with-account@example.com", is_active=True)
		NewsletterSubscriber.objects.create(email="without-account@example.com", is_active=True)
		User.objects.create_user(username="withaccount", email="with-account@example.com", password="test-pass-123")

		request = self.factory.get("/admin/news/newslettersubscriber/", {"has_account": "yes"})
		filter_instance = HasAccountListFilter(
			request,
			{},
			NewsletterSubscriber,
			self.admin,
		)
		filter_instance.used_parameters = {"has_account": "yes"}
		filtered = filter_instance.queryset(request, self.admin.get_queryset(request))

		self.assertEqual(list(filtered.values_list("email", flat=True)), ["with-account@example.com"])


class NewsletterCampaignAdminTests(TestCase):
	def setUp(self):
		self.site = AdminSite()
		self.admin = NewsletterCampaignAdmin(NewsletterCampaign, self.site)
		self.factory = RequestFactory()
		self.staff_user = User.objects.create_user(
			username="newsletteradmin",
			email="newsletteradmin@example.com",
			password="test-pass-123",
			is_staff=True,
		)

	@override_settings(TIME_ZONE="UTC", NEWSLETTER_TIME_ZONE="America/Los_Angeles")
	def test_save_model_recomputes_next_send_at_when_schedule_changes(self):
		campaign = NewsletterCampaign.objects.create(
			name="Monthly campaign",
			subject="Monthly update",
			body="Body text",
			mode=NewsletterCampaign.MODE_AUTOMATED,
			is_active=True,
			frequency=NewsletterCampaign.FREQ_MONTHLY,
			day_of_month=1,
			send_time=time(8, 0),
			next_send_at=datetime(2026, 5, 1, 15, 0, tzinfo=datetime_timezone.utc),
		)
		campaign.day_of_month = 5
		campaign.send_time = time(15, 0)
		request = self.factory.post(f"/admin/news/newslettercampaign/{campaign.pk}/change/")
		request.user = self.staff_user

		class StubForm:
			changed_data = ["day_of_month", "send_time"]

		with patch("apps.news.models.timezone.now", return_value=datetime(2026, 4, 30, 19, 0, tzinfo=datetime_timezone.utc)):
			self.admin.save_model(request, campaign, StubForm(), change=True)

		campaign.refresh_from_db()
		self.assertEqual(
			campaign.next_send_at,
			datetime(2026, 5, 5, 22, 0, tzinfo=datetime_timezone.utc),
		)

	@override_settings(TIME_ZONE="UTC", NEWSLETTER_TIME_ZONE="America/Los_Angeles")
	def test_last_sent_at_display_uses_newsletter_timezone(self):
		campaign = NewsletterCampaign.objects.create(
			name="Daily campaign",
			subject="Daily update",
			body="Body text",
			mode=NewsletterCampaign.MODE_AUTOMATED,
			is_active=True,
			frequency=NewsletterCampaign.FREQ_DAILY,
			last_sent_at=datetime(2026, 5, 1, 19, 0, tzinfo=datetime_timezone.utc),
		)

		display_value = self.admin.last_sent_at_display(campaign)

		self.assertEqual(display_value, "May 1, 2026, noon")


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	CONTACT_RATE_LIMIT="1/1h",
	CONTACT_RECIPIENT="support@example.com",
	DEFAULT_FROM_EMAIL="no-reply@example.com",
	SITE_URL="https://mirandainsights.com",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class ContactSupportThrottleTests(TestCase):
	def test_contact_support_rate_limit_returns_429_after_limit(self):
		payload = {
			"name": "Taylor Client",
			"organization": "Northwind",
			"email": "taylor@example.com",
			"phone": "",
			"business_location": "",
			"subject_choice": "support",
			"message": "Need help with the portal.",
		}

		first_response = self.client.post(reverse("contact_support"), payload, secure=True)
		second_response = self.client.post(reverse("contact_support"), payload, secure=True)

		self.assertEqual(first_response.status_code, 302)
		self.assertEqual(second_response.status_code, 429)
		self.assertContains(second_response, "Too many contact requests were submitted. Please wait and try again.", status_code=429)
		self.assertGreater(int(second_response["Retry-After"]), 0)
		self.assertLessEqual(int(second_response["Retry-After"]), 3600)


@override_settings(
	NEWSLETTER_SUBSCRIBE_RATE_LIMIT="1/1h",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class NewsletterSubscribeThrottleTests(TestCase):
	def test_subscribe_rate_limit_returns_429_after_limit(self):
		payload = {"email": "throttle-person@example.com"}
		first_response = self.client.post(reverse("newsletter_subscribe"), payload, secure=True)
		second_response = self.client.post(reverse("newsletter_subscribe"), payload, secure=True)

		self.assertEqual(first_response.status_code, 302)
		self.assertEqual(second_response.status_code, 429)
		self.assertGreater(int(second_response["Retry-After"]), 0)
		self.assertLessEqual(int(second_response["Retry-After"]), 3600)
