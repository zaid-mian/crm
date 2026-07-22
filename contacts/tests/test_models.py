from django.test import TestCase
from django.contrib.auth import get_user_model
from contacts.models import Contact

User = get_user_model()

class ContactModelTest(TestCase):
    def setUp(self):
        self.salesperson = User.objects.create_user(username='salesrep', password='password123')

    def test_create_contact_success(self):
        contact = Contact.objects.create(
            full_name='Jane Doe',
            email='jane@example.com',
            phone_number='+1234567890',
            company_name='ABC Ltd',
            designation='Manager',
            assigned_salesperson=self.salesperson
        )
        self.assertEqual(contact.full_name, 'Jane Doe')
        self.assertEqual(contact.contact_code, f'CT{contact.id:03d}')
        self.assertEqual(contact.status, 'Active')
        self.assertFalse(contact.is_deleted)

    def test_soft_delete(self):
        contact = Contact.objects.create(
            full_name='John Smith',
            phone_number='+0987654321',
            assigned_salesperson=self.salesperson
        )
        self.assertFalse(contact.is_deleted)
        contact.soft_delete()
        self.assertTrue(contact.is_deleted)
