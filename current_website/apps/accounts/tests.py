from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AccountProfile
from apps.news.models import NewsletterSubscriber


User = get_user_model()


class DashboardNewsletterPreferenceTests(TestCase):
	def test_dashboard_unsubscribe_deletes_subscriber(self):
		user = User.objects.create_user(username="isaiah", email="isaiah@example.com", password="test-pass-123")
		AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0100",
		)
		subscriber = NewsletterSubscriber.objects.create(email="isaiah@example.com", is_active=True)

		self.client.login(username="isaiah", password="test-pass-123")
		response = self.client.post(
			reverse("dashboard"),
			{"settings_action": "newsletter", "subscribe_to_newsletter": ""},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(NewsletterSubscriber.objects.filter(pk=subscriber.pk).exists())
		self.assertContains(response, "You have been unsubscribed from newsletter updates.")
