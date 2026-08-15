from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from accounts.models import Organization, OwnerProfile
from leads.models import Lead, UserProfile
from contacts.models import Contact
from companies.models import Company
from opportunities.models import Opportunity
from payments.models import Payment
from roles.services import RoleService

User = get_user_model()

class CRMTenantIsolationTestCase(APITestCase):
    def setUp(self):
        # 1. Create default roles
        self.admin_role = RoleService.get_default_admin_role()
        self.sales_role = RoleService.get_default_role('Salesperson')

        # 2. Create Organizations
        self.org_a = Organization.objects.create(name="Tenant A", is_active=True)
        self.org_b = Organization.objects.create(name="Tenant B", is_active=True)

        # 3. Create Users for Tenant A
        self.user_a_admin = User.objects.create_user(username="admin_a", email="admin_a@test.com", password="password")
        OwnerProfile.objects.create(user=self.user_a_admin, organization=self.org_a, cnic="1111111111111", phone_number="03001111111")
        # Ensure UserProfile exists with ADMIN and mapped to org_a
        UserProfile.objects.filter(user=self.user_a_admin).update(user_type="ADMIN", role=self.admin_role, organization=self.org_a)

        self.user_a_sales = User.objects.create_user(username="sales_a", email="sales_a@test.com", password="password")
        UserProfile.objects.filter(user=self.user_a_sales).update(user_type="USER", role=self.sales_role, organization=self.org_a)

        # 4. Create Users for Tenant B
        self.user_b_admin = User.objects.create_user(username="admin_b", email="admin_b@test.com", password="password")
        OwnerProfile.objects.create(user=self.user_b_admin, organization=self.org_b, cnic="2222222222222", phone_number="03002222222")
        UserProfile.objects.filter(user=self.user_b_admin).update(user_type="ADMIN", role=self.admin_role, organization=self.org_b)

        # 5. Create Platform Admin (Superuser)
        self.platform_admin = User.objects.create_superuser(username="platform_admin", email="padmin@test.com", password="password")

        # 6. Create CRM records for Tenant A
        self.company_a = Company.objects.create(organization=self.org_a, name="Company A", assigned_salesperson=self.user_a_sales)
        self.lead_a = Lead.objects.create(organization=self.org_a, full_name="Lead A", phone="03001234567", company_name="Company A", assigned_salesperson=self.user_a_sales)
        self.contact_a = Contact.objects.create(organization=self.org_a, full_name="Contact A", company=self.company_a, assigned_salesperson=self.user_a_sales)
        self.opp_a = Opportunity.objects.create(
            organization=self.org_a,
            name="Opportunity A",
            company=self.company_a,
            source_lead=self.lead_a,
            primary_contact=self.contact_a,
            assigned_salesperson=self.user_a_sales,
            expected_close_date="2026-12-31"
        )
        self.payment_a = Payment.objects.create(
            organization=self.org_a,
            invoice_number="INV-A01",
            company=self.company_a,
            opportunity=self.opp_a,
            total_amount=1000.00,
            assigned_salesperson=self.user_a_sales
        )

        # 7. Create CRM records for Tenant B
        self.company_b = Company.objects.create(organization=self.org_b, name="Company B", assigned_salesperson=self.user_b_admin)
        self.lead_b = Lead.objects.create(organization=self.org_b, full_name="Lead B", phone="03007654321", company_name="Company B", assigned_salesperson=self.user_b_admin)
        self.contact_b = Contact.objects.create(organization=self.org_b, full_name="Contact B", company=self.company_b, assigned_salesperson=self.user_b_admin)
        self.opp_b = Opportunity.objects.create(
            organization=self.org_b,
            name="Opportunity B",
            company=self.company_b,
            source_lead=self.lead_b,
            primary_contact=self.contact_b,
            assigned_salesperson=self.user_b_admin,
            expected_close_date="2026-12-31"
        )
        self.payment_b = Payment.objects.create(
            organization=self.org_b,
            invoice_number="INV-B01",
            company=self.company_b,
            opportunity=self.opp_b,
            total_amount=2000.00,
            assigned_salesperson=self.user_b_admin
        )

    def test_tenant_a_cannot_read_tenant_b(self):
        """Verify Tenant A admin/salesperson cannot retrieve Tenant B records."""
        self.client.login(username="admin_a", password="password")
        
        urls = [
            reverse("leads:lead-detail", kwargs={"pk": self.lead_b.pk}),
            reverse("contacts:contact-detail", kwargs={"pk": self.contact_b.pk}),
            reverse("companies:company-detail", kwargs={"pk": self.company_b.pk}),
            reverse("opportunities:opportunity-detail", kwargs={"pk": self.opp_b.pk}),
            reverse("payment-detail", kwargs={"pk": self.payment_b.pk}),
        ]
        
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_a_cannot_list_tenant_b(self):
        """Verify Tenant A admin cannot see Tenant B records in lists."""
        self.client.login(username="admin_a", password="password")
        
        # Test Leads List
        response = self.client.get(reverse("leads:lead-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Handle formats (Format A has results inside "data")
        results = response.data.get("data", {}).get("results", response.data.get("data", []))
        ids = [item["id"] for item in results]
        self.assertIn(self.lead_a.id, ids)
        self.assertNotIn(self.lead_b.id, ids)

        # Test Companies List
        response = self.client.get(reverse("companies:company-list"))
        results = response.data.get("data", {}).get("results", response.data.get("data", []))
        ids = [item["id"] for item in results]
        self.assertIn(self.company_a.id, ids)
        self.assertNotIn(self.company_b.id, ids)

    def test_tenant_a_cannot_update_tenant_b(self):
        """Verify Tenant A cannot update Tenant B's lead."""
        self.client.login(username="admin_a", password="password")
        url = reverse("leads:lead-detail", kwargs={"pk": self.lead_b.pk})
        response = self.client.patch(url, {"full_name": "Hacked Name"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_a_cannot_delete_tenant_b(self):
        """Verify Tenant A cannot delete Tenant B's contact."""
        self.client.login(username="admin_a", password="password")
        url = reverse("contacts:contact-detail", kwargs={"pk": self.contact_b.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_organization_derived_on_creation(self):
        """Verify the backend ignores submitted organization_id and derives it from user."""
        self.client.login(username="admin_a", password="password")
        
        # Post request trying to set organization to Tenant B (self.org_b.id)
        payload = {
            "full_name": "New Lead",
            "phone": "03009999999",
            "company_name": "New Co",
            "organization": self.org_b.id
        }
        
        response = self.client.post(reverse("leads:lead-list"), payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify it was saved under org_a (not org_b!)
        lead_id = response.data.get("data", response.data)["id"]
        lead = Lead.objects.get(id=lead_id)
        self.assertEqual(lead.organization, self.org_a)

    def test_platform_admin_has_global_access(self):
        """Verify platform superuser has global visibility."""
        self.client.login(username="platform_admin", password="password")
        
        # Retrieve lead B
        response = self.client.get(reverse("leads:lead-detail", kwargs={"pk": self.lead_b.pk}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Retrieve lead A
        response = self.client.get(reverse("leads:lead-detail", kwargs={"pk": self.lead_a.pk}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
