from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from companies.models import Company
from opportunities.models import Opportunity, OpportunityStage
from contacts.models import Contact
from leads.models import Lead

User = get_user_model()

class PaymentAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('salesperson', 'sales@example.com', 'sales123')
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'admincrm123')
        self.company = Company.objects.create(name="Acme Corporation")
        self.contact = Contact.objects.create(full_name="John Doe", company=self.company, phone_number="123456")
        
        self.lead = Lead.objects.create(
            full_name="Alice Smith",
            phone="+11111",
            email="alice@example.com",
            company_name="A Inc",
            assigned_salesperson=self.user
        )
        
        from datetime import date
        self.opportunity = Opportunity.objects.create(
            name="Acme Big Deal",
            company=self.company,
            primary_contact=self.contact,
            source_lead=self.lead,
            stage=OpportunityStage.CLOSED_WON,
            amount=10000.00,
            expected_close_date=date.today(),
            assigned_salesperson=self.user
        )
        self.list_url = reverse('payment-list')

    def test_anonymous_user_blocked(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_user_can_list(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
