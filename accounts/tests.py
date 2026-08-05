from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from accounts.models import Organization, OwnerProfile, RegistrationRequest

User = get_user_model()

class AccountsModelIntegrityTest(TestCase):
    def setUp(self):
        # Create users
        self.user1 = User.objects.create_user(
            username="owner1@platform.com",
            email="owner1@platform.com",
            password="securepassword123",
            first_name="Alice",
            last_name="Owner"
        )
        self.user2 = User.objects.create_user(
            username="owner2@platform.com",
            email="owner2@platform.com",
            password="securepassword123",
            first_name="Bob",
            last_name="Owner"
        )

        # Create organizations
        self.org1 = Organization.objects.create(name="Acme Corp")
        self.org2 = Organization.objects.create(name="Stark Industries")

    def test_owner_profile_creation(self):
        """Verify we can successfully create and query OwnerProfile and Organization."""
        profile = OwnerProfile.objects.create(
            user=self.user1,
            organization=self.org1,
            cnic="12345-6789012-3",
            phone_number="0300-1234567",
            country="Pakistan",
            address="123 Street, Acme City"
        )
        self.assertEqual(OwnerProfile.objects.count(), 1)
        self.assertEqual(profile.organization, self.org1)
        self.assertEqual(str(profile), "Alice Owner - Acme Corp")

    def test_owner_profile_user_uniqueness(self):
        """Verify that a user cannot link to multiple OwnerProfiles (OneToOne constraint)."""
        OwnerProfile.objects.create(
            user=self.user1,
            organization=self.org1,
            cnic="12345-6789012-3",
            phone_number="0300-1234567",
            country="Pakistan"
        )

        # Attempt to link user1 to another profile for org2
        with self.assertRaises(IntegrityError):
            OwnerProfile.objects.create(
                user=self.user1,
                organization=self.org2,
                cnic="99999-9999999-9",
                phone_number="0300-9999999",
                country="USA"
            )

    def test_owner_profile_organization_uniqueness(self):
        """Verify that an Organization cannot be linked to multiple OwnerProfiles (OneToOne constraint)."""
        OwnerProfile.objects.create(
            user=self.user1,
            organization=self.org1,
            cnic="12345-6789012-3",
            phone_number="0300-1234567",
            country="Pakistan"
        )

        # Attempt to link user2 to same org1 (which is already linked to user1)
        with self.assertRaises(IntegrityError):
            OwnerProfile.objects.create(
                user=self.user2,
                organization=self.org1,
                cnic="99999-9999999-9",
                phone_number="0300-9999999",
                country="USA"
            )

    def test_registration_request_lifecycle(self):
        """Verify the creation and relations of the RegistrationRequest queue."""
        profile = OwnerProfile.objects.create(
            user=self.user1,
            organization=self.org1,
            cnic="12345-6789012-3",
            phone_number="0300-1234567",
            country="Pakistan"
        )
        
        reg_request = RegistrationRequest.objects.create(
            owner_profile=profile,
            status="pending"
        )
        
        self.assertEqual(RegistrationRequest.objects.count(), 1)
        self.assertEqual(reg_request.status, "pending")
        self.assertIsNone(reg_request.rejection_reason)
        self.assertEqual(str(reg_request), "owner1@platform.com - pending")

        # Try to create duplicate request on same profile (should fail OneToOne constraint)
        with self.assertRaises(IntegrityError):
            RegistrationRequest.objects.create(
                owner_profile=profile,
                status="approved"
            )
