from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from unittest.mock import patch
from rest_framework.exceptions import ValidationError
from contacts.models import Contact
from contacts.services import ContactQueryService, ContactWorkflowService

User = get_user_model()

class ContactServiceTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', password='adminpassword')
        self.manager = User.objects.create_user(username='manager', password='password123')
        # Add Sales Manager group check configuration if needed, or is_staff which acts as manager
        self.manager.is_staff = True
        self.manager.save()

        self.sales1 = User.objects.create_user(username='sales1', password='password123')
        self.sales2 = User.objects.create_user(username='sales2', password='password123')
        self.sales_inactive = User.objects.create_user(username='sales_inactive', password='password123', is_active=False)

        self.contact1 = Contact.objects.create(
            full_name='Contact One',
            phone_number='+100',
            assigned_salesperson=self.sales1
        )
        self.contact2 = Contact.objects.create(
            full_name='Contact Two',
            phone_number='+200',
            assigned_salesperson=self.sales2
        )
        self.contact_unassigned = Contact.objects.create(
            full_name='Contact Three',
            phone_number='+300'
        )

    def test_visible_contacts_salesperson(self):
        """Verify salesperson only sees their own assigned contacts."""
        visible = ContactQueryService.get_visible_contacts(self.sales1)
        self.assertEqual(visible.count(), 1)
        self.assertIn(self.contact1, visible)
        self.assertNotIn(self.contact2, visible)

    def test_visible_contacts_admin_and_manager(self):
        """Verify admin and managers see all contacts."""
        admin_visible = ContactQueryService.get_visible_contacts(self.admin)
        self.assertEqual(admin_visible.count(), 3)

        manager_visible = ContactQueryService.get_visible_contacts(self.manager)
        self.assertEqual(manager_visible.count(), 3)

    def test_workflow_assign_salesperson_success(self):
        """Verify workflow service assigns active salesperson successfully."""
        contact = ContactWorkflowService.assign_salesperson(self.contact_unassigned, self.sales1)
        self.assertEqual(contact.assigned_salesperson, self.sales1)

    def test_workflow_assign_inactive_salesperson_fails(self):
        """Verify assigning inactive salesperson raises ValidationError."""
        with self.assertRaises(ValidationError) as context:
            ContactWorkflowService.assign_salesperson(self.contact_unassigned, self.sales_inactive)
        self.assertIn("Cannot assign a contact to an inactive salesperson.", str(context.exception))

    def test_database_rollback_on_failed_workflow_action(self):
        """Verify database transaction rolls back fully upon write error."""
        with patch.object(Contact, 'save', side_effect=IntegrityError("Mock Integrity Error")):
            with self.assertRaises(IntegrityError):
                ContactWorkflowService.assign_salesperson(self.contact_unassigned, self.sales1)
        
        # Reload and check state remains unchanged
        refetched = Contact.objects.get(pk=self.contact_unassigned.pk)
        self.assertIsNone(refetched.assigned_salesperson)
