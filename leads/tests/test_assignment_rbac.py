from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.core.cache import cache

from accounts.models import Organization
from leads.models import Lead, UserProfile
from opportunities.models import Opportunity
from contacts.models import Contact
from companies.models import Company
from roles.models import Role, CRMResource, RolePermission

User = get_user_model()

class AssignmentRBACEnforcementTests(APITestCase):
    def setUp(self):
        cache.clear()

        # 1. Create resources
        self.leads_res, _ = CRMResource.objects.get_or_create(codename="leads", defaults={"name": "Leads"})
        self.opps_res, _ = CRMResource.objects.get_or_create(codename="opportunities", defaults={"name": "Opportunities"})
        self.contacts_res, _ = CRMResource.objects.get_or_create(codename="contacts", defaults={"name": "Contacts"})
        self.companies_res, _ = CRMResource.objects.get_or_create(codename="companies", defaults={"name": "Companies"})

        # 2. Setup roles
        self.sales_role, _ = Role.objects.get_or_create(name="Salesperson", defaults={"description": "Salesperson"})
        self.manager_role, _ = Role.objects.get_or_create(name="Manager", defaults={"description": "Manager"})
        self.admin_role, _ = Role.objects.get_or_create(name="Administrator", defaults={"description": "Admin"})

        RolePermission.objects.filter(role__in=[self.sales_role, self.manager_role, self.admin_role]).delete()

        # Salesperson: ASSIGN=OWN for all resources
        for res in [self.leads_res, self.opps_res, self.contacts_res, self.companies_res]:
            RolePermission.objects.create(role=self.sales_role, resource=res, action="VIEW", scope="OWN")
            RolePermission.objects.create(role=self.sales_role, resource=res, action="CREATE", scope="OWN")
            RolePermission.objects.create(role=self.sales_role, resource=res, action="EDIT", scope="OWN")
            RolePermission.objects.create(role=self.sales_role, resource=res, action="ASSIGN", scope="OWN")

        # Manager: ASSIGN=ALL for all resources
        for res in [self.leads_res, self.opps_res, self.contacts_res, self.companies_res]:
            RolePermission.objects.create(role=self.manager_role, resource=res, action="VIEW", scope="ALL")
            RolePermission.objects.create(role=self.manager_role, resource=res, action="CREATE", scope="ALL")
            RolePermission.objects.create(role=self.manager_role, resource=res, action="EDIT", scope="ALL")
            RolePermission.objects.create(role=self.manager_role, resource=res, action="ASSIGN", scope="ALL")

        # Admin: ASSIGN=ALL for all resources
        for res in [self.leads_res, self.opps_res, self.contacts_res, self.companies_res]:
            RolePermission.objects.create(role=self.admin_role, resource=res, action="VIEW", scope="ALL")
            RolePermission.objects.create(role=self.admin_role, resource=res, action="CREATE", scope="ALL")
            RolePermission.objects.create(role=self.admin_role, resource=res, action="EDIT", scope="ALL")
            RolePermission.objects.create(role=self.admin_role, resource=res, action="ASSIGN", scope="ALL")

        # 3. Organization
        self.org = Organization.objects.create(name="Test Organization", is_active=True)

        # 3. Users
        self.sales_a = User.objects.create_user('sales_a', 'sales_a@example.com', 'pass')
        self.sales_b = User.objects.create_user('sales_b', 'sales_b@example.com', 'pass')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'pass')
        self.admin_user = User.objects.create_superuser('admin_user', 'admin@example.com', 'pass')

        # Link UserProfiles
        self.sales_a.profile.role = self.sales_role
        self.sales_a.profile.organization = self.org
        self.sales_a.profile.save()

        self.sales_b.profile.role = self.sales_role
        self.sales_b.profile.organization = self.org
        self.sales_b.profile.save()

        self.manager.profile.role = self.manager_role
        self.manager.profile.organization = self.org
        self.manager.profile.save()

        # Add manager to Sales Manager group
        from django.contrib.auth.models import Group
        manager_group, _ = Group.objects.get_or_create(name='Sales Manager')
        self.manager.groups.add(manager_group)

        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.user_type = 'ADMIN'
        self.admin_user.profile.organization = self.org
        self.admin_user.profile.save()

        # 4. Existing instances owned by sales_a
        self.lead_a = Lead.objects.create(
            organization=self.org,
            full_name="Lead A", phone="123", company_name="A Corp", assigned_salesperson=self.sales_a
        )
        self.company_a = Company.objects.create(
            organization=self.org,
            name="Company A", phone="123", assigned_salesperson=self.sales_a
        )
        self.contact_a = Contact.objects.create(
            organization=self.org,
            full_name="Contact A", phone_number="123", assigned_salesperson=self.sales_a
        )
        from datetime import date
        self.opp_a = Opportunity.objects.create(
            organization=self.org,
            name="Opp A",
            amount=1000,
            assigned_salesperson=self.sales_a,
            expected_close_date=date(2026, 12, 31),
            primary_contact=self.contact_a,
            company=self.company_a,
            source_lead=self.lead_a
        )

    # --- SALESPERSON TESTS ---

    def test_salesperson_creates_lead_assigned_to_self(self):
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(
            reverse('leads:lead-list'),
            data={"full_name": "New Lead Unique A", "phone": "99999", "company_name": "Unique A Corp", "assigned_salesperson": self.sales_a.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_salesperson_creates_lead_assigned_to_other_fails(self):
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(
            reverse('leads:lead-list'),
            data={"full_name": "New Lead Unique B", "phone": "88888", "company_name": "Unique B Corp", "assigned_salesperson": self.sales_b.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Salespeople can only assign records to themselves", str(response.data))

    def test_salesperson_assigns_lead_to_self(self):
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('leads:lead-assign', kwargs={'pk': self.lead_a.pk})
        response = self.client.post(url, data={"assigned_salesperson": self.sales_a.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_salesperson_assigns_lead_to_other_fails(self):
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('leads:lead-assign', kwargs={'pk': self.lead_a.pk})
        response = self.client.post(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_salesperson_edits_opportunity_owner_to_self(self):
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('opportunities:opportunity-detail', kwargs={'pk': self.opp_a.pk})
        response = self.client.patch(url, data={"assigned_salesperson": self.sales_a.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_salesperson_edits_opportunity_owner_to_other_fails(self):
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('opportunities:opportunity-detail', kwargs={'pk': self.opp_a.pk})
        response = self.client.patch(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_salesperson_creates_contact_assigned_to_self(self):
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(
            reverse('contacts:contact-list'),
            data={"full_name": "New Contact", "phone_number": "999", "assigned_salesperson": self.sales_a.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_salesperson_creates_contact_assigned_to_other_fails(self):
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(
            reverse('contacts:contact-list'),
            data={"full_name": "New Contact", "phone_number": "999", "assigned_salesperson": self.sales_b.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_salesperson_edits_contact_owner_to_other_fails(self):
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('contacts:contact-detail', kwargs={'pk': self.contact_a.pk})
        response = self.client.patch(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_salesperson_creates_company_assigned_to_self(self):
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(
            reverse('companies:company-list'),
            data={"name": "New Company", "phone": "999", "assigned_salesperson": self.sales_a.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_salesperson_creates_company_assigned_to_other_fails(self):
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(
            reverse('companies:company-list'),
            data={"name": "New Company", "phone": "999", "assigned_salesperson": self.sales_b.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_salesperson_edits_company_owner_to_other_fails(self):
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('companies:company-detail', kwargs={'pk': self.company_a.pk})
        response = self.client.patch(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- MANAGER TESTS ---

    def test_manager_can_assign_lead_to_other(self):
        self.client.force_authenticate(user=self.manager)
        url = reverse('leads:lead-assign', kwargs={'pk': self.lead_a.pk})
        response = self.client.post(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_manager_can_reassign_contact(self):
        self.client.force_authenticate(user=self.manager)
        url = reverse('contacts:contact-detail', kwargs={'pk': self.contact_a.pk})
        response = self.client.patch(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_manager_can_reassign_company(self):
        self.client.force_authenticate(user=self.manager)
        url = reverse('companies:company-detail', kwargs={'pk': self.company_a.pk})
        response = self.client.patch(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- ADMIN TESTS ---

    def test_admin_can_reassign_lead(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('leads:lead-assign', kwargs={'pk': self.lead_a.pk})
        response = self.client.post(url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
