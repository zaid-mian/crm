from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from companies.models import Company
from contacts.models import Contact
from opportunities.models import Opportunity
from leads.models import Lead

User = get_user_model()

class CompanyViewSetTestCase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pwd')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'pwd', is_staff=True)
        self.sales_a = User.objects.create_user('sales_a', 'sales_a@example.com', 'pwd')
        self.sales_b = User.objects.create_user('sales_b', 'sales_b@example.com', 'pwd')

        self.company_a = Company.objects.create(
            name="Alpha Corp",
            assigned_salesperson=self.sales_a,
            website="https://alpha.com",
            email="info@alpha.com"
        )
        self.company_b = Company.objects.create(
            name="Beta Corp",
            assigned_salesperson=self.sales_b
        )

        self.list_url = reverse('companies:company-list')
        self.detail_url_a = reverse('companies:company-detail', kwargs={'pk': self.company_a.pk})

    def test_company_list_scoping(self):
        """Verify visibility scoping on Company listing endpoint."""
        # Admin sees both
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 2)

        # Sales A sees only Alpha Corp
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.get(self.list_url)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)
        self.assertEqual(response.data["data"]["results"][0]["name"], "Alpha Corp")

    def test_company_retrieve_access(self):
        """Verify retrieve restrictions on Company details endpoint."""
        # Sales A retrieve Alpha Corp (Success)
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.get(self.detail_url_a)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["name"], "Alpha Corp")

        # Sales A retrieve Beta Corp (NotFound due to scoping)
        detail_url_b = reverse('companies:company-detail', kwargs={'pk': self.company_b.pk})
        response = self.client.get(detail_url_b)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_company_create_and_validation(self):
        """Verify validation rules and unique company name constraints."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "name": "Alpha Corp", # Duplicate name
            "email": "invalid-email",
            "website": "invalid-url",
            "annual_revenue": -100,
            "employee_count": -5
        }
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data["errors"])
        self.assertIn("email", response.data["errors"])
        self.assertIn("website", response.data["errors"])
        self.assertIn("annual_revenue", response.data["errors"])
        self.assertIn("employee_count", response.data["errors"])

        # Successful creation
        payload["name"] = "Unique Gamma LLC"
        payload["email"] = "gamma@example.com"
        payload["website"] = "https://gamma.com"
        payload["annual_revenue"] = 50000
        payload["employee_count"] = 10
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["name"], "Unique Gamma LLC")

    def test_company_delete_protection(self):
        """Verify ProtectedError interceptor outputs detail payload when delete blocks."""
        self.client.force_authenticate(user=self.admin)

        # Create contact referencing company_a
        contact = Contact.objects.create(
            full_name="John Doe",
            company=self.company_a,
            phone_number="+111"
        )
        # Create opportunity referencing company_a
        lead = Lead.objects.create(
            full_name="Lead",
            company_name="Alpha Corp",
            assigned_salesperson=self.sales_a
        )
        from django.utils import timezone
        Opportunity.objects.create(
            name="Alpha Deal",
            company=self.company_a,
            source_lead=lead,
            primary_contact=contact,
            assigned_salesperson=self.sales_a,
            expected_close_date=timezone.now().date()
        )

        response = self.client.delete(self.detail_url_a)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "Cannot delete company because it has 1 related contacts and 1 opportunities."
        )
