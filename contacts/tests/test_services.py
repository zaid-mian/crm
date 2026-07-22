from django.test import TestCase
from django.contrib.auth import get_user_model
from contacts.models import Contact
from contacts.services import ContactQueryService

User = get_user_model()

class ContactServiceTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', password='adminpassword')
        self.salesperson1 = User.objects.create_user(username='sales1', password='password123')
        self.salesperson2 = User.objects.create_user(username='sales2', password='password123')

        self.contact1 = Contact.objects.create(
            full_name='Contact One',
            phone_number='+100',
            assigned_salesperson=self.salesperson1
        )
        self.contact2 = Contact.objects.create(
            full_name='Contact Two',
            phone_number='+200',
            assigned_salesperson=self.salesperson2
        )

    def test_visible_contacts_salesperson(self):
        visible = ContactQueryService.get_visible_contacts(self.salesperson1)
        self.assertEqual(visible.count(), 1)
        self.assertIn(self.contact1, visible)

    def test_visible_contacts_admin(self):
        visible = ContactQueryService.get_visible_contacts(self.admin)
        self.assertEqual(visible.count(), 2)
