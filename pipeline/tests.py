from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from leads.models import Lead
from opportunities.models import Opportunity
from companies.models import Company
from contacts.models import Contact

User = get_user_model()

class PipelineViewSetTestCase(APITestCase):
    def setUp(self):
        # Create users
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pwd')
        self.sales_a = User.objects.create_user('sales_a', 'sales_a@example.com', 'pwd')
        self.sales_b = User.objects.create_user('sales_b', 'sales_b@example.com', 'pwd')

        # Create active leads (unconverted)
        self.lead_a = Lead.objects.create(
            full_name="Lead A",
            company_name="Company A",
            phone="+111",
            email="leada@example.com",
            status=Lead.LeadStatus.NEW,
            assigned_salesperson=self.sales_a
        )
        self.lead_b = Lead.objects.create(
            full_name="Lead B",
            company_name="Company B",
            phone="+222",
            status=Lead.LeadStatus.NEW,
            assigned_salesperson=self.sales_b
        )
        self.lead_unassigned = Lead.objects.create(
            full_name="Lead Unassigned",
            company_name="Company C",
            phone="+333",
            status=Lead.LeadStatus.NEW
        )

        # Create an Opportunity
        self.company = Company.objects.create(
            name="Delta Corp",
            assigned_salesperson=self.sales_a
        )
        self.contact = Contact.objects.create(
            full_name="John Contact",
            company=self.company,
            phone_number="+444",
            assigned_salesperson=self.sales_a
        )
        from django.utils import timezone
        self.opp = Opportunity.objects.create(
            name="Deal A",
            company=self.company,
            primary_contact=self.contact,
            source_lead=self.lead_a,  # Mock link for testing
            assigned_salesperson=self.sales_a,
            stage='QUALIFICATION',
            amount=5000.00,
            expected_close_date=timezone.now().date()
        )

        self.list_url = reverse('pipeline:pipeline-list')
        self.move_url = reverse('pipeline:pipeline-move')

    def test_pipeline_list_rbac_scoping(self):
        """Verify Pipeline listing scopes cards based on user roles."""
        # 1. Admin should see all cards (unconverted leads and opportunities)
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 3 unconverted leads (lead_a, lead_b, lead_unassigned) + 1 opportunity (opp) = 4 cards
        self.assertEqual(len(response.data["data"]), 4)

        # 2. Sales A should see only their cards (lead_a, opp)
        self.client.force_authenticate(user=self.sales_a)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 2)
        # Check entity types
        entity_types = [card["entity_type"] for card in response.data["data"]]
        self.assertIn("lead", entity_types)
        self.assertIn("opportunity", entity_types)

    def test_move_lead_status_transitions(self):
        """Verify Lead moves successfully through unconverted stages."""
        self.client.force_authenticate(user=self.sales_a)
        
        # 1. Move NEW -> CONTACTED
        payload = {
            "entity_type": "lead",
            "id": self.lead_a.id,
            "target_stage": "CONTACTED"
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.status, 'CONTACTED')

        # 2. Move CONTACTED -> FOLLOW_UP
        payload["target_stage"] = "FOLLOW_UP"
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.status, 'FOLLOW_UP')

    def test_move_lead_to_qualified_converts(self):
        """Verify moving a Lead to QUALIFIED automatically converts the Lead and returns Opportunity."""
        self.client.force_authenticate(user=self.sales_a)
        payload = {
            "entity_type": "lead",
            "id": self.lead_a.id,
            "target_stage": "QUALIFIED"
        }
        # Execute move
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check response details (Opportunity card DTO)
        self.assertEqual(response.data["data"]["entity_type"], "opportunity")
        self.assertEqual(response.data["data"]["stage"], "QUALIFIED")
        self.assertIsNotNone(response.data["data"]["company_id"])
        self.assertIsNotNone(response.data["data"]["primary_contact_id"])
        
        # Verify Lead state in database
        self.lead_a.refresh_from_db()
        self.assertTrue(self.lead_a.is_converted)
        self.assertEqual(self.lead_a.status, 'CONVERTED')
        self.assertIsNotNone(self.lead_a.converted_opportunity)

    def test_move_opportunity_stages(self):
        """Verify Opportunity stages update correctly."""
        self.client.force_authenticate(user=self.sales_a)
        
        # Move QUALIFIED -> PROPOSAL
        payload = {
            "entity_type": "opportunity",
            "id": self.opp.id,
            "target_stage": "PROPOSAL"
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, 'PROPOSAL')

        # Move PROPOSAL -> NEGOTIATION
        payload["target_stage"] = "NEGOTIATION"
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, 'NEGOTIATION')

        # Move NEGOTIATION -> WON
        payload["target_stage"] = "WON"
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, 'CLOSED_WON')

    def test_move_to_lost(self):
        """Verify both Leads and Opportunities can transition to LOST terminal column."""
        # 1. Lead to LOST
        self.client.force_authenticate(user=self.sales_a)
        payload = {
            "entity_type": "lead",
            "id": self.lead_a.id,
            "target_stage": "LOST"
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.status, 'LOST')

        # 2. Opportunity to LOST
        payload = {
            "entity_type": "opportunity",
            "id": self.opp.id,
            "target_stage": "LOST"
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, 'CLOSED_LOST')

    def test_validation_unassigned_lead_blocked(self):
        """Verify unassigned Leads cannot be moved past NEW."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "entity_type": "lead",
            "id": self.lead_unassigned.id,
            "target_stage": "CONTACTED"
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Assign the lead to a salesperson before moving it from NEW.", response.data["message"])

    def test_validation_unidirectional_promotion_blocked(self):
        """Verify moving Opportunity back to a Lead stage returns 400 Bad Request."""
        self.client.force_authenticate(user=self.sales_a)
        payload = {
            "entity_type": "opportunity",
            "id": self.opp.id,
            "target_stage": "CONTACTED"
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Opportunities cannot be moved to Lead-only stages.", response.data["message"])

    def test_validation_terminal_stage_lock(self):
        """Verify salespeople cannot move closed/lost entities."""
        # Setup Opportunity in terminal WON stage
        self.opp.stage = 'CLOSED_WON'
        self.opp.save()

        self.client.force_authenticate(user=self.sales_a)
        payload = {
            "entity_type": "opportunity",
            "id": self.opp.id,
            "target_stage": "PROPOSAL"
        }
        # Salesperson update should be blocked
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Closed opportunities are locked and cannot be modified by salespeople.", response.data["message"])

        # Admin update should pass
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
