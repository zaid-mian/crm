from django.test import TestCase
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date

from leads.models import Lead
from contacts.models import Contact
from opportunities.models import Opportunity, OpportunityStage

User = get_user_model()

class OpportunityModelTestCase(TestCase):
    def setUp(self):
        self.salesperson = User.objects.create_user(
            username='salesperson', password='pwd'
        )
        self.lead = Lead.objects.create(
            full_name="Lead John",
            company_name="Acme Inc",
            phone="+12345",
            source="WEBSITE"
        )
        self.contact = Contact.objects.create(
            full_name="Lead John",
            company_name="Acme Inc",
            phone_number="+12345"
        )

    def test_opportunity_properties_derivation(self):
        """Verify dynamic property derivations based on stage."""
        opp = Opportunity.objects.create(
            name="Acme Opportunity",
            company_name="Acme Inc",
            source_lead=self.lead,
            primary_contact=self.contact,
            assigned_salesperson=self.salesperson,
            stage=OpportunityStage.QUALIFICATION,
            amount=Decimal('1000.00'),
            expected_close_date=date(2026, 12, 31)
        )
        
        # 1. Qualification (10%)
        self.assertEqual(opp.probability, 10)
        self.assertEqual(opp.expected_revenue, Decimal('100.00'))
        self.assertFalse(opp.won)
        self.assertFalse(opp.closed)
        self.assertEqual(opp.opportunity_code, f"OP{opp.id:03d}")

        # 2. Closed Won (100%)
        opp.stage = OpportunityStage.CLOSED_WON
        self.assertEqual(opp.probability, 100)
        self.assertEqual(opp.expected_revenue, Decimal('1000.00'))
        self.assertTrue(opp.won)
        self.assertTrue(opp.closed)

        # 3. Closed Lost (0%)
        opp.stage = OpportunityStage.CLOSED_LOST
        self.assertEqual(opp.probability, 0)
        self.assertEqual(opp.expected_revenue, Decimal('0.00'))
        self.assertFalse(opp.won)
        self.assertTrue(opp.closed)
