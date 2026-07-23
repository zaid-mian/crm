from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError
from unittest.mock import patch

from leads.models import Lead
from leads.services import (
    LeadQueryService,
    LeadStatsService,
    LeadWorkflowService,
    LeadWorkflowManager,
)

User = get_user_model()

class LeadServicesTestCase(TestCase):
    def setUp(self):
        # Create users for role-based scoping tests
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pwd')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'pwd', is_staff=True)
        self.sales_a = User.objects.create_user('sales_a', 'sales_a@example.com', 'pwd')
        self.sales_b = User.objects.create_user('sales_b', 'sales_b@example.com', 'pwd')
        self.sales_inactive = User.objects.create_user('sales_in', 'sales_in@example.com', 'pwd', is_active=False)

        # Create leads for scoping
        self.lead_a = Lead.objects.create(
            full_name="Lead A", phone="+11111", company_name="A Corp", assigned_salesperson=self.sales_a
        )
        self.lead_b = Lead.objects.create(
            full_name="Lead B", phone="+22222", company_name="B Corp", assigned_salesperson=self.sales_b
        )
        self.lead_unassigned = Lead.objects.create(
            full_name="Lead C", phone="+33333", company_name="C Corp"
        )

    def test_query_service_scopes_visible_leads(self):
        """Verify query service filters list querysets based on user authorization."""
        # Admin sees all leads
        admin_leads = LeadQueryService.get_visible_leads(self.admin)
        self.assertEqual(admin_leads.count(), 3)

        # Manager sees all leads
        manager_leads = LeadQueryService.get_visible_leads(self.manager)
        self.assertEqual(manager_leads.count(), 3)

        # Salesperson A sees only lead_a
        sales_a_leads = LeadQueryService.get_visible_leads(self.sales_a)
        self.assertEqual(sales_a_leads.count(), 1)
        self.assertEqual(sales_a_leads.first(), self.lead_a)

    def test_stats_service_aggregates_status_correctly(self):
        """Verify LeadStatsService aggregates correctly for the visibility subset."""
        # Scoped to Salesperson A
        scoped_qs = LeadQueryService.get_visible_leads(self.sales_a)
        stats = LeadStatsService.get_status_grouped_stats(scoped_qs)
        self.assertEqual(stats["total_leads"], 1)
        self.assertEqual(stats["status_counts"][Lead.LeadStatus.NEW], 1)

        # Scoped to Admin
        admin_qs = LeadQueryService.get_visible_leads(self.admin)
        admin_stats = LeadStatsService.get_status_grouped_stats(admin_qs)
        self.assertEqual(admin_stats["total_leads"], 3)
        self.assertEqual(admin_stats["status_counts"][Lead.LeadStatus.NEW], 3)

    def test_workflow_assign_valid_path(self):
        """Verify successful lead salesperson assignment."""
        LeadWorkflowService.assign_salesperson(self.lead_unassigned, self.sales_a)
        self.lead_unassigned.refresh_from_db()
        self.assertEqual(self.lead_unassigned.assigned_salesperson, self.sales_a)

    def test_workflow_assign_idempotency(self):
        """Verify re-assigning the same salesperson succeeds and is consistent."""
        LeadWorkflowService.assign_salesperson(self.lead_a, self.sales_a)
        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.assigned_salesperson, self.sales_a)

    def test_workflow_assign_converted_lead_fails(self):
        """Verify assigning converted leads fails validation."""
        self.lead_a.is_converted = True
        self.lead_a.status = Lead.LeadStatus.CONVERTED
        self.lead_a.save()

        with self.assertRaises(ValidationError):
            LeadWorkflowService.assign_salesperson(self.lead_a, self.sales_b)

    def test_workflow_assign_inactive_salesperson_fails(self):
        """Verify assigning inactive salespersons fails validation."""
        with self.assertRaises(ValidationError):
            LeadWorkflowService.assign_salesperson(self.lead_unassigned, self.sales_inactive)

    def test_workflow_convert_valid_path(self):
        """Verify successful lead conversion workflow sets timestamp and spawns Contact."""
        from contacts.models import Contact
        contact_count_before = Contact.objects.count()
        
        lead = LeadWorkflowService.convert_lead(self.lead_a)
        self.assertEqual(lead.status, Lead.LeadStatus.CONVERTED)
        self.assertTrue(lead.is_converted)
        self.assertIsNotNone(lead.converted_at)

        # Assert contact was created matching lead fields
        self.assertEqual(Contact.objects.count(), contact_count_before + 1)
        contact = Contact.objects.latest('id')
        self.assertEqual(contact.full_name, lead.full_name)
        self.assertEqual(contact.company_name, lead.company_name)
        self.assertEqual(contact.phone_number, lead.phone)
        self.assertEqual(contact.email, lead.email)
        self.assertEqual(contact.assigned_salesperson, lead.assigned_salesperson)

    def test_workflow_convert_unassigned_lead_fails(self):
        """Verify that converting an unassigned lead raises a ValidationError."""
        with self.assertRaises(ValidationError) as context:
            LeadWorkflowService.convert_lead(self.lead_unassigned)
        self.assertIn("Assign the lead to a salesperson before converting it.", str(context.exception))

    def test_workflow_convert_idempotency(self):
        """Verify attempting to convert an already converted lead fails validation."""
        LeadWorkflowService.convert_lead(self.lead_a)
        with self.assertRaises(ValidationError):
            LeadWorkflowService.convert_lead(self.lead_a)

    def test_workflow_convert_lost_lead_fails(self):
        """Verify converting lost leads fails validation."""
        LeadWorkflowService.assign_salesperson(self.lead_unassigned, self.sales_a)
        LeadWorkflowService.mark_lead_lost(self.lead_unassigned, Lead.LostReason.BUDGET_TOO_HIGH, "Notes")
        with self.assertRaises(ValidationError):
            LeadWorkflowService.convert_lead(self.lead_unassigned)

    def test_workflow_lost_valid_path(self):
        """Verify marking lead as lost."""
        lead = LeadWorkflowService.mark_lead_lost(
            self.lead_unassigned, Lead.LostReason.COMPETITOR_CHOSEN, "Competitor offered discount."
        )
        self.assertEqual(lead.status, Lead.LeadStatus.LOST)
        self.assertEqual(lead.lost_reason, Lead.LostReason.COMPETITOR_CHOSEN)

    def test_workflow_lost_idempotency(self):
        """Verify marking an already lost lead as lost again works and updates details."""
        LeadWorkflowService.mark_lead_lost(self.lead_unassigned, Lead.LostReason.NO_RESPONSE, "Init")
        
        # Second call to mark lost behaves consistently and updates notes
        LeadWorkflowService.mark_lead_lost(self.lead_unassigned, Lead.LostReason.WRONG_CONTACT, "Second notes")
        self.lead_unassigned.refresh_from_db()
        self.assertEqual(self.lead_unassigned.status, Lead.LeadStatus.LOST)
        self.assertEqual(self.lead_unassigned.lost_reason, Lead.LostReason.WRONG_CONTACT)
        self.assertEqual(self.lead_unassigned.lost_notes, "Second notes")

    def test_workflow_lost_converted_lead_fails(self):
        """Verify marking converted leads as lost fails validation."""
        LeadWorkflowService.convert_lead(self.lead_a)
        with self.assertRaises(ValidationError):
            LeadWorkflowService.mark_lead_lost(self.lead_a, Lead.LostReason.NOT_INTERESTED, "Too late")

    def test_workflow_assign_status_transition(self):
        """Verify lead salesperson assignment transitions status from NEW to ASSIGNED."""
        self.assertEqual(self.lead_unassigned.status, Lead.LeadStatus.NEW)
        LeadWorkflowService.assign_salesperson(self.lead_unassigned, self.sales_a)
        self.lead_unassigned.refresh_from_db()
        self.assertEqual(self.lead_unassigned.status, Lead.LeadStatus.ASSIGNED)

    def test_workflow_contacted_action_success(self):
        """Verify user explicitly transitioning lead to CONTACTED."""
        LeadWorkflowService.assign_salesperson(self.lead_unassigned, self.sales_a)
        self.assertEqual(self.lead_unassigned.status, Lead.LeadStatus.ASSIGNED)
        
        LeadWorkflowService.mark_contacted(self.lead_unassigned)
        self.lead_unassigned.refresh_from_db()
        self.assertEqual(self.lead_unassigned.status, Lead.LeadStatus.CONTACTED)

    def test_workflow_contacted_action_fails_if_lost_or_converted(self):
        """Verify contacted transition fails on converted/lost leads."""
        # Converted fails
        LeadWorkflowService.convert_lead(self.lead_a)
        with self.assertRaises(ValidationError):
            LeadWorkflowService.mark_contacted(self.lead_a)

        # Lost fails
        LeadWorkflowService.mark_lead_lost(self.lead_b, Lead.LostReason.NO_RESPONSE, "")
        with self.assertRaises(ValidationError):
            LeadWorkflowService.mark_contacted(self.lead_b)

    def test_database_rollback_on_failed_workflow_action(self):
        """Verify failed workflow operations rollback database changes entirely."""
        lead = Lead.objects.create(
            full_name="Rollback Test",
            phone="+99999",
            company_name="Transaction Rollback Inc",
            status=Lead.LeadStatus.NEW,
            assigned_salesperson=self.sales_a
        )
        
        # Mock lead.save() to raise database error to assert rollback
        with patch.object(Lead, 'save', side_effect=IntegrityError("Mock Database Integrity Error")):
            with self.assertRaises(IntegrityError):
                LeadWorkflowService.convert_lead(lead)
        
        # Verify the database state remains NEW and NOT converted (transaction rolled back)
        refetched = Lead.objects.get(pk=lead.pk)
        self.assertEqual(refetched.status, Lead.LeadStatus.NEW)
        self.assertFalse(refetched.is_converted)

    def test_database_rollback_on_contact_creation_failure(self):
        """Verify that conversion rolls back lead status if Contact creation fails."""
        from contacts.models import Contact
        lead = Lead.objects.create(
            full_name="Rollback Contact Test",
            phone="+999992",
            company_name="Contact Failure Inc",
            status=Lead.LeadStatus.NEW,
            assigned_salesperson=self.sales_a
        )

        with patch.object(Contact.objects, 'create', side_effect=IntegrityError("Mock Contact Integrity Error")):
            with self.assertRaises(IntegrityError):
                LeadWorkflowService.convert_lead(lead)

        # Refetch lead and verify it is NOT converted and status remains NEW
        refetched = Lead.objects.get(pk=lead.pk)
        self.assertEqual(refetched.status, Lead.LeadStatus.NEW)
        self.assertFalse(refetched.is_converted)
        self.assertIsNone(refetched.converted_at)
