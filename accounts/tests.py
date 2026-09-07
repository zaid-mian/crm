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
        with self.captureOnCommitCallbacks(execute=True):
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

    def test_signup_validation_errors(self):
        """Verify malformed cnic and phone numbers are rejected by PlatformSignupSerializer."""
        url = reverse('accounts:api_register')
        
        # 1. Invalid CNIC (short digits)
        bad_cnic_data = self.signup_data.copy()
        bad_cnic_data["cnic"] = "12345-abc"
        bad_cnic_data["email"] = "error1@test.com"
        response = self.client.post(url, bad_cnic_data, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn("cnic", response.json()["errors"])

        # 2. Invalid phone (letters included)
        bad_phone_data = self.signup_data.copy()
        bad_phone_data["phone_number"] = "0333-111-xyz"
        bad_phone_data["email"] = "error2@test.com"
        response = self.client.post(url, bad_phone_data, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone_number", response.json()["errors"])

    def test_add_employee_success(self):
        """Verify CRM administrator can successfully create a new employee inside their organization."""
        # 1. Create a CRM administrator
        admin = User.objects.create_user(
            username="admin@testcorp.com",
            email="admin@testcorp.com",
            password="adminpassword123",
            is_active=True
        )
        org = Organization.objects.create(name="QA Testing Corp", is_active=True)
        
        # Update the automatically created profile
        profile = admin.profile
        profile.organization = org
        profile.user_type = 'ADMIN'
        profile.save()
        
        # 2. Login as CRM admin
        self.client.login(username="admin@testcorp.com", password="adminpassword123")
        
        # 3. Create or fetch a default role to assign
        from roles.models import Role
        role, _ = Role.objects.get_or_create(name="Salesperson", defaults={"description": "Sales Agent"})
        
        # 4. POST to create employee
        url = reverse('accounts:api_admin_users')
        payload = {
            "email": "employee@testcorp.com",
            "password": "employeepassword123",
            "first_name": "John",
            "last_name": "Doe",
            "role_id": role.id
        }
        response = self.client.post(url, payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Employee created successfully.")
        
        # 5. Verify database records
        emp_user = User.objects.get(email="employee@testcorp.com")
        self.assertTrue(emp_user.is_active)
        self.assertEqual(emp_user.first_name, "John")
        
        from leads.models import UserProfile as UP
        emp_profile = UP.objects.get(user=emp_user)
        self.assertEqual(emp_profile.organization, org) # Organization matches admin's organization
        self.assertEqual(emp_profile.role, role)
        self.assertEqual(emp_profile.user_type, 'USER')

    def test_add_employee_unauthorized(self):
        """Verify non-admin users cannot create employees."""
        # 1. Create standard salesperson
        sp = User.objects.create_user(
            username="sales@testcorp.com",
            email="sales@testcorp.com",
            password="salespassword123",
            is_active=True
        )
        org = Organization.objects.create(name="QA Testing Corp", is_active=True)
        
        # Update the automatically created profile
        profile = sp.profile
        profile.organization = org
        profile.user_type = 'USER'
        profile.save()
        
        # 2. Login as salesperson
        self.client.login(username="sales@testcorp.com", password="salespassword123")
        
        # 3. Attempt POST to create employee
        url = reverse('accounts:api_admin_users')
        payload = {
            "email": "intruder@testcorp.com",
            "password": "password123",
            "first_name": "Intruder",
            "last_name": "User"
        }
        response = self.client.post(url, payload, content_type='application/json')
        self.assertEqual(response.status_code, 403)


class CORSSessionCSRFTestCase(TestCase):
    def test_cors_allowed_origin(self):
        """CORS request from allowed origin returns correct headers."""
        url = reverse('accounts:api_register')
        # Allowed origin
        response = self.client.options(
            url, 
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:3000")

        # Disallowed origin
        response_disallowed = self.client.options(
            url, 
            HTTP_ORIGIN="http://disallowed-domain.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST"
        )
        # In django-cors-headers, requests from disallowed origins do not get Access-Control-Allow-Origin header
        self.assertNotIn("Access-Control-Allow-Origin", response_disallowed.headers)

    def test_csrf_protection_active(self):
        """CSRF middleware protects mutating state APIs when session authentication is active."""
        # Create active user
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(username="test_csrf_u", email="csrf@test.com", password="password", is_active=True)
        
        # Initialize client with enforce_csrf_checks=True
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.login(username="test_csrf_u", password="password")
        
        # Call mutating endpoint without CSRF token (should fail with 403 Forbidden)
        url = reverse('accounts:api_register')
        response = client.post(url, {})
        self.assertEqual(response.status_code, 403)


class PasswordResetAPITestCase(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            username="reset_user@test.com",
            email="reset_user@test.com",
            password="oldpassword123",
            is_active=True
        )

    def test_password_reset_api_flow(self):
        """Verify successful password reset request and API confirmation flow."""
        from django.core import mail
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator

        # 1. POST forgot-password request
        forgot_url = reverse('accounts:api_forgot_password')
        response = self.client.post(forgot_url, {"email": "reset_user@test.com"})
        self.assertEqual(response.status_code, 200)

        # 2. Check console mail outbox
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("reset-password", email.body)

        # Generate fresh token & uidb64 to test API directly
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        confirm_url = reverse('accounts:api_password_reset_confirm')

        # 3. Mismatched passwords should return 400
        payload_mismatch = {
            "uidb64": uidb64,
            "token": token,
            "new_password": "NewSecurePassword123!",
            "confirm_password": "DifferentPassword123!"
        }
        res_mismatch = self.client.post(confirm_url, payload_mismatch)
        self.assertEqual(res_mismatch.status_code, 400)

        # 4. Invalid token should return 400
        payload_invalid_token = {
            "uidb64": uidb64,
            "token": "invalid-token-123",
            "new_password": "NewSecurePassword123!",
            "confirm_password": "NewSecurePassword123!"
        }
        res_token = self.client.post(confirm_url, payload_invalid_token)
        self.assertEqual(res_token.status_code, 400)

        # 5. Correct payload reset succeeds
        payload_success = {
            "uidb64": uidb64,
            "token": token,
            "new_password": "NewSecurePassword123!",
            "confirm_password": "NewSecurePassword123!"
        }
        res_success = self.client.post(confirm_url, payload_success)
        self.assertEqual(res_success.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecurePassword123!"))


class MeViewExtendedTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from accounts.models import Organization, OwnerProfile
        from leads.models import UserProfile
        from roles.models import Role, CRMResource, RolePermission
        from roles.services import RoleService

        User = get_user_model()

        # Setup organization
        self.org = Organization.objects.create(name="Authorized Corp", is_active=True)

        # Setup roles
        self.admin_role = RoleService.get_default_admin_role()
        self.sales_role = RoleService.get_default_role("Salesperson")

        # Create resource
        self.resource, _ = CRMResource.objects.get_or_create(codename="leads", name="Leads")

        # Create permission mapping for Salesperson
        RolePermission.objects.get_or_create(role=self.sales_role, resource=self.resource, action="VIEW", defaults={"scope": "OWN"})
        RolePermission.objects.get_or_create(role=self.sales_role, resource=self.resource, action="DELETE", defaults={"scope": "NONE"})

        # 1. Platform Superuser
        self.superuser = User.objects.create_superuser(
            username="superuser@test.com", email="superuser@test.com", password="password123"
        )

        # 2. Platform Staff
        self.staff_user = User.objects.create_user(
            username="staff@test.com", email="staff@test.com", password="password123", is_staff=True
        )

        # 3. Normal CRM user with organization
        self.crm_user = User.objects.create_user(
            username="crmuser@test.com", email="crmuser@test.com", password="password123"
        )
        UserProfile.objects.filter(user=self.crm_user).update(
            user_type="USER", role=self.sales_role, organization=self.org
        )

        # 4. CRM user without organization
        self.no_org_user = User.objects.create_user(
            username="noorguser@test.com", email="noorguser@test.com", password="password123"
        )
        UserProfile.objects.filter(user=self.no_org_user).update(
            user_type="USER", role=self.sales_role, organization=None
        )

    def test_unauthenticated_request(self):
        me_url = reverse('accounts:api_me')
        response = self.client.get(me_url)
        self.assertEqual(response.status_code, 403)

    def test_platform_superuser_payload(self):
        self.client.login(username="superuser@test.com", password="password123")
        response = self.client.get(reverse('accounts:api_me'))
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['user_type'], 'ADMIN')
        self.assertEqual(data['role'], 'Administrator')
        self.assertTrue(data['permissions']['leads']['view'])
        self.assertTrue(data['permissions']['leads']['delete'])

    def test_platform_staff_payload(self):
        self.client.login(username="staff@test.com", password="password123")
        response = self.client.get(reverse('accounts:api_me'))
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['user_type'], 'ADMIN')
        self.assertEqual(data['role'], 'Administrator')
        self.assertTrue(data['permissions']['leads']['view'])

    def test_crm_user_with_organization_payload(self):
        self.client.login(username="crmuser@test.com", password="password123")
        response = self.client.get(reverse('accounts:api_me'))
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['user_type'], 'USER')
        self.assertEqual(data['role'], 'Salesperson')
        self.assertEqual(data['profile']['organization']['name'], "Authorized Corp")

        # Verify effective permissions
        self.assertTrue(data['permissions']['leads']['view'])
        # Salesperson leads delete permission is NONE (False)
        self.assertFalse(data['permissions']['leads'].get('delete', False))

    def test_crm_user_without_organization_payload(self):
        self.client.login(username="noorguser@test.com", password="password123")
        response = self.client.get(reverse('accounts:api_me'))
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['user_type'], 'USER')
        self.assertIsNone(data['profile']['organization'])


class ChangePasswordAPITests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            username="changeme@test.com",
            email="changeme@test.com",
            password="OldPassword123!",
            is_active=True
        )
        self.change_url = reverse('accounts:api_change_password')

    def test_unauthenticated_request(self):
        response = self.client.post(self.change_url, {})
        self.assertEqual(response.status_code, 403)

    def test_missing_fields(self):
        self.client.login(username="changeme@test.com", password="OldPassword123!")
        
        # 1. Missing current_password
        res1 = self.client.post(self.change_url, {
            "new_password": "NewPassword123!",
            "confirm_new_password": "NewPassword123!"
        })
        self.assertEqual(res1.status_code, 400)
        self.assertIn("All fields are required.", res1.json()["message"])

        # 2. Missing new_password
        res2 = self.client.post(self.change_url, {
            "current_password": "OldPassword123!",
            "confirm_new_password": "NewPassword123!"
        })
        self.assertEqual(res2.status_code, 400)

        # 3. Missing confirm_new_password
        res3 = self.client.post(self.change_url, {
            "current_password": "OldPassword123!",
            "new_password": "NewPassword123!"
        })
        self.assertEqual(res3.status_code, 400)

    def test_incorrect_current_password(self):
        self.client.login(username="changeme@test.com", password="OldPassword123!")
        response = self.client.post(self.change_url, {
            "current_password": "WrongPassword123!",
            "new_password": "NewPassword123!",
            "confirm_new_password": "NewPassword123!"
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Incorrect current password.", response.json()["message"])

    def test_new_password_mismatch(self):
        self.client.login(username="changeme@test.com", password="OldPassword123!")
        response = self.client.post(self.change_url, {
            "current_password": "OldPassword123!",
            "new_password": "NewPassword123!",
            "confirm_new_password": "DifferentPassword123!"
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("New passwords do not match.", response.json()["message"])

    def test_weak_password(self):
        self.client.login(username="changeme@test.com", password="OldPassword123!")
        response = self.client.post(self.change_url, {
            "current_password": "OldPassword123!",
            "new_password": "123",
            "confirm_new_password": "123"
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Weak password.", response.json()["message"])
        self.assertIn("new_password", response.json()["errors"])

    def test_successful_password_change_flow(self):
        # 1. Login with old password
        login_success = self.client.login(username="changeme@test.com", password="OldPassword123!")
        self.assertTrue(login_success)

        # 2. Change password
        response = self.client.post(self.change_url, {
            "current_password": "OldPassword123!",
            "new_password": "NewSecurePassword123!",
            "confirm_new_password": "NewSecurePassword123!"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Password changed successfully")

        # 3. Verify session remains valid (check me endpoint succeeds without relogging)
        me_response = self.client.get(reverse('accounts:api_me'))
        self.assertEqual(me_response.status_code, 200)

        # 4. Logout of the client session
        self.client.logout()

        # 5. Old password no longer authenticates
        login_old = self.client.login(username="changeme@test.com", password="OldPassword123!")
        self.assertFalse(login_old)

        # 6. New password authenticates successfully
        login_new = self.client.login(username="changeme@test.com", password="NewSecurePassword123!")
        self.assertTrue(login_new)


class RegistrationReapplyAPITests(TestCase):
    def setUp(self):
        self.register_url = reverse('accounts:api_register')
        self.login_url = reverse('accounts:api_login')
        self.admin_user = User.objects.create_superuser(
            username="admin@platform.com",
            email="admin@platform.com",
            password="adminpassword123"
        )
        self.signup_data = {
            "email": "testowner@test.com",
            "password": "ownerpassword123",
            "first_name": "John",
            "last_name": "Doe",
            "company_name": "Test Organization",
            "cnic": "11111-2222222-3",
            "phone_number": "0333-1112223",
            "country": "Pakistan",
            "address": "456 Avenue, Karachi"
        }

    def test_reapply_lifecycle_and_rules(self):
        # 1. Normal registration works
        res = self.client.post(self.register_url, self.signup_data, content_type='application/json')
        self.assertEqual(res.status_code, 201)

        # 2. Duplicate pending email is rejected
        res_dup_pending = self.client.post(self.register_url, self.signup_data, content_type='application/json')
        self.assertEqual(res_dup_pending.status_code, 400)
        self.assertIn("A user with this email address already exists.", res_dup_pending.json()["errors"]["email"])

        # Reject the registration via admin endpoint
        user = User.objects.get(email="testowner@test.com")
        reg_req = RegistrationRequest.objects.get(owner_profile=user.ownerprofile)
        self.client.login(username="admin@platform.com", password="adminpassword123")
        reject_url = reverse('accounts:api_admin_reject', kwargs={'pk': reg_req.pk})
        res_reject = self.client.post(reject_url, {"reason": "Document invalid"}, content_type='application/json')
        self.assertEqual(res_reject.status_code, 200)
        self.client.logout()

        # 3. Rejected user attempts login, rejection reason is returned
        login_res = self.client.post(self.login_url, {
            "username": "testowner@test.com",
            "password": "ownerpassword123"
        }, content_type='application/json')
        self.assertEqual(login_res.status_code, 403)
        self.assertIn("Your registration was rejected. Reason: Document invalid", login_res.json()["message"])

        # 4. Rejected registration can reapply (using same signup payload with updated name and address)
        reapply_data = self.signup_data.copy()
        reapply_data["first_name"] = "John Updated"
        reapply_data["address"] = "789 Street, Lahore"
        reapply_res = self.client.post(self.register_url, reapply_data, content_type='application/json')
        self.assertEqual(reapply_res.status_code, 201)

        # 5. Reapplication returns RegistrationRequest to pending, clears reason, updates data
        reg_req.refresh_from_db()
        self.assertEqual(reg_req.status, "pending")
        self.assertIsNone(reg_req.rejection_reason)
        
        user.refresh_from_db()
        self.assertEqual(user.first_name, "John Updated")
        self.assertEqual(user.ownerprofile.address, "789 Street, Lahore")

        # 6. Reapplied user remains inactive
        self.assertFalse(user.is_active)
        self.assertFalse(user.ownerprofile.organization.is_active)

        # 7. Admin can approve the reapplied registration
        self.client.login(username="admin@platform.com", password="adminpassword123")
        approve_url = reverse('accounts:api_admin_approve', kwargs={'pk': reg_req.pk})
        with self.captureOnCommitCallbacks(execute=True):
            res_approve = self.client.post(approve_url)
        self.assertEqual(res_approve.status_code, 200)

        # Verify active states
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.ownerprofile.organization.is_active)
        self.client.logout()

        # 8. Duplicate approved/active email is rejected
        res_dup_active = self.client.post(self.register_url, self.signup_data, content_type='application/json')
        self.assertEqual(res_dup_active.status_code, 400)


class UsernameEmailLoginTests(TestCase):
    def setUp(self):
        # Create a user with distinct username and email
        self.salesperson = User.objects.create_user(
            username="salesperson1",
            email="sp1@gmail.com",
            password="Password123",
            is_active=True
        )
        
        # Create an admin user where username == email
        self.admin = User.objects.create_superuser(
            username="admin@bms.com",
            email="admin@bms.com",
            password="Password123",
            is_active=True
        )
        
        # Create a manager user where username == email
        self.manager = User.objects.create_user(
            username="mz@gmail.com",
            email="mz@gmail.com",
            password="Password123",
            is_active=True
        )

    def test_valid_username_login(self):
        # Test A: Valid username login -> 200
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "salesperson1",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["username"], "salesperson1")

    def test_valid_email_login(self):
        # Test B: Valid email login -> 200
        # Test H: Existing salesperson login works using email
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "sp1@gmail.com",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["username"], "salesperson1")

    def test_invalid_email_login(self):
        # Test C: Invalid email -> 401
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "nonexistent@gmail.com",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_invalid_username_login(self):
        # Test D: Invalid username -> 401
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "nonexistentuser",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_correct_identifier_wrong_password(self):
        # Test E: Correct identifier + wrong password -> 401
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "salesperson1",
            "password": "WrongPassword"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 401)

        response_email = self.client.post(url, {
            "username": "sp1@gmail.com",
            "password": "WrongPassword"
        }, content_type='application/json')
        self.assertEqual(response_email.status_code, 401)

    def test_admin_login_works(self):
        # Test F: Existing admin login still works
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "admin@bms.com",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_manager_login_works(self):
        # Test G: Existing manager login still works
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "mz@gmail.com",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_session_and_me_view_integration(self):
        # Test I: Existing session creation remains intact
        # Test J: /api/me/ works after successful login
        url = reverse('accounts:api_login')
        response = self.client.post(url, {
            "username": "sp1@gmail.com",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        # Verify session is stored and /api/me/ returns authenticated data
        me_url = reverse('accounts:api_me')
        me_response = self.client.get(me_url)
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["data"]["username"], "salesperson1")



