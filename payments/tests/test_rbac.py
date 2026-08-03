from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.core.cache import cache
from datetime import date

from leads.models import UserProfile
from companies.models import Company
from contacts.models import Contact
from leads.models import Lead
from opportunities.models import Opportunity
from payments.models import Payment
from roles.models import Role, CRMResource, RolePermission

User = get_user_model()

class PaymentsRBACIntegrationTests(APITestCase):
    def setUp(self):
        # Clear permissions cache to avoid leakage
        cache.clear()

        # 1. Ensure CRMResource for Payments exists
        self.resource, _ = CRMResource.objects.get_or_create(
            codename="payments",
            defaults={"name": "Payments"}
        )

        # 2. Set up default roles
        self.admin_role, _ = Role.objects.get_or_create(
            name="Administrator",
            defaults={"is_system": True, "description": "Admin"}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name="Manager",
            defaults={"is_system": True, "description": "Manager"}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name="Salesperson",
            defaults={"is_system": True, "description": "Salesperson"}
        )

        # Clear any existing permission configurations for these roles
        RolePermission.objects.filter(role__in=[self.admin_role, self.manager_role, self.sales_role]).delete()

        # 3. Configure permissions matrix
        # Admin gets full access (ALL)
        for act in ["VIEW", "CREATE", "EDIT", "DELETE"]:
            RolePermission.objects.create(role=self.admin_role, resource=self.resource, action=act, scope="ALL")
            RolePermission.objects.create(role=self.manager_role, resource=self.resource, action=act, scope="ALL")

        # Salesperson gets OWN visibility and editing, no assignment permission
        RolePermission.objects.create(role=self.sales_role, resource=self.resource, action="VIEW", scope="OWN")
        RolePermission.objects.create(role=self.sales_role, resource=self.resource, action="CREATE", scope="OWN")
        RolePermission.objects.create(role=self.sales_role, resource=self.resource, action="EDIT", scope="OWN")

        # 4. Create testing users
        self.admin_user = User.objects.create_superuser('admin_user', 'admin@example.com', 'pass')
        self.manager_user = User.objects.create_user('manager_user', 'manager@example.com', 'pass')
        self.sales_a = User.objects.create_user('sales_a', 'sales_a@example.com', 'pass')
        self.sales_b = User.objects.create_user('sales_b', 'sales_b@example.com', 'pass')

        # Connect profiles to roles explicitly
        self.admin_profile = UserProfile.objects.get(user=self.admin_user)
        self.admin_profile.role = self.admin_role
        self.admin_profile.save()
        self.admin_user = User.objects.get(pk=self.admin_user.pk)

        self.manager_profile = UserProfile.objects.get(user=self.manager_user)
        self.manager_profile.role = self.manager_role
        self.manager_profile.save()
        self.manager_user = User.objects.get(pk=self.manager_user.pk)

        self.sales_a_profile = UserProfile.objects.get(user=self.sales_a)
        self.sales_a_profile.role = self.sales_role
        self.sales_a_profile.save()
        self.sales_a = User.objects.get(pk=self.sales_a.pk)

        self.sales_b_profile = UserProfile.objects.get(user=self.sales_b)
        self.sales_b_profile.role = self.sales_role
        self.sales_b_profile.save()
        self.sales_b = User.objects.get(pk=self.sales_b.pk)

        # 5. Setup basic models
        self.company_a = Company.objects.create(name="A Corp")
        self.company_b = Company.objects.create(name="B Corp")
        
        self.lead_a = Lead.objects.create(full_name="Lead A", phone="+1", email="a@a.com")
        self.lead_b = Lead.objects.create(full_name="Lead B", phone="+2", email="b@b.com")

        self.contact_a = Contact.objects.create(full_name="Contact A", phone_number="+111", email="a@a.com", company=self.company_a)
        self.contact_b = Contact.objects.create(full_name="Contact B", phone_number="+222", email="b@b.com", company=self.company_b)

        self.opp_a = Opportunity.objects.create(
            name="Opp A",
            company=self.company_a,
            source_lead=self.lead_a,
            primary_contact=self.contact_a,
            assigned_salesperson=self.sales_a,
            amount=5000.0,
            stage="CLOSED_WON",
            expected_close_date=date.today()
        )
        self.opp_b = Opportunity.objects.create(
            name="Opp B",
            company=self.company_b,
            source_lead=self.lead_b,
            primary_contact=self.contact_b,
            assigned_salesperson=self.sales_b,
            amount=8000.0,
            stage="CLOSED_WON",
            expected_close_date=date.today()
        )

        # 6. Create test payments
        self.payment_a = Payment.objects.create(
            invoice_number="INV-001",
            company=self.company_a,
            opportunity=self.opp_a,
            total_amount=5000.0,
            assigned_salesperson=self.sales_a
        )
        self.payment_b = Payment.objects.create(
            invoice_number="INV-002",
            company=self.company_b,
            opportunity=self.opp_b,
            total_amount=8000.0,
            assigned_salesperson=self.sales_b
        )

        self.list_url = reverse('payment-list')

    def detail_url(self, pk):
        return reverse('payment-detail', kwargs={'pk': pk})

    # --- 1. Administrator Verification ---
    def test_admin_full_payments_access(self):
        """Verify Administrator role bypasses all scoping filters and can view/edit any record."""
        self.client.force_authenticate(user=self.admin_user)

        # Can view all payments
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 2)

        # Can retrieve any payment
        response = self.client.get(self.detail_url(self.payment_b.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Can edit any payment
        response = self.client.patch(self.detail_url(self.payment_b.pk), data={"notes": "Admin Updated notes"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- 2. Manager Verification ---
    def test_manager_full_payments_access(self):
        """Verify Manager role bypasses scoping filters and can manage all records."""
        self.client.force_authenticate(user=self.manager_user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 2)

        response = self.client.get(self.detail_url(self.payment_a.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- 3. Salesperson Scoping Verification (OWN vs ALL) ---
    def test_salesperson_scoped_list_and_detail(self):
        """Verify Salesperson only views their assigned payments, other payments return 404."""
        self.client.force_authenticate(user=self.sales_a)

        # List shows only payment_a
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)
        self.assertEqual(response.data["data"]["results"][0]["id"], self.payment_a.pk)

        # Retrieve own payment works
        response = self.client.get(self.detail_url(self.payment_a.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Retrieve payment belonging to Salesperson B returns 404
        response = self.client.get(self.detail_url(self.payment_b.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_salesperson_scoped_update(self):
        """Verify Salesperson can edit own payments, but editing others returns 404."""
        self.client.force_authenticate(user=self.sales_a)

        # Edit own succeeds
        response = self.client.patch(self.detail_url(self.payment_a.pk), data={"notes": "Salesperson Updated Notes"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Edit others returns 404
        response = self.client.patch(self.detail_url(self.payment_b.pk), data={"notes": "Hack Attempt"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- 4. Assignment Override Verification ---
    def test_salesperson_assignment_override_on_create(self):
        """Verify that a Salesperson attempting to assign a new payment to B is overridden to themselves."""
        self.client.force_authenticate(user=self.sales_a)

        payload = {
            "company": self.company_a.pk,
            "opportunity": self.opp_a.pk,
            "total_amount": 1000.0,
            "amount_received": 500.0,
            "payment_method": "CASH",
            "payment_date": str(date.today()),
            "assigned_salesperson": self.sales_b.pk
        }
        
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        payment_id = response.data["data"]["id"]
        created_payment = Payment.objects.get(pk=payment_id)
        self.assertEqual(created_payment.assigned_salesperson, self.sales_a)

    def test_salesperson_assignment_preserved_on_update(self):
        """Verify that a Salesperson cannot reassign an existing payment to B (assignment is preserved)."""
        self.client.force_authenticate(user=self.sales_a)

        payload = {
            "assigned_salesperson": self.sales_b.pk
        }
        
        response = self.client.patch(self.detail_url(self.payment_a.pk), data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify the assignee remains Sales A
        self.payment_a.refresh_from_db()
        self.assertEqual(self.payment_a.assigned_salesperson, self.sales_a)
