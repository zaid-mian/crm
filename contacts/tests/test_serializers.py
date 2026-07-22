from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework import serializers
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
        """Verify ContactDetailSerializer outputs correct values and empty placeholders."""
        serializer = ContactDetailSerializer(instance=self.contact)
        data = serializer.data
        self.assertEqual(data['full_name'], 'Alice Smith')
        self.assertEqual(data['company_name'], 'Beta LLC')
        # Placeholders must return empty lists
        self.assertEqual(data['related_opportunities'], [])
        self.assertEqual(data['activities'], [])
        self.assertEqual(data['related_tasks'], [])

    def test_create_serializer_duplicate_phone(self):
        """Verify phone number duplication check on creation."""
        data = {
            'full_name': 'Bob',
            'phone_number': '+1112223333',
            'email': 'bob@example.com',
        }
        serializer = ContactCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('phone_number', serializer.errors)

    def test_create_serializer_duplicate_email(self):
        """Verify email address duplication check on creation."""
        data = {
            'full_name': 'Bob',
            'phone_number': '+999888',
            'email': 'alice@example.com',
        }
        serializer = ContactCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('email', serializer.errors)

    def test_update_serializer_ignores_self_duplicates(self):
        """Verify update serializer allows saving the same email/phone for the current instance."""
        data = {
            'full_name': 'Alice Smith Renamed',
            'phone_number': '+1112223333',
            'email': 'alice@example.com',
        }
        serializer = ContactUpdateSerializer(instance=self.contact, data=data)
        self.assertTrue(serializer.is_valid())

    def test_update_serializer_detects_other_duplicates(self):
        """Verify update serializer prevents saving email/phone owned by another contact."""
        other_contact = Contact.objects.create(
            full_name='Other Person',
            email='other@example.com',
            phone_number='+8888888888'
        )
        data = {
            'full_name': 'Alice Renamed',
            'phone_number': '+8888888888',
            'email': 'other@example.com',
        }
        serializer = ContactUpdateSerializer(instance=self.contact, data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('phone_number', serializer.errors)
        self.assertIn('email', serializer.errors)
