from django.test import TestCase
from django.urls import reverse


class HealthAndLoginSmokeTests(TestCase):
    def test_healthz_endpoint_returns_ok(self):
        response = self.client.get(reverse('healthz'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_login_page_loads(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)

