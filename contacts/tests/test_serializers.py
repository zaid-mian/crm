from django.test import TestCase
from django.contrib.auth import get_user_model
from contacts.models import Contact
from contacts.serializers import (
    ContactListSerializer,
    ContactDetailSerializer,
    ContactCreateSerializer,
    ContactUpdateSerializer,
)

User = get_user_model()

class ContactSerializerTest(TestCase):
    def setUp(self):
        self.salesperson = User.objects.create_user(username='salesrep', password='password123')
        self.contact = Contact.objects.create(
            full_name='Alice Smith',
            email='alice@example.com',
            phone_number='+1112223333',
            company_name='Beta LLC',
            designation='CEO',
            assigned_salesperson=self.salesperson
        )

    def test_contact_detail_serializer(self):
        serializer = ContactDetailSerializer(instance=self.contact)
        data = serializer.data
        self.assertEqual(data['full_name'], 'Alice Smith')
        self.assertEqual(data['company_name'], 'Beta LLC')
        self.assertIn('related_opportunities', data)
        self.assertIn('activities', data)
        self.assertIn('related_tasks', data)

    def test_duplicate_phone_validation(self):
        data = {
            'full_name': 'Bob',
            'phone_number': '+1112223333',
            'email': 'bob@example.com',
            'company_name': 'Gamma Corp',
            'assigned_salesperson': self.salesperson.id
        }
        serializer = ContactCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('phone_number', serializer.errors)
