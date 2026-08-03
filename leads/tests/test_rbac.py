from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.core.cache import cache

from leads.models import Lead, UserProfile
from roles.models import Role, CRMResource, RolePermission

User = get_user_model()

class LeadsRBACIntegrationTests(APITestCase):
    def setUp(self):
        # Clear permissions cache to avoid leakage
        cache.clear()

        # 1. Ensure CRMResource for Leads exists
        self.resource, _ = CRMResource.objects.get_or_create(
            codename="leads",
            defaults={"name": "Leads"}
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

        # Clear any existing permission configurations for these roles to be clean
        RolePermission.objects.filter(role__in=[self.admin_role, self.manager_role, self.sales_role]).delete()

        # 3. Configure permissions matrix
        # Admin gets full access (ALL)
        for act in ["VIEW", "CREATE", "EDIT", "ASSIGN", "APPROVE"]:
            RolePermission.objects.create(role=self.admin_role, resource=self.resource, action=act, scope="ALL")

        # Manager gets full access (ALL)
        for act in ["VIEW", "CREATE", "EDIT", "ASSIGN", "APPROVE"]:
            RolePermission.objects.create(role=self.manager_role, resource=self.resource, action=act, scope="ALL")

        # Salesperson gets OWN visibility and editing, no assignment or conversion permission
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

        # 5. Create test leads
        self.lead_a = Lead.objects.create(
            full_name="Lead Sales A",
            phone="+1111",
            company_name="A Corp",
            assigned_salesperson=self.sales_a
        )
        self.lead_b = Lead.objects.create(
            full_name="Lead Sales B",
            phone="+2222",
            company_name="B Corp",
            assigned_salesperson=self.sales_b
        )
        self.lead_unassigned = Lead.objects.create(
            full_name="Lead Unassigned",
            phone="+3333",
            company_name="C Corp"
        )

        self.list_url = reverse('leads:lead-list')

    def detail_url(self, pk):
        return reverse('leads:lead-detail', kwargs={'pk': pk})

    # --- 1. Administrator Verification ---
    def test_admin_full_leads_access(self):
        """Verify Administrator role bypasses all scoping filters and can view/edit/assign/convert any record."""
        self.client.force_authenticate(user=self.admin_user)

        # Can view all leads
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 3)

        # Can retrieve any lead
        response = self.client.get(self.detail_url(self.lead_b.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Can update salesperson assignment
        assign_url = reverse('leads:lead-assign', kwargs={'pk': self.lead_unassigned.pk})
        response = self.client.post(assign_url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Can convert lead
        convert_url = reverse('leads:lead-convert', kwargs={'pk': self.lead_a.pk})
        response = self.client.post(convert_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- 2. Manager Verification ---
    def test_manager_full_leads_access(self):
        """Verify Manager role bypasses scoping filters and can manage all records."""
        self.client.force_authenticate(user=self.manager_user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 3)

        response = self.client.get(self.detail_url(self.lead_a.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assign_url = reverse('leads:lead-assign', kwargs={'pk': self.lead_unassigned.pk})
        response = self.client.post(assign_url, data={"assigned_salesperson": self.sales_a.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- 3. Salesperson Scoping Verification (OWN vs ALL) ---
    def test_salesperson_scoped_list_and_detail(self):
        """Verify Salesperson only views their assigned leads, other leads return 404."""
        self.client.force_authenticate(user=self.sales_a)

        # List shows only lead_a
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)
        self.assertEqual(response.data["data"]["results"][0]["id"], self.lead_a.pk)

        # Retrieve own lead works
        response = self.client.get(self.detail_url(self.lead_a.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Retrieve lead belonging to Salesperson B returns 404
        response = self.client.get(self.detail_url(self.lead_b.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_salesperson_scoped_update(self):
        """Verify Salesperson can edit own leads, but editing others returns 404."""
        self.client.force_authenticate(user=self.sales_a)

        # Edit own succeeds
        response = self.client.patch(self.detail_url(self.lead_a.pk), data={"full_name": "Updated Name"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Edit others returns 404
        response = self.client.patch(self.detail_url(self.lead_b.pk), data={"full_name": "Hack Attempt"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- 4. Custom Actions Authorization Verification ---
    def test_salesperson_assign_permission_denied(self):
        """Verify Salesperson cannot access the assign endpoint (returns 403)."""
        self.client.force_authenticate(user=self.sales_a)
        assign_url = reverse('leads:lead-assign', kwargs={'pk': self.lead_a.pk})

        response = self.client.post(assign_url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_salesperson_convert_permission_denied(self):
        """Verify Salesperson cannot access the convert endpoint (returns 403)."""
        self.client.force_authenticate(user=self.sales_a)
        convert_url = reverse('leads:lead-convert', kwargs={'pk': self.lead_a.pk})

        response = self.client.post(convert_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- 5. Assignment Override Verification ---
    def test_salesperson_assignment_override_on_create(self):
        """Verify that a Salesperson attempting to assign a new lead to someone else is overridden to themselves."""
        self.client.force_authenticate(user=self.sales_a)

        payload = {
            "full_name": "New Scoped Lead",
            "company_name": "Test Company",
            "phone": "+9999",
            "assigned_salesperson": self.sales_b.pk  # Sales A tries to assign to Sales B
        }
        
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify the lead is created but assigned to Sales A
        lead_id = response.data["data"]["id"]
        created_lead = Lead.objects.get(pk=lead_id)
        self.assertEqual(created_lead.assigned_salesperson, self.sales_a)
