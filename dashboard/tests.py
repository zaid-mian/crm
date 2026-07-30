from decimal import Decimal
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from leads.models import Lead
from companies.models import Company
from contacts.models import Contact
from opportunities.models import Opportunity
from payments.models import Payment, PaymentTransaction
from pipeline.models import Pipeline, PipelineStage

User = get_user_model()


class DashboardAPITests(APITestCase):
    def setUp(self):
        cache.clear()

        # Create Users
        self.admin_user = User.objects.create_superuser(
            username='admin_user',
            email='admin@test.com',
            password='password123'
        )
        self.sales_user_1 = User.objects.create_user(
            username='sales_1',
            email='sales1@test.com',
            password='password123'
        )
        self.sales_user_2 = User.objects.create_user(
            username='sales_2',
            email='sales2@test.com',
            password='password123'
        )

        # Setup standard pipeline and stages
        self.pipeline = Pipeline.objects.create(name="Standard Sales Pipeline", is_default=True)
        self.stage_new = PipelineStage.objects.create(
            pipeline=self.pipeline,
            name="New Lead",
            entity_type="LEAD",
            stage_type="NORMAL_LEAD",
            order=0,
            color="#ffc107"
        )
        self.stage_won = PipelineStage.objects.create(
            pipeline=self.pipeline,
            name="Closed Won",
            entity_type="OPPORTUNITY",
            stage_type="WON",
            order=1,
            color="#28a745"
        )

        # Companies
        self.company_1 = Company.objects.create(
            name="Company 1",
            assigned_salesperson=self.sales_user_1
        )
        self.company_2 = Company.objects.create(
            name="Company 2",
            assigned_salesperson=self.sales_user_2
        )

        # Contacts
        self.contact_1 = Contact.objects.create(
            full_name="Contact 1",
            company=self.company_1,
            assigned_salesperson=self.sales_user_1
        )
        self.contact_2 = Contact.objects.create(
            full_name="Contact 2",
            company=self.company_2,
            assigned_salesperson=self.sales_user_2
        )

        # Leads
        self.lead_1 = Lead.objects.create(
            full_name="Lead One",
            company_name="Company 1",
            pipeline=self.pipeline,
            pipeline_stage=self.stage_new,
            assigned_salesperson=self.sales_user_1,
            source="WEBSITE",
            status="NEW"
        )
        self.lead_2 = Lead.objects.create(
            full_name="Lead Two",
            company_name="Company 2",
            pipeline=self.pipeline,
            pipeline_stage=self.stage_new,
            assigned_salesperson=self.sales_user_2,
            source="REFERRAL",
            status="QUALIFIED"
        )

        # Opportunities
        self.opp_1 = Opportunity.objects.create(
            name="Opportunity 1",
            company=self.company_1,
            source_lead=self.lead_1,
            primary_contact=self.contact_1,
            assigned_salesperson=self.sales_user_1,
            stage="QUALIFICATION",
            pipeline=self.pipeline,
            pipeline_stage=self.stage_new,
            amount=Decimal("10000.00"),
            expected_close_date="2026-08-15"
        )
        self.opp_2 = Opportunity.objects.create(
            name="Opportunity 2",
            company=self.company_2,
            source_lead=self.lead_2,
            primary_contact=self.contact_2,
            assigned_salesperson=self.sales_user_2,
            stage="CLOSED_WON",
            pipeline=self.pipeline,
            pipeline_stage=self.stage_won,
            amount=Decimal("25000.00"),
            expected_close_date="2026-07-29"
        )

        # Payments
        self.payment_1 = Payment.objects.create(
            invoice_number="INV-001",
            company=self.company_1,
            opportunity=self.opp_1,
            total_amount=Decimal("10000.00"),
            paid_amount=Decimal("2000.00"),
            status="PARTIALLY_PAID",
            assigned_salesperson=self.sales_user_1
        )
        self.payment_2 = Payment.objects.create(
            invoice_number="INV-002",
            company=self.company_2,
            opportunity=self.opp_2,
            total_amount=Decimal("25000.00"),
            paid_amount=Decimal("25000.00"),
            status="PAID",
            assigned_salesperson=self.sales_user_2
        )

        # Setup endpoints URLs
        self.summary_url = reverse('dashboard:dashboard-summary')
        self.pipeline_url = reverse('dashboard:dashboard-pipeline')
        self.activity_url = reverse('dashboard:dashboard-activity')
        self.followups_url = reverse('dashboard:dashboard-followups')
        self.charts_url = reverse('dashboard:dashboard-charts')

    def test_unauthenticated_requests_fail(self):
        response = self.client.get(self.summary_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_metrics_visibility(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.summary_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Admin should see global metrics (aggregations of both sales_user_1 and sales_user_2)
        self.assertEqual(response.data["total_leads"], 2)
        self.assertEqual(response.data["active_opportunities"], 1) # opp_2 is Closed Won
        self.assertEqual(response.data["won_deals"], 1)
        self.assertEqual(float(response.data["total_pipeline_value"]), 10000.00)
        self.assertEqual(float(response.data["won_revenue"]), 25000.00)
        self.assertEqual(response.data["total_companies"], 2)
        self.assertEqual(response.data["total_contacts"], 2)

    def test_salesperson_data_scoping(self):
        # Authenticate as sales_user_1
        self.client.force_authenticate(user=self.sales_user_1)
        response = self.client.get(self.summary_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Salesperson 1 should see only their own scoped metrics
        self.assertEqual(response.data["total_leads"], 1)
        self.assertEqual(response.data["active_opportunities"], 1)
        self.assertEqual(response.data["won_deals"], 0)
        self.assertEqual(float(response.data["total_pipeline_value"]), 10000.00)
        self.assertEqual(float(response.data["won_revenue"]), 0.00)
        self.assertEqual(response.data["total_companies"], 1)
        self.assertEqual(response.data["total_contacts"], 1)

    def test_caching_behavior(self):
        self.client.force_authenticate(user=self.sales_user_1)
        
        # First request should populate cache
        response1 = self.client.get(self.summary_url)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        # Mutate database (create another lead)
        Lead.objects.create(
            full_name="Lead Three",
            company_name="Company 1",
            pipeline=self.pipeline,
            pipeline_stage=self.stage_new,
            assigned_salesperson=self.sales_user_1,
            source="WEBSITE",
            status="NEW"
        )
        
        # Second request should return cached response (identical to first, ignoring the database mutation)
        response2 = self.client.get(self.summary_url)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.data["total_leads"], 1) # Still cached at 1

        # Clear cache and verify update
        cache.clear()
        response3 = self.client.get(self.summary_url)
        self.assertEqual(response3.data["total_leads"], 2) # Updated to 2

    def test_pipeline_funnel_endpoint(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.pipeline_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) > 0)
        
        # Verify fields in stage item
        first_stage = response.data[0]
        self.assertIn("stage_id", first_stage)
        self.assertIn("stage_name", first_stage)
        self.assertIn("lead_count", first_stage)
        self.assertIn("opportunity_count", first_stage)

    def test_recent_activity_endpoint(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.activity_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Recent activity should return formatted generic logs
        self.assertTrue(len(response.data) > 0)
        first_act = response.data[0]
        self.assertIn("id", first_act)
        self.assertIn("type", first_act)
        self.assertIn("timestamp", first_act)
        self.assertIn("description", first_act)

    def test_upcoming_followups_endpoint(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.followups_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify followups returns active opportunities
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["entity_type"], "OPPORTUNITY")
        self.assertEqual(response.data[0]["title"], "Target Close: Opportunity 1")

    def test_charts_endpoint(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.charts_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("lead_sources", response.data)
        self.assertIn("payment_summary", response.data)
