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


from django.urls import reverse

class AccountsAPITestCase(TestCase):
    def setUp(self):
        # Create a superuser for admin views
        self.admin_user = User.objects.create_superuser(
            username="admin@platform.com",
            email="admin@platform.com",
            password="adminpassword123"
        )
        
        # Base registration parameters
        self.signup_data = {
            "email": "newowner@test.com",
            "password": "ownerpassword123",
            "first_name": "John",
            "last_name": "Doe",
            "company_name": "Test Organization",
            "cnic": "11111-2222222-3",
            "phone_number": "0333-1112223",
            "country": "Pakistan",
            "address": "456 Avenue, Karachi"
        }

    def test_platform_signup_lifecycle(self):
        """Verify standard user and organization signup submits successfully in inactive states."""
        url = reverse('accounts:api_register')
        response = self.client.post(url, self.signup_data, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        
        # Verify inactive account creations
        user = User.objects.get(email="newowner@test.com")
        self.assertFalse(user.is_active)
        
        profile = user.ownerprofile
        self.assertEqual(profile.cnic, "11111-2222222-3")
        self.assertFalse(profile.organization.is_active)
        self.assertEqual(profile.organization.name, "Test Organization")
        
        request_record = RegistrationRequest.objects.get(owner_profile=profile)
        self.assertEqual(request_record.status, "pending")

    def test_login_pending_rejection_gates(self):
        """Verify login blocks inactive accounts with status-specific messages."""
        # 1. Submit signup
        self.client.post(reverse('accounts:api_register'), self.signup_data, content_type='application/json')
        
        # 2. Attempt login (should be blocked as pending)
        login_url = reverse('accounts:api_login')
        login_data = {
            "username": "newowner@test.com",
            "password": "ownerpassword123"
        }
        response = self.client.post(login_url, login_data, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertIn("pending admin approval", response.json()['message'])

        # 3. Reject the request
        user = User.objects.get(email="newowner@test.com")
        reg_request = RegistrationRequest.objects.get(owner_profile=user.ownerprofile)
        reg_request.status = 'rejected'
        reg_request.rejection_reason = "Invalid documents"
        reg_request.save()

        # 4. Attempt login (should be blocked as rejected)
        response_rejected = self.client.post(login_url, login_data, content_type='application/json')
        self.assertEqual(response_rejected.status_code, 403)
        self.assertIn("rejected. Reason: Invalid documents", response_rejected.json()['message'])

    def test_login_success_and_me_payload(self):
        """Verify successful login and correctness of the profile payload."""
        # 1. Create approved owner user
        owner = User.objects.create_user(
            username="approved@test.com",
            email="approved@test.com",
            password="ownerpassword123",
            first_name="Jane",
            last_name="Owner",
            is_active=True
        )
        org = Organization.objects.create(name="Authorized Corp", is_active=True)
        OwnerProfile.objects.create(
            user=owner,
            organization=org,
            cnic="22222-3333333-4",
            phone_number="0300-9876543",
            country="Pakistan"
        )

        # 2. Login
        login_url = reverse('accounts:api_login')
        login_response = self.client.post(
            login_url, 
            {"username": "approved@test.com", "password": "ownerpassword123"},
            content_type='application/json'
        )
        self.assertEqual(login_response.status_code, 200)

        # 3. Fetch Me API
        me_url = reverse('accounts:api_me')
        me_response = self.client.get(me_url)
        self.assertEqual(me_response.status_code, 200)
        
        data = me_response.json()['data']
        self.assertEqual(data['email'], "approved@test.com")
        self.assertEqual(data['profile']['organization']['name'], "Authorized Corp")

    def test_admin_approval_triggers_crm_provisioning(self):
        """Verify that registration approvals fire signals that auto-provision CRM UserProfile."""
        # 1. Register tenant
        self.client.post(reverse('accounts:api_register'), self.signup_data, content_type='application/json')
        owner_user = User.objects.get(email="newowner@test.com")
        reg_request = RegistrationRequest.objects.get(owner_profile=owner_user.ownerprofile)

        # 2. Login as admin
        self.client.login(username="admin@platform.com", password="adminpassword123")

        # 3. Query list of registrations
        list_url = reverse('accounts:api_admin_registrations')
        list_response = self.client.get(list_url)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()['data']), 1)

        # 4. Approve request
        approve_url = reverse('accounts:api_admin_approve', kwargs={'pk': reg_request.pk})
        approve_response = self.client.post(approve_url)
        self.assertEqual(approve_response.status_code, 200)

        # 5. Verify activation
        owner_user.refresh_from_db()
        self.assertTrue(owner_user.is_active)
        self.assertTrue(owner_user.ownerprofile.organization.is_active)

        # 6. Verify Decoupled Onboarding: CRM profile must be auto-created with dynamic RBAC roles
        from leads.models import UserProfile
        crm_profile = UserProfile.objects.get(user=owner_user)
        self.assertEqual(crm_profile.user_type, 'ADMIN')
        self.assertEqual(crm_profile.role.name, "Administrator")

