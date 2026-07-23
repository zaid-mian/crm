from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date, timedelta

from leads.models import Lead
from contacts.models import Contact
from opportunities.models import Opportunity, OpportunityStage

User = get_user_model()

class OpportunityViewsTestCase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pwd')
        self.salesperson1 = User.objects.create_user('sales1', 'sales1@example.com', 'pwd')
        self.salesperson2 = User.objects.create_user('sales2', 'sales2@example.com', 'pwd')

        self.lead = Lead.objects.create(
            full_name="John Doe", company_name="Acme Corp", phone="+111",
            assigned_salesperson=self.salesperson1
        )
        self.contact = Contact.objects.create(full_name="John Doe", company_name="Acme Corp", phone_number="+111")
        
        self.opp = Opportunity.objects.create(
            name="Acme Deal", company_name="Acme Corp", source_lead=self.lead,
            primary_contact=self.contact, assigned_salesperson=self.salesperson1,
            stage=OpportunityStage.QUALIFICATION, amount=Decimal('5000.00'),
            expected_close_date=date.today() + timedelta(days=30)
        )

        self.list_url = reverse('opportunities:opportunity-list')
        self.detail_url = lambda pk: reverse('opportunities:opportunity-detail', kwargs={'pk': pk})
        self.change_stage_url = lambda pk: reverse('opportunities:opportunity-change-stage', kwargs={'pk': pk})
        self.stats_url = reverse('opportunities:opportunity-stats')

    def test_list_visibility_scoping(self):
        """Verify listing filters opportunities based on the requesting user."""
        # 1. Admin sees everything
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)

        # 2. Salesperson 1 (Owner) sees it
        self.client.force_authenticate(user=self.salesperson1)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)

        # 3. Salesperson 2 (Non-Owner) sees 0
        self.client.force_authenticate(user=self.salesperson2)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 0)

    def test_retrieve_security(self):
        """Verify non-owners are blocked from retrieving detail view."""
        self.client.force_authenticate(user=self.salesperson2)
        response = self.client.get(self.detail_url(self.opp.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.salesperson1)
        response = self.client.get(self.detail_url(self.opp.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_opportunity_success(self):
        """Verify successful update of editable fields."""
        self.client.force_authenticate(user=self.salesperson1)
        payload = {
            "name": "Updated Acme Deal",
            "amount": "6500.00"
        }
        response = self.client.patch(self.detail_url(self.opp.pk), data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["name"], "Updated Acme Deal")
        self.assertEqual(response.data["data"]["amount"], "6500.00")

    def test_change_stage_success(self):
        """Verify change-stage action endpoint transitions stage successfully."""
        self.client.force_authenticate(user=self.salesperson1)
        payload = {"stage": OpportunityStage.DISCOVERY}
        response = self.client.post(self.change_stage_url(self.opp.pk), data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["stage"], OpportunityStage.DISCOVERY)

    def test_stats_aggregation_response(self):
        """Verify stats endpoint returns expected structure and values."""
        self.client.force_authenticate(user=self.salesperson1)
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("total_deals", response.data["data"])
        self.assertEqual(response.data["data"]["total_deals"], 1)
