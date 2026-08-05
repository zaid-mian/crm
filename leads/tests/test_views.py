from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from leads.models import Lead

User = get_user_model()

class LeadViewSetTestCase(APITestCase):
    def setUp(self):
        # Create user roles
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'adminpass')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'managerpass')
        
        # Ensure Sales Manager group exists and manager is added
        manager_group, _ = Group.objects.get_or_create(name='Sales Manager')
        self.manager.groups.add(manager_group)
        self.manager.is_staff = True
        self.manager.save()

        self.sales_a = User.objects.create_user('sales_a', 'sales_a@example.com', 'salesapass')
        self.sales_b = User.objects.create_user('sales_b', 'sales_b@example.com', 'salesbpass')

        # Create active leads
        self.lead_a = Lead.objects.create(
            full_name="Alice Smith", phone="+11111", email="alice@example.com", company_name="A Inc", assigned_salesperson=self.sales_a
        )
        self.lead_b = Lead.objects.create(
            full_name="Bob Jones", phone="+22222", email="bob@example.com", company_name="B Inc", assigned_salesperson=self.sales_b
        )
        self.lead_unassigned = Lead.objects.create(
            full_name="Charlie Brown", phone="+33333", email="charlie@example.com", company_name="C Inc"
        )

        # Standard list URL
        self.list_url = reverse('leads:lead-list')

    # Helper method for detailing url
    def detail_url(self, pk):
        return reverse('leads:lead-detail', kwargs={'pk': pk})

    # --- 1. Standard Response Format Tests ---
    def test_api_success_response_format(self):
        """Verify success response conforms to standardized success envelope."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.detail_url(self.lead_a.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check envelope layout
        self.assertTrue(response.data["success"])
        self.assertIn("message", response.data)
        self.assertIn("data", response.data)
        self.assertEqual(response.data["data"]["id"], self.lead_a.pk)

    def test_api_error_response_format_on_invalid_lost(self):
        """Verify validation errors conform to standardized error envelope."""
        self.client.force_authenticate(user=self.admin)
        
        # Lost endpoint requires reason
        response = self.client.post(reverse('leads:lead-lost', kwargs={'pk': self.lead_a.pk}), data={})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Check error envelope
        self.assertFalse(response.data["success"])
        self.assertIn("message", response.data)
        self.assertIn("errors", response.data)
        self.assertIn("lost_reason", response.data["errors"])

    # --- 2. Permission Matrix Tests ---
    def test_permission_anonymous_denied(self):
        """Verify anonymous users are rejected."""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN) # Or 401 depending on auth configuration

    def test_permission_salesperson_scopes_leads(self):
        """Verify salespeople only retrieve their assigned leads, and others return 404."""
        # Authenticated as Salesperson A
        self.client.force_authenticate(user=self.sales_a)
        
        # Can list A's leads
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)
        self.assertEqual(response.data["data"]["results"][0]["id"], self.lead_a.pk)

        # Can retrieve own lead
        response_detail = self.client.get(self.detail_url(self.lead_a.pk))
        self.assertEqual(response_detail.status_code, status.HTTP_200_OK)

        # Gets 404 retrieving B's lead
        response_b = self.client.get(self.detail_url(self.lead_b.pk))
        self.assertEqual(response_b.status_code, status.HTTP_404_NOT_FOUND)

    def test_permission_managers_and_admins_view_all(self):
        """Verify Managers and Admins bypass row-level lead constraints."""
        for user in [self.manager, self.admin]:
            self.client.force_authenticate(user=user)
            response = self.client.get(self.list_url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["data"]["pagination"]["total_items"], 3)

    # --- 3. CRUD Edge Cases ---
    def test_deleted_endpoint_disabled(self):
        """Verify permanent deletion endpoint returns 405 Method Not Allowed."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.detail_url(self.lead_a.pk))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_create_validation_missing_fields(self):
        """Verify creating a lead validation errors on missing required fields."""
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(self.list_url, data={
            "phone": "+12345" # Missing full_name and company_name
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("full_name", response.data["errors"])
        self.assertIn("company_name", response.data["errors"])

    def test_update_validation_invalid_enum(self):
        """Verify updating a lead validates choices correctly."""
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.patch(self.detail_url(self.lead_a.pk), data={
            "source": "INVALID_SOURCE_VALUE"
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("source", response.data["errors"])

    def test_invalid_uuid_or_integer_primary_key(self):
        """Verify retrieving an invalid primary key ID formats as 404."""
        self.client.force_authenticate(user=self.admin)
        # Assuming BigAutoField, 999999 is non-existent
        response = self.client.get(self.detail_url(999999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- 4. Filtering, Sorting, Search, and Pagination ---
    def test_custom_pagination_structure(self):
        """Verify response contains custom pagination structure."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        pagination = response.data["data"]["pagination"]
        self.assertEqual(pagination["page"], 1)
        self.assertEqual(pagination["page_size"], 20)
        self.assertEqual(pagination["total_items"], 3)
        self.assertIn("total_pages", pagination)

    def test_filtering_by_status(self):
        """Verify status filter functions correctly."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f"{self.list_url}?status=NEW")
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 3)

        response_empty = self.client.get(f"{self.list_url}?status=LOST")
        self.assertEqual(response_empty.data["data"]["pagination"]["total_items"], 0)

    def test_lead_code_search_parsing(self):
        """Verify search maps dynamic property 'lead_code' patterns successfully."""
        self.client.force_authenticate(user=self.admin)
        lead_code = self.lead_b.lead_code # formats as LD-000002 (since ID=2)
        
        response = self.client.get(f"{self.list_url}?search={lead_code}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.lead_b.pk)

    def test_general_search(self):
        """Verify text-based search queries correctly."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f"{self.list_url}?search=Alice")
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)
        self.assertEqual(response.data["data"]["results"][0]["id"], self.lead_a.pk)

    # --- 5. Workflow Action & Idempotency Tests ---
    def test_action_assign_permissions(self):
        """Verify only Admin and Sales Manager can access assign endpoint."""
        assign_url = reverse('leads:lead-assign', kwargs={'pk': self.lead_unassigned.pk})
        
        # Salesperson gets 403
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(assign_url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Admin succeeds
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(assign_url, data={"assigned_salesperson": self.sales_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_action_convert_permissions(self):
        """Verify only Admin and Sales Manager can convert leads."""
        convert_url = reverse('leads:lead-convert', kwargs={'pk': self.lead_a.pk})

        self.client.force_authenticate(user=self.sales_a)
        response = self.client.post(convert_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.manager)
        response = self.client.post(convert_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_action_convert_unassigned_lead_fails(self):
        """Verify converting unassigned leads fails with 400 Bad Request."""
        convert_url = reverse('leads:lead-convert', kwargs={'pk': self.lead_unassigned.pk})
        self.client.force_authenticate(user=self.manager)
        response = self.client.post(convert_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("Assign the lead to a salesperson before converting it.", str(response.data["errors"]))

    def test_action_lost_workflow_validation(self):
        """Verify lost workflow transition constraints."""
        self.client.force_authenticate(user=self.sales_a)
        lost_url = reverse('leads:lead-lost', kwargs={'pk': self.lead_a.pk})
        
        # Missing lost reason in request body
        response = self.client.post(lost_url, data={})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Successful request
        response = self.client.post(lost_url, data={
            "lost_reason": Lead.LostReason.BUDGET_TOO_HIGH,
            "lost_notes": "Pricing barrier."
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], Lead.LeadStatus.LOST)

    def test_stats_scoped_correctly(self):
        """Verify stats endpoint aggregates only over authorized visibility scope."""
        stats_url = reverse('leads:lead-stats')
        
        # Salesperson A sees 1 lead
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.get(stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["total_leads"], 1)

        # Admin sees 3 leads
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["total_leads"], 3)

    # --- 6. Query Efficiency / N+1 Avoidance Tests ---
    def test_query_efficiency_on_lead_listings(self):
        """Verify listing endpoint avoids N+1 queries by pre-fetching salesperson data."""
        self.client.force_authenticate(user=self.admin)
        
        # Standard execution should execute exactly 2 queries:
        # 1. Page count query
        # 2. Results fetch query (which pre-fetches the user relation)
        with self.assertNumQueries(2):
            response = self.client.get(self.list_url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data["data"]["results"]), 3)

    def test_view_create_lead_missing_phone_fails(self):
        """Verify lead creation fails when phone is missing."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "full_name": "Email Only Lead",
            "company_name": "Acme Inc",
            "email": "onlyemail@example.com"
        }
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_view_create_lead_with_phone_only_success(self):
        """Verify lead creation succeeds with phone only (email optional)."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "full_name": "Phone Only Lead",
            "company_name": "Acme Inc",
            "phone": "+9999"
        }
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["full_name"], "Phone Only Lead")
        self.assertIsNone(response.data["data"]["email"])

    def test_view_create_lead_with_neither_fails(self):
        """Verify lead creation fails if both email and phone are empty."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "full_name": "Invalid Lead",
            "company_name": "Acme Inc"
        }
        response = self.client.post(self.list_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_view_action_contacted_success(self):
        """Verify explicit POST to /contacted/ transitions lead to CONTACTED status."""
        self.client.force_authenticate(user=self.sales_a)
        contacted_url = reverse('leads:lead-contacted', kwargs={'pk': self.lead_a.pk})
        
        response = self.client.post(contacted_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["status"], Lead.LeadStatus.CONTACTED)

    def test_view_action_convert_populates_converted_at(self):
        """Verify conversion view action returns converted_at value."""
        self.client.force_authenticate(user=self.manager)
        convert_url = reverse('leads:lead-convert', kwargs={'pk': self.lead_a.pk})
        
        response = self.client.post(convert_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["data"]["converted_at"])
