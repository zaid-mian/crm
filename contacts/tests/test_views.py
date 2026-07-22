from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from contacts.models import Contact

User = get_user_model()

class ContactViewSetTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='admin', password='adminpassword')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(
            full_name='Charlie Brown',
            phone_number='+123987',
            email='charlie@example.com',
            company_name='Peanuts Inc',
            assigned_salesperson=self.user
        )

    def test_list_contacts(self):
        url = reverse('contacts:contact-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])

    def test_retrieve_contact(self):
        url = reverse('contacts:contact-detail', kwargs={'pk': self.contact.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['full_name'], 'Charlie Brown')

    def test_create_contact(self):
        url = reverse('contacts:contact-list')
        payload = {
            'full_name': 'David Miller',
            'phone_number': '+999888777',
            'email': 'david@example.com',
            'company_name': 'Delta Corp',
            'assigned_salesperson': self.user.id
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])

    def test_soft_delete_contact(self):
        url = reverse('contacts:contact-detail', kwargs={'pk': self.contact.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contact.refresh_from_db()
        self.assertTrue(self.contact.is_deleted)
