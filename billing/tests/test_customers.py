from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from accounts.models import Organization, OwnerProfile
from billing.models import BillingCustomer
from billing.services import CustomerService
from roles.models import Role, RolePermission, CRMResource
from roles.services import PermissionService

from billing.tests.helpers import setup_billing_test_permissions

User = get_user_model()


class BillingCustomerAPITestCase(APITestCase):
    def setUp(self):
        # 1. Setup Roles
        self.admin_role, _ = Role.objects.get_or_create(
            name='Administrator',
            defaults={'is_system': True, 'description': 'Admin'}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name='Manager',
            defaults={'is_system': True, 'description': 'Manager'}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name='Salesperson',
            defaults={'is_system': True, 'description': 'Salesperson'}
        )

        # 2. Setup permissions for granular billing resources
        setup_billing_test_permissions(admin_role=self.admin_role, manager_role=self.manager_role, sales_role=self.sales_role)

        # 3. Create Organizations
        self.org1 = Organization.objects.create(name="Acme Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Beta Org 2", is_active=True)

        # 4. Create Users for Org 1
        self.admin_user = User.objects.create_user(username='org1_admin', email='admin@org1.com', password='password123')
        self.admin_user.profile.organization = self.org1
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()

        self.manager_user = User.objects.create_user(username='org1_manager', email='mgr@org1.com', password='password123')
        self.manager_user.profile.organization = self.org1
        self.manager_user.profile.role = self.manager_role
        self.manager_user.profile.save()

        self.sales1 = User.objects.create_user(username='org1_sales1', email='sales1@org1.com', password='password123')
        self.sales1.profile.organization = self.org1
        self.sales1.profile.role = self.sales_role
        self.sales1.profile.save()

        self.sales2 = User.objects.create_user(username='org1_sales2', email='sales2@org1.com', password='password123')
        self.sales2.profile.organization = self.org1
        self.sales2.profile.role = self.sales_role
        self.sales2.profile.save()

        # Org Owner for Org 1
        self.owner_user = User.objects.create_user(username='org1_owner', email='owner@org1.com', password='password123')
        OwnerProfile.objects.create(
            user=self.owner_user,
            organization=self.org1,
            cnic='12345',
            phone_number='12345',
            country='USA'
        )

        # Users for Org 2
        self.org2_admin = User.objects.create_user(username='org2_admin', email='admin@org2.com', password='password123')
        self.org2_admin.profile.organization = self.org2
        self.org2_admin.profile.role = self.admin_role
        self.org2_admin.profile.save()

        self.org2_sales = User.objects.create_user(username='org2_sales', email='sales@org2.com', password='password123')
        self.org2_sales.profile.organization = self.org2
        self.org2_sales.profile.role = self.sales_role
        self.org2_sales.profile.save()

        # URLs
        self.list_url = '/api/v1/billing/customers/'
        self.detail_url = lambda pk: f'/api/v1/billing/customers/{pk}/'

        # Clear permission cache before tests
        for u in [self.admin_user, self.manager_user, self.sales1, self.sales2, self.owner_user, self.org2_admin, self.org2_sales]:
            PermissionService.clear_user_permission_cache(u.id)

    # 1. Global Uniqueness
    def test_customer_number_global_uniqueness(self):
        BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-00001',
            name='Customer 1'
        )
        with self.assertRaises(IntegrityError):
            BillingCustomer.objects.create(
                organization=self.org2,
                customer_number='CUST-00001',
                name='Customer 2 Duplicate'
            )

    # 2. Automatic Numbering
    def test_customer_number_auto_generation(self):
        self.client.force_authenticate(user=self.admin_user)
        res1 = self.client.post(self.list_url, {'name': 'First Customer'}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res1.data['customer_number'], 'CUST-00001')

        res2 = self.client.post(self.list_url, {'name': 'Second Customer'}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res2.data['customer_number'], 'CUST-00002')

    # 3. Explicit Customer Number Creation
    def test_customer_number_explicit_on_post(self):
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(self.list_url, {
            'name': 'Custom ID Customer',
            'customer_number': '  CUSTOM-999  '
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['customer_number'], 'CUSTOM-999')

        # Next auto customer should continue from highest CUST-XXXXX
        res_auto = self.client.post(self.list_url, {'name': 'Next Auto'}, format='json')
        self.assertEqual(res_auto.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_auto.data['customer_number'], 'CUST-00001')

    # 4. Customer Number Immutability on PUT/PATCH
    def test_customer_number_immutable_on_put_patch(self):
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(self.list_url, {'name': 'Original Name'}, format='json')
        cust_id = res.data['id']
        orig_number = res.data['customer_number']

        # Attempt to change via PATCH
        res_patch = self.client.patch(self.detail_url(cust_id), {
            'customer_number': 'CUST-CHANGED'
        }, format='json')
        self.assertEqual(res_patch.status_code, status.HTTP_400_BAD_REQUEST)
        error_dict = res_patch.data.get('errors', res_patch.data)
        self.assertIn('customer_number', error_dict)

        # Verify unchanged
        cust = BillingCustomer.objects.get(id=cust_id)
        self.assertEqual(cust.customer_number, orig_number)

    # 5. Collision Retry Logic
    def test_customer_number_concurrency_collision_retry(self):
        # Pre-create CUST-00001 directly in DB
        BillingCustomer.objects.create(organization=self.org1, customer_number='CUST-00001', name='Collision Pre-seed')

        self.client.force_authenticate(user=self.admin_user)
        # Creating next should detect CUST-00001 exists and generate CUST-00002
        res = self.client.post(self.list_url, {'name': 'Retry Winner'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['customer_number'], 'CUST-00002')

    # 6. Unrelated IntegrityError Propagation
    def test_unrelated_integrity_error_propagation(self):
        with patch.object(BillingCustomer.objects, 'create', side_effect=IntegrityError("FOREIGN KEY constraint failed")):
            with self.assertRaises(IntegrityError):
                CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Bad FK'})

    # 7. CUST-99999 Exhaustion Limit
    def test_cust_99999_exhaustion_limit(self):
        BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-99999',
            name='Max Customer'
        )
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(self.list_url, {'name': 'Overflow Customer'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Customer number sequence limit reached', str(res.data))

    # 8. Customer Search
    def test_customer_search(self):
        c1 = CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Alice Smith', 'email': 'alice@domain.com'})
        c2 = CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Bob Jones', 'email': 'bob@acme.com'})
        c3 = CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Charlie Smith', 'email': 'charlie@other.com'})

        self.client.force_authenticate(user=self.admin_user)
        # Search by name
        res_name = self.client.get(f'{self.list_url}?search=Smith')
        self.assertEqual(res_name.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_name.data), 2)

        # Search by email
        res_email = self.client.get(f'{self.list_url}?search=acme.com')
        self.assertEqual(len(res_email.data), 1)
        self.assertEqual(res_email.data[0]['name'], 'Bob Jones')

        # Search by customer number
        res_num = self.client.get(f'{self.list_url}?search={c1.customer_number}')
        self.assertEqual(len(res_num.data), 1)
        self.assertEqual(res_num.data[0]['id'], c1.id)

    # 9. External Reference Filtering
    def test_external_reference_id_query_parameter(self):
        c1 = CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Ext Ref 1', 'external_reference_id': 'EXT-ALPHA'})
        c2 = CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Ext Ref 2', 'external_reference_id': 'EXT-BETA'})

        self.client.force_authenticate(user=self.admin_user)
        res = self.client.get(f'{self.list_url}?external_reference_id=EXT-ALPHA')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['external_reference_id'], 'EXT-ALPHA')

    # 10. Administrator CRUD Permissions
    def test_admin_crud_permissions(self):
        self.client.force_authenticate(user=self.admin_user)
        # Create
        res_c = self.client.post(self.list_url, {'name': 'Admin Client'}, format='json')
        self.assertEqual(res_c.status_code, status.HTTP_201_CREATED)
        cid = res_c.data['id']

        # View
        res_v = self.client.get(self.detail_url(cid))
        self.assertEqual(res_v.status_code, status.HTTP_200_OK)

        # Edit
        res_e = self.client.patch(self.detail_url(cid), {'name': 'Admin Client Renamed'}, format='json')
        self.assertEqual(res_e.status_code, status.HTTP_200_OK)
        self.assertEqual(res_e.data['name'], 'Admin Client Renamed')

        # Delete (Deactivate)
        res_d = self.client.delete(self.detail_url(cid))
        self.assertEqual(res_d.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BillingCustomer.objects.get(id=cid).is_active)

    # 11. Manager CRUD Permissions
    def test_manager_crud_permissions(self):
        self.client.force_authenticate(user=self.manager_user)
        res_c = self.client.post(self.list_url, {'name': 'Manager Client'}, format='json')
        self.assertEqual(res_c.status_code, status.HTTP_201_CREATED)
        cid = res_c.data['id']

        res_e = self.client.patch(self.detail_url(cid), {'phone': '+1999999999'}, format='json')
        self.assertEqual(res_e.status_code, status.HTTP_200_OK)
        self.assertEqual(res_e.data['phone'], '+1999999999')

        res_d = self.client.delete(self.detail_url(cid))
        self.assertEqual(res_d.status_code, status.HTTP_204_NO_CONTENT)

    # 12. Salesperson OWN View & Edit
    def test_salesperson_own_view_and_edit(self):
        # Create customer owned by sales1
        c1 = CustomerService.create_customer(self.org1, self.sales1, {'name': 'Sales1 Client'})
        # Create customer owned by sales2
        c2 = CustomerService.create_customer(self.org1, self.sales2, {'name': 'Sales2 Client'})

        self.client.force_authenticate(user=self.sales1)

        # Sales1 list only contains c1
        res_list = self.client.get(self.list_url)
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        ids = [c['id'] for c in res_list.data]
        self.assertIn(c1.id, ids)
        self.assertNotIn(c2.id, ids)

        # Sales1 can edit c1
        res_edit = self.client.patch(self.detail_url(c1.id), {'name': 'Sales1 Updated'}, format='json')
        self.assertEqual(res_edit.status_code, status.HTTP_200_OK)

        # Sales1 CANNOT edit c2 (returns 403 or 404 because out of scoped queryset)
        res_edit_c2 = self.client.patch(self.detail_url(c2.id), {'name': 'Hacked'}, format='json')
        self.assertIn(res_edit_c2.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    # 13. Salesperson Create Assigns created_by
    def test_salesperson_create_assigns_created_by(self):
        self.client.force_authenticate(user=self.sales1)
        res = self.client.post(self.list_url, {'name': 'Salesperson Created'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        cust = BillingCustomer.objects.get(id=res.data['id'])
        self.assertEqual(cust.metadata.get('created_by_id'), self.sales1.id)

    # 14. Salesperson DELETE Denied
    def test_salesperson_delete_denied(self):
        c1 = CustomerService.create_customer(self.org1, self.sales1, {'name': 'Sales1 Client'})
        self.client.force_authenticate(user=self.sales1)
        res_del = self.client.delete(self.detail_url(c1.id))
        self.assertEqual(res_del.status_code, status.HTTP_403_FORBIDDEN)

    # 15. Cross-Owner Salesperson Access Denied (Same Tenant)
    def test_cross_owner_salesperson_access_denied(self):
        c2 = CustomerService.create_customer(self.org1, self.sales2, {'name': 'Sales2 Exclusive'})
        self.client.force_authenticate(user=self.sales1)

        res_detail = self.client.get(self.detail_url(c2.id))
        self.assertIn(res_detail.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    # 16. Cross-Tenant Isolation
    def test_cross_tenant_isolation(self):
        c_org2 = CustomerService.create_customer(self.org2, self.org2_admin, {'name': 'Org2 Secret Customer'})

        # Org1 Admin cannot see or access Org2 Customer
        self.client.force_authenticate(user=self.admin_user)
        res_list = self.client.get(self.list_url)
        self.assertNotIn(c_org2.id, [c['id'] for c in res_list.data])

        res_detail = self.client.get(self.detail_url(c_org2.id))
        self.assertIn(res_detail.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    # 17. Email Normalization and Validation
    def test_email_normalization_and_validation(self):
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(self.list_url, {
            'name': 'Email Test',
            'email': '  TEST.USER@EXAMPLE.COM  '
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['email'], 'test.user@example.com')

    # 18. Address Authoritative Normalization
    def test_address_authoritative_normalization(self):
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(self.list_url, {
            'name': 'Address Test',
            'billing_address_line1': '  123 Main St  ',
            'billing_city': '  New York  ',
            'billing_postal_code': ' 10001 '
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['billing_address_line1'], '123 Main St')
        self.assertEqual(res.data['billing_city'], 'New York')
        self.assertEqual(res.data['billing_postal_code'], '10001')

    # 19. Tax ID Case Preserved and Trimmed
    def test_tax_id_case_preserved_trimmed(self):
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(self.list_url, {
            'name': 'Tax Test',
            'tax_id': '  Vat-12345-aBc  '
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['tax_id'], 'Vat-12345-aBc')

    # 20. Payment Reference Safety
    def test_payment_reference_safety(self):
        self.client.force_authenticate(user=self.admin_user)
        # Valid safe token
        res_valid = self.client.post(self.list_url, {
            'name': 'Token Customer',
            'default_payment_method_id': 'pm_tok_12345abcde'
        }, format='json')
        self.assertEqual(res_valid.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_valid.data['default_payment_method_id'], 'pm_tok_12345abcde')

        # Invalid raw card number (16 digits)
        res_raw = self.client.post(self.list_url, {
            'name': 'Raw Card Customer',
            'default_payment_method_id': '4111 1111 1111 1111'
        }, format='json')
        self.assertEqual(res_raw.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Raw credit card numbers are prohibited', str(res_raw.data))

    # 21. DELETE Deactivation (Soft Delete)
    def test_delete_deactivation(self):
        c = CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Deactivate Me'})
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.delete(self.detail_url(c.id))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

        c.refresh_from_db()
        self.assertFalse(c.is_active)

    # 22. PATCH Reactivation
    def test_patch_reactivation(self):
        c = CustomerService.create_customer(self.org1, self.admin_user, {'name': 'Reactivate Me'})
        c.is_active = False
        c.save()

        self.client.force_authenticate(user=self.admin_user)
        res = self.client.patch(self.detail_url(c.id), {'is_active': True}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['is_active'])

        c.refresh_from_db()
        self.assertTrue(c.is_active)

    # 23. Search and Filters Preserve RBAC and Tenant Boundaries
    def test_search_and_filters_preserve_rbac_and_tenant_boundaries(self):
        # Create customer for Sales2 in Org1
        c_sales2 = CustomerService.create_customer(self.org1, self.sales2, {'name': 'Common Keyword', 'external_reference_id': 'KEYWORD-REF'})
        # Create customer for Org2
        c_org2 = CustomerService.create_customer(self.org2, self.org2_admin, {'name': 'Common Keyword', 'external_reference_id': 'KEYWORD-REF'})
        # Create customer for Sales1 in Org1
        c_sales1 = CustomerService.create_customer(self.org1, self.sales1, {'name': 'Common Keyword', 'external_reference_id': 'KEYWORD-REF'})

        # Sales1 searches for 'Common Keyword'
        self.client.force_authenticate(user=self.sales1)
        res_search = self.client.get(f'{self.list_url}?search=Common')
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        ids = [x['id'] for x in res_search.data]
        self.assertEqual(ids, [c_sales1.id])  # MUST ONLY see their own record in Org1

        # Sales1 filters by external reference
        res_ext = self.client.get(f'{self.list_url}?external_reference_id=KEYWORD-REF')
        self.assertEqual(res_ext.status_code, status.HTTP_200_OK)
        ids_ext = [x['id'] for x in res_ext.data]
        self.assertEqual(ids_ext, [c_sales1.id])  # MUST ONLY see their own record in Org1
