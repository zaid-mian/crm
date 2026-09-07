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

        # Setup standard pipeline stages for test records
        from pipeline.models import PipelineStage
        self.stage_new = PipelineStage.objects.get(order=0)
        self.stage_contacted = PipelineStage.objects.get(order=1)
        self.stage_followup = PipelineStage.objects.get(order=2)
        self.stage_conversion = PipelineStage.objects.get(order=3)
        self.stage_proposal = PipelineStage.objects.get(order=4)
        self.stage_negotiation = PipelineStage.objects.get(order=5)
        self.stage_won = PipelineStage.objects.get(order=6)
        self.stage_lost = PipelineStage.objects.get(order=7)

        self.lead_a.pipeline_stage = self.stage_new
        self.lead_a.save()
        self.lead_b.pipeline_stage = self.stage_new
        self.lead_b.save()
        self.lead_unassigned.pipeline_stage = self.stage_new
        self.lead_unassigned.save()
        self.opp.pipeline_stage = self.stage_conversion
        self.opp.save()

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

    def test_move_lead_by_stage_id(self):
        """Verify Lead moves successfully using target_stage_id."""
        self.client.force_authenticate(user=self.sales_a)
        
        # Move Lead to Contacted stage (order=1)
        payload = {
            "entity_type": "lead",
            "id": self.lead_a.id,
            "target_stage_id": self.stage_contacted.id
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.pipeline_stage, self.stage_contacted)
        self.assertEqual(self.lead_a.status, 'CONTACTED')

    def test_move_lead_to_conversion_stage_type(self):
        """Verify Lead converts to Opportunity when moved to stage_type=CONVERSION."""
        self.client.force_authenticate(user=self.sales_a)
        payload = {
            "entity_type": "lead",
            "id": self.lead_a.id,
            "target_stage_id": self.stage_conversion.id
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["entity_type"], "opportunity")
        
        self.lead_a.refresh_from_db()
        self.assertTrue(self.lead_a.is_converted)
        self.assertEqual(self.lead_a.converted_opportunity.pipeline_stage, self.stage_conversion)

    def test_pipeline_crud_admin(self):
        """Verify Admin can create, read, update, and delete Pipelines."""
        self.client.force_authenticate(user=self.admin)
        
        # 1. Create
        url = reverse('pipeline:pipelines-list')
        payload = {"name": "New Pipeline", "description": "Dynamic custom pipeline"}
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        pipeline_id = response.data["id"]

        # 2. List/Detail
        response = self.client.get(reverse('pipeline:pipelines-detail', args=[pipeline_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "New Pipeline")

        # 3. Update
        response = self.client.patch(reverse('pipeline:pipelines-detail', args=[pipeline_id]), data={"name": "Updated Name"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated Name")

        # 4. Delete
        response = self.client.delete(reverse('pipeline:pipelines-detail', args=[pipeline_id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_pipeline_crud_rbac_blocked_for_salesperson(self):
        """Verify salesperson cannot modify Pipelines."""
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('pipeline:pipelines-list')
        payload = {"name": "Blocked Pipeline"}
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_stage_crud_admin(self):
        """Verify Admin can manage stages with validation constraints."""
        self.client.force_authenticate(user=self.admin)
        pipeline_id = self.stage_new.pipeline_id
        
        # 1. Create a normal Opportunity stage
        url = reverse('pipeline:pipeline-stage-list')
        payload = {
            "pipeline": pipeline_id,
            "name": "Demo Stage",
            "entity_type": "OPPORTUNITY",
            "order": 12,
            "stage_type": "NORMAL_OPPORTUNITY",
            "color": "#ffffff"
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        stage_id = response.data["id"]

        # 2. Invalid entity_type/stage_type combination check
        payload_invalid = {
            "pipeline": pipeline_id,
            "name": "Invalid Stage",
            "entity_type": "LEAD",
            "order": 13,
            "stage_type": "CONVERSION"
        }
        response = self.client.post(url, data=payload_invalid)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("CONVERSION stage cannot belong to LEAD.", str(response.data))

        # 3. Duplicate order validation check
        payload_dup_order = {
            "pipeline": pipeline_id,
            "name": "Duplicate Stage",
            "entity_type": "OPPORTUNITY",
            "order": 12,
            "stage_type": "NORMAL_OPPORTUNITY"
        }
        response = self.client.post(url, data=payload_dup_order)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_stage_deletion_active_cards_reassignment(self):
        """Verify deletion locks on stages with active cards, and reassignment flow."""
        self.client.force_authenticate(user=self.admin)
        
        # stage_new has lead_a, lead_b, and lead_unassigned.
        url_detail = reverse('pipeline:pipeline-stage-detail', args=[self.stage_new.id])
        
        # 1. Deletion without reassignment fails
        response = self.client.delete(url_detail)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot delete stage containing active cards.", response.data["message"])

        # 2. Deletion with reassignment moves cards and succeeds
        response = self.client.delete(url_detail, data={"reassign_stage_id": self.stage_contacted.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify cards were reassigned
        self.lead_a.refresh_from_db()
        self.lead_b.refresh_from_db()
        self.assertEqual(self.lead_a.pipeline_stage, self.stage_contacted)
        self.assertEqual(self.lead_b.pipeline_stage, self.stage_contacted)

    def test_lead_creation_auto_pipeline_and_stage(self):
        """Verify Lead creation automatically assigns default pipeline and its first Lead stage."""
        pipeline = self.stage_new.pipeline
        pipeline.is_default = True
        pipeline.save()
        
        self.client.force_authenticate(user=self.sales_a)
        url = reverse('leads:lead-list')
        payload = {
            "full_name": "New Test Lead",
            "company_name": "Test Company",
            "phone": "+99998888",
            "email": "newtestlead@example.com",
            "source": "WEBSITE",
            "priority": "HIGH"
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify default pipeline and stage are set
        lead_id = response.data["data"]["id"]
        lead = Lead.objects.get(pk=lead_id)
        self.assertIsNotNone(lead.pipeline)
        self.assertEqual(lead.pipeline.is_default, True)
        self.assertEqual(lead.pipeline_stage.stage_type, 'NORMAL_LEAD')
        self.assertEqual(lead.pipeline_stage.order, 0)

    def test_pipeline_switching_resets_stage(self):
        """Verify switching a Lead/Opportunity to another pipeline resets its stage to the first compatible stage of target pipeline."""
        from pipeline.models import Pipeline, PipelineStage
        self.client.force_authenticate(user=self.admin)
        
        # Create second pipeline and its stages
        pipeline_b = Pipeline.objects.create(name="Pipeline B", is_default=False)
        stage_b_1 = PipelineStage.objects.create(
            pipeline=pipeline_b,
            name="Draft",
            entity_type='LEAD',
            order=0,
            stage_type='NORMAL_LEAD'
        )
        stage_b_2 = PipelineStage.objects.create(
            pipeline=pipeline_b,
            name="Converted Opp",
            entity_type='OPPORTUNITY',
            order=1,
            stage_type='NORMAL_OPPORTUNITY'
        )
        
        # 1. Switch Lead to Pipeline B
        lead_url = reverse('leads:lead-detail', args=[self.lead_a.id])
        payload = {
            "pipeline": pipeline_b.id
        }
        response = self.client.patch(lead_url, data=payload)

        print("Status:", response.status_code)
        print("Response:", response.data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
                
        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.pipeline, pipeline_b)
        self.assertEqual(self.lead_a.pipeline_stage, stage_b_1) # reset to first compatible stage

        # 2. Switch Opportunity to Pipeline B
        opp_url = reverse('opportunities:opportunity-detail', args=[self.opp.id])
        payload_opp = {
            "pipeline": pipeline_b.id
        }
        response = self.client.patch(opp_url, data=payload_opp)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.pipeline, pipeline_b)
        self.assertEqual(self.opp.pipeline_stage, stage_b_2) # reset to first compatible opportunity stage
        
    def test_pipeline_move_stage_pipeline_mismatch(self):
        """Verify moving a card to a stage belonging to a different pipeline is blocked."""
        from pipeline.models import Pipeline, PipelineStage
        self.client.force_authenticate(user=self.admin)
        
        pipeline_b = Pipeline.objects.create(name="Pipeline B", is_default=False)
        stage_b_1 = PipelineStage.objects.create(
            pipeline=pipeline_b,
            name="Draft",
            entity_type='LEAD',
            order=0,
            stage_type='NORMAL_LEAD'
        )
        
        # Try to move lead_a (currently on default pipeline) to stage_b_1 (on Pipeline B)
        payload = {
            "entity_type": "lead",
            "id": self.lead_a.id,
            "target_stage_id": stage_b_1.id
        }
        response = self.client.post(self.move_url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Target stage does not belong to the lead's active pipeline.", response.data["message"])

    def test_configure_behavior_inference(self ):
        """Verify configure_behavior API endpoint correctly computes and maps behaviors."""
        from pipeline.models import Pipeline, PipelineStage
        self.client.force_authenticate(user=self.admin)
        
        # Create pipeline and stages (no behaviors set)
        p = Pipeline.objects.create(name="Custom P")
        s1 = PipelineStage.objects.create(pipeline=p, name="Lead S1", order=0, entity_type='LEAD', stage_type='NORMAL_LEAD')
        s2 = PipelineStage.objects.create(pipeline=p, name="Conv S2", order=1, entity_type='LEAD', stage_type='NORMAL_LEAD')
        s3 = PipelineStage.objects.create(pipeline=p, name="Opp S3", order=2, entity_type='LEAD', stage_type='NORMAL_LEAD')
        s4 = PipelineStage.objects.create(pipeline=p, name="Won S4", order=3, entity_type='LEAD', stage_type='NORMAL_LEAD')

        url = reverse('pipeline:pipelines-detail', args=[p.id]) + "configure_behavior/"
        payload = {
            "conversion_stage_id": s2.id,
            "won_stage_id": s4.id
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert correct mappings
        s1.refresh_from_db()
        s2.refresh_from_db()
        s3.refresh_from_db()
        s4.refresh_from_db()

        self.assertEqual(s1.entity_type, 'LEAD')
        self.assertEqual(s1.stage_type, 'NORMAL_LEAD')
        self.assertEqual(s2.entity_type, 'OPPORTUNITY')
        self.assertEqual(s2.stage_type, 'CONVERSION')
        self.assertEqual(s3.entity_type, 'OPPORTUNITY')
        self.assertEqual(s3.stage_type, 'NORMAL_OPPORTUNITY')
        self.assertEqual(s4.entity_type, 'OPPORTUNITY')
        self.assertEqual(s4.stage_type, 'WON')

    def test_single_anchor_role_invariants(self):
        """Verify only one Conversion stage can exist in a pipeline."""
        from pipeline.models import Pipeline, PipelineStage
        self.client.force_authenticate(user=self.admin)
        
        p = Pipeline.objects.create(name="Anchor Pipeline")
        s1 = PipelineStage.objects.create(pipeline=p, name="Conv 1", order=0, entity_type='OPPORTUNITY', stage_type='CONVERSION')
        
        # Trying to create another conversion stage fails validation
        url = reverse('pipeline:pipeline-stage-list')
        payload = {
            "pipeline": p.id,
            "name": "Conv 2",
            "entity_type": "OPPORTUNITY",
            "stage_type": "CONVERSION",
            "order": 1
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only one CONVERSION stage can exist per pipeline.", str(response.data))

    def test_universal_boundary_validation_fails(self):
        """Verify boundary recalculation is blocked when active cards exist in shifting boundary stages."""
        from pipeline.models import Pipeline, PipelineStage
        self.client.force_authenticate(user=self.admin)

        p = Pipeline.objects.create(name="Boundary Pipeline")
        s0 = PipelineStage.objects.create(pipeline=p, name="Draft", order=0, entity_type='LEAD', stage_type='NORMAL_LEAD')
        s1 = PipelineStage.objects.create(pipeline=p, name="Lead 1", order=1, entity_type='LEAD', stage_type='NORMAL_LEAD')
        s2 = PipelineStage.objects.create(pipeline=p, name="Conv 2", order=2, entity_type='OPPORTUNITY', stage_type='CONVERSION')
        s3 = PipelineStage.objects.create(pipeline=p, name="Opp 3", order=3, entity_type='OPPORTUNITY', stage_type='NORMAL_OPPORTUNITY')

        # Add active Lead in s1
        lead = Lead.objects.create(
            full_name="Lead Boundary Check",
            company_name="Acme Tech",
            phone="123",
            pipeline=p,
            pipeline_stage=s1,
            assigned_salesperson=self.sales_a
        )

        # Shift conversion stage to s1 (which contains the active lead). This is illegal because s1 would turn into OPPORTUNITY.
        url = reverse('pipeline:pipelines-detail', args=[p.id]) + "configure_behavior/"
        payload = {
            "conversion_stage_id": s1.id
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("would change from Lead to Opportunity while containing active Leads", response.data["message"])

    def test_custom_opportunity_form_builder_and_conversion(self):
        """Verify custom Opportunity form builder template mapping and dynamic fields validation on conversion."""
        from pipeline.models import Pipeline, PipelineStage, CustomForm, CustomFormField
        self.client.force_authenticate(user=self.admin)

        p = Pipeline.objects.create(name="Custom Form Pipeline")
        s1 = PipelineStage.objects.create(pipeline=p, name="Lead 1", order=0, entity_type='LEAD', stage_type='NORMAL_LEAD')
        s2 = PipelineStage.objects.create(pipeline=p, name="Conv 2", order=1, entity_type='OPPORTUNITY', stage_type='CONVERSION')

        # Create active lead
        lead = Lead.objects.create(
            full_name="Dynamic Form Lead",
            company_name="Dynamic Corp",
            phone="555",
            pipeline=p,
            pipeline_stage=s1,
            assigned_salesperson=self.sales_a
        )

        # 1. POST Custom Form definition
        url_form = reverse('pipeline:pipelines-detail', args=[p.id]) + "form/"
        payload_form = {
            "is_active": True,
            "fields": [
                {"label": "B2B Budget", "field_type": "NUMBER", "required": True, "order": 0},
                {"label": "Onsite Required", "field_type": "CHECKBOX", "required": False, "order": 1},
                {"label": "Region", "field_type": "DROPDOWN", "required": True, "options": ["US", "EU", "APAC"], "order": 2}
            ]
        }
        response = self.client.post(url_form, data=payload_form, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["is_active"], True)
        self.assertEqual(len(response.data["data"]["fields"]), 3)

        # 2. Convert Lead - Fails on missing required fields or incorrect data types
        url_convert = reverse('leads:lead-detail', args=[lead.id]) + "convert/"
        payload_invalid = {
            "custom_values": {
                "B2B Budget": "not-a-number",  # invalid number
                "Region": "Africa"             # invalid option
            }
        }
        response = self.client.post(url_convert, data=payload_invalid, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Must be a valid number.", str(response.data))
        self.assertIn("Must be one of the options", str(response.data))

        # 3. Convert Lead - Success
        payload_valid = {
            "opp_data": {
                "amount": 15000.00,
                "expected_close_date": "2026-08-30"
            },
            "custom_values": {
                "B2B Budget": 15000,
                "Onsite Required": True,
                "Region": "US"
            }
        }
        response = self.client.post(url_convert, data=payload_valid, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        lead.refresh_from_db()
        self.assertEqual(lead.is_converted, True)
        
        opp = lead.converted_opportunity
        self.assertEqual(opp.amount, 15000.00)
        self.assertEqual(opp.custom_values["B2B Budget"], 15000)
        self.assertEqual(opp.custom_values["Region"], "US")
        self.assertEqual(opp.pipeline_stage, s2)
