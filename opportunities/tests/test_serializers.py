from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import MagicMock

from leads.models import Lead
from contacts.models import Contact
from opportunities.models import Opportunity, OpportunityStage
from opportunities.serializers import OpportunityUpdateSerializer

User = get_user_model()

class OpportunitySerializerTestCase(TestCase):
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
        self.opp = Opportunity.objects.create(
            name="Acme Opportunity",
            company_name="Acme Inc",
            source_lead=self.lead,
            primary_contact=self.contact,
            assigned_salesperson=self.salesperson,
            stage=OpportunityStage.QUALIFICATION,
            amount=Decimal('1000.00'),
            expected_close_date=date.today() + timedelta(days=30)
        )

    def test_update_validation_non_negative_amount(self):
        """Verify updating with a negative amount raises validation error."""
        serializer = OpportunityUpdateSerializer(
            instance=self.opp,
            data={"amount": "-50.00"},
            partial=True,
            context={"request": MagicMock(user=self.salesperson)}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("amount", serializer.errors)

    def test_update_validation_close_date_in_past(self):
        """Verify close date cannot be before creation date."""
        past_date = date.today() - timedelta(days=10)
        serializer = OpportunityUpdateSerializer(
            instance=self.opp,
            data={"expected_close_date": past_date},
            partial=True,
            context={"request": MagicMock(user=self.salesperson)}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("expected_close_date", serializer.errors)

    def test_update_stage_closed_lost_requires_lost_reason(self):
        """Verify transitioning to Closed Lost requires lost_reason."""
        serializer = OpportunityUpdateSerializer(
            instance=self.opp,
            data={"stage": OpportunityStage.CLOSED_LOST, "lost_reason": ""},
            partial=True,
            context={"request": MagicMock(user=self.salesperson)}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("lost_reason", serializer.errors)
