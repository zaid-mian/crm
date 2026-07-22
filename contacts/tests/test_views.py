from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from contacts.models import Contact

User = get_user_model()

class ContactViewSetTestCase(APITestCase):
    def setUp(self):
        # 1. Setup Users & Roles
        self.admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='password123')
        
        self.manager = User.objects.create_user(username='salesmanager', email='manager@example.com', password='password123')
        manager_group, _ = Group.objects.get_or_create(name='Sales Manager')
        self.manager.groups.add(manager_group)

        self.sales_a = User.objects.create_user(username='salesperson_a', email='sales_a@example.com', password='password123')
        self.sales_b = User.objects.create_user(username='salesperson_b', email='sales_b@example.com', password='password123')

        # 2. Setup Data
        self.contact_a = Contact.objects.create(
            full_name='Charlie Brown',
            phone_number='+111222',
            email='charlie@example.com',
            company_name='Alpha Corp',
            designation='VP sales',
            assigned_salesperson=self.sales_a
        )
        self.contact_b = Contact.objects.create(
            full_name='Lucy van Pelt',
            phone_number='+333444',
            email='lucy@example.com',
            company_name='Beta Corp',
            designation='Director',
            assigned_salesperson=self.sales_b
        )
        self.contact_unassigned = Contact.objects.create(
            full_name='Linus van Pelt',
            phone_number='+555666',
            email='linus@example.com',
            company_name='Gamma Corp'
        )

        self.list_url = reverse('contacts:contact-list')

    # --- 1. CRUD Success & Failure Tests ---
    def test_contact_list_success(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]["results"]), 3)

    def test_contact_retrieve_success(self):
        self.client.force_authenticate(user=self.admin)
        detail_url = reverse('contacts:contact-detail', kwargs={'pk': self.contact_a.pk})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["full_name"], "Charlie Brown")
        self.assertEqual(response.data["data"]["related_opportunities"], [])

    def test_contact_create_success(self):
        self.client.force_authenticate(user=self.admin)
        payload = {
            "full_name": "Snoopy Dog",
            "phone_number": "+999000",
            "email": "snoopy@example.com",
            "company_name": "Peanuts LLC",
            "designation": "Mascot"
        }
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["full_name"], "Snoopy Dog")

    def test_contact_create_validation_failure(self):
        self.client.force_authenticate(user=self.admin)
        # Duplicate phone number
        payload = {
            "full_name": "Duplicate Contact",
            "phone_number": "+111222",
            "email": "dup@example.com"
        }
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("phone_number", response.data["errors"])

    def test_contact_update_success(self):
        self.client.force_authenticate(user=self.admin)
        detail_url = reverse('contacts:contact-detail', kwargs={'pk': self.contact_a.pk})
        payload = {
            "full_name": "Charlie Brown Jr.",
            "phone_number": "+111222",
            "email": "charlie@example.com",
            "company_name": "Alpha Corp Updated",
            "designation": "VP sales"
        }
        response = self.client.put(detail_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["full_name"], "Charlie Brown Jr.")
        self.assertEqual(response.data["data"]["company_name"], "Alpha Corp Updated")

    def test_contact_soft_delete(self):
        self.client.force_authenticate(user=self.admin)
        detail_url = reverse('contacts:contact-detail', kwargs={'pk': self.contact_a.pk})
        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Check soft deleted record is hidden from default viewset queries
        self.contact_a.refresh_from_db()
        self.assertTrue(self.contact_a.is_deleted)
        
        response = self.client.get(self.list_url)
        self.assertEqual(len(response.data["data"]["results"]), 2)

    # --- 2. RBAC Scoping Tests ---
    def test_rbac_salesperson_visibility(self):
        # Salesperson A sees only contact_a
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.get(self.list_url)
        self.assertEqual(len(response.data["data"]["results"]), 1)
        self.assertEqual(response.data["data"]["results"][0]["id"], self.contact_a.id)

    def test_rbac_manager_and_admin_visibility(self):
        # Manager sees all contacts
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(self.list_url)
        self.assertEqual(len(response.data["data"]["results"]), 3)

        # Admin sees all contacts
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(len(response.data["data"]["results"]), 3)

    def test_rbac_salesperson_retrieve_forbidden(self):
        # Salesperson A tries to view Salesperson B's contact
        self.client.force_authenticate(user=self.sales_a)
        detail_url = reverse('contacts:contact-detail', kwargs={'pk': self.contact_b.pk})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- 3. Filter, Search, Ordering & Pagination Tests ---
    def test_filter_by_company(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f"{self.list_url}?company_name=Alpha")
        self.assertEqual(len(response.data["data"]["results"]), 1)
        self.assertEqual(response.data["data"]["results"][0]["id"], self.contact_a.id)

    def test_search_by_name(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f"{self.list_url}?search=Lucy")
        self.assertEqual(len(response.data["data"]["results"]), 1)
        self.assertEqual(response.data["data"]["results"][0]["id"], self.contact_b.id)

    def test_pagination_envelope(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        pagination_data = response.data["data"]["pagination"]
        self.assertEqual(pagination_data["page"], 1)
        self.assertEqual(pagination_data["total_items"], 3)
        self.assertIn("results", response.data["data"])

    # --- 4. Query Efficiency (N+1 check) ---
    def test_query_efficiency_on_contact_listings(self):
        """Verify listing endpoint avoids N+1 queries by pre-fetching salesperson data."""
        self.client.force_authenticate(user=self.admin)
        
        # Standard execution should execute exactly 2 queries:
        # 1. Page count query
        # 2. Results fetch query (which pre-fetches the user relation)
        with self.assertNumQueries(2):
            response = self.client.get(self.list_url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
