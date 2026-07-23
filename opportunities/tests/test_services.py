from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from decimal import Decimal
from datetime import date, timedelta

from leads.models import Lead
from leads.services import LeadWorkflowService
from contacts.models import Contact
from opportunities.models import Opportunity, OpportunityStage
from opportunities.services import (
    OpportunityQueryService,
    OpportunityStatsService,
    OpportunityWorkflowService,
)

User = get_user_model()

class OpportunityServicesTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pwd')
        self.salesperson1 = User.objects.create_user('sales1', 'sales1@example.com', 'pwd')
        self.salesperson2 = User.objects.create_user('sales2', 'sales2@example.com', 'pwd')

        self.lead1 = Lead.objects.create(
            full_name="Lead 1", company_name="Corp A", phone="+111", assigned_salesperson=self.salesperson1
        )
        self.lead2 = Lead.objects.create(
            full_name="Lead 2", company_name="Corp B", phone="+222", assigned_salesperson=self.salesperson2
        )

        self.contact1 = Contact.objects.create(full_name="Lead 1", company_name="Corp A", phone_number="+111")
        self.contact2 = Contact.objects.create(full_name="Lead 2", company_name="Corp B", phone_number="+222")

        # Opportunity 1: Salesperson 1
        self.opp1 = Opportunity.objects.create(
            name="Opp A", company_name="Corp A", source_lead=self.lead1,
            primary_contact=self.contact1, assigned_salesperson=self.salesperson1,
            stage=OpportunityStage.QUALIFICATION, amount=Decimal('5000.00'),
            expected_close_date=date.today() + timedelta(days=30)
        )
        # Opportunity 2: Salesperson 2
        self.opp2 = Opportunity.objects.create(
            name="Opp B", company_name="Corp B", source_lead=self.lead2,
            primary_contact=self.contact2, assigned_salesperson=self.salesperson2,
            stage=OpportunityStage.DISCOVERY, amount=Decimal('10000.00'),
            expected_close_date=date.today() + timedelta(days=30)
        )

    def test_query_service_scoping(self):
        """Verify query service restricts listing visibility based on ownership/roles."""
        # Admin sees both
        admin_qs = OpportunityQueryService.get_visible_opportunities(self.admin)
        self.assertEqual(admin_qs.count(), 2)

        # Salesperson 1 sees only opp1
        sales1_qs = OpportunityQueryService.get_visible_opportunities(self.salesperson1)
        self.assertEqual(sales1_qs.count(), 1)
        self.assertEqual(sales1_qs.first(), self.opp1)

    def test_stats_service_aggregates_correctly(self):
        """Verify that summary KPIs calculate correctly."""
        stats = OpportunityStatsService.get_summary_stats(Opportunity.objects.all())
        self.assertEqual(stats["total_deals"], 2)
        self.assertEqual(stats["open_deals"], 2)
        self.assertEqual(stats["pipeline_value"], 15000.00)
        
        # opp1 expected_revenue (5000 * 10% = 500) + opp2 expected_revenue (10000 * 20% = 2000) = 2500
        self.assertEqual(stats["expected_revenue"], 2500.00)
        self.assertEqual(stats["avg_deal_size"], 7500.00)

    def test_workflow_sequential_transitions(self):
        """Verify that only sequential transitions are accepted, others raise ValidationError."""
        # 1. Qualification -> Discovery (Allowed)
        OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.DISCOVERY, "", self.salesperson1)
        self.assertEqual(self.opp1.stage, OpportunityStage.DISCOVERY)

        # 2. Discovery -> Negotiation (Not Allowed directly, skips Proposal)
        with self.assertRaises(ValidationError):
            OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.NEGOTIATION, "", self.salesperson1)

    def test_workflow_terminal_stage_lock_for_salespersons(self):
        """Verify non-admin users cannot transition out of closed won/lost stages."""
        # Move through sequence to CLOSED_WON
        OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.DISCOVERY, "", self.salesperson1)
        OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.PROPOSAL, "", self.salesperson1)
        OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.NEGOTIATION, "", self.salesperson1)
        OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.CLOSED_WON, "", self.salesperson1)
        self.assertTrue(self.opp1.closed)

        # Non-admin salesperson tries to move it back to Negotiation (Fails)
        with self.assertRaises(ValidationError):
            OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.NEGOTIATION, "", self.salesperson1)

        # Admin tries to move it back to Negotiation (Succeeds)
        OpportunityWorkflowService.change_stage(self.opp1, OpportunityStage.NEGOTIATION, "", self.admin)
        self.opp1.refresh_from_db()
        self.assertEqual(self.opp1.stage, OpportunityStage.NEGOTIATION)
        self.assertFalse(self.opp1.closed)

    def test_lead_conversion_creates_opportunity_atomically(self):
        """Verify Lead conversion workflow instantiates Contact and Opportunity atomically."""
        lead = Lead.objects.create(
            full_name="Convertible Lead",
            company_name="Convert Inc",
            phone="+999",
            assigned_salesperson=self.salesperson1
        )
        # Verify initial counts
        contact_count_before = Contact.objects.count()
        opp_count_before = Opportunity.objects.count()

        # Execute conversion
        LeadWorkflowService.convert_lead(lead)

        # Assert counts incremented
        self.assertEqual(Contact.objects.count(), contact_count_before + 1)
        self.assertEqual(Opportunity.objects.count(), opp_count_before + 1)

        # Assert new Opportunity mapped properties correctly
        opp = Opportunity.objects.latest('id')
        self.assertEqual(opp.name, "Convert Inc - Initial Opportunity")
        self.assertEqual(opp.company_name, "Convert Inc")
        self.assertEqual(opp.source_lead, lead)
        self.assertEqual(opp.assigned_salesperson, self.salesperson1)
        self.assertEqual(opp.stage, OpportunityStage.QUALIFICATION)
        self.assertEqual(opp.amount, Decimal('0.00'))
        from django.utils import timezone
        self.assertEqual(opp.expected_close_date, timezone.now().date() + timedelta(days=30))
