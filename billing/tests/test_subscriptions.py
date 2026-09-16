from datetime import date, timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from accounts.models import Organization
from billing.models import BillingCustomer, Subscription
from billing.services import SubscriptionService
from roles.models import Role, RolePermission, CRMResource

from billing.tests.helpers import setup_billing_test_permissions

User = get_user_model()


class BillingSubscriptionAPITestCase(APITestCase):
    def setUp(self):
        # 1. Setup Roles and permissions
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

        setup_billing_test_permissions(admin_role=self.admin_role, manager_role=self.manager_role, sales_role=self.sales_role)

        # 3. Create Organizations
        self.org1 = Organization.objects.create(name="Acme Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Beta Org 2", is_active=True)

        # 4. Create Users for Org 1
        self.admin_user = User.objects.create_user(username='sub_org1_admin', email='sub_admin@org1.com', password='password123')
        self.admin_user.profile.organization = self.org1
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()

        self.manager_user = User.objects.create_user(username='sub_org1_manager', email='sub_mgr@org1.com', password='password123')
        self.manager_user.profile.organization = self.org1
        self.manager_user.profile.role = self.manager_role
        self.manager_user.profile.save()

        self.sales1 = User.objects.create_user(username='sub_sales1', email='sales1@org1.com', password='password123')
        self.sales1.profile.organization = self.org1
        self.sales1.profile.role = self.sales_role
        self.sales1.profile.save()

        self.sales2 = User.objects.create_user(username='sub_sales2', email='sales2@org1.com', password='password123')
        self.sales2.profile.organization = self.org1
        self.sales2.profile.role = self.sales_role
        self.sales2.profile.save()

        # Users for Org 2
        self.org2_user = User.objects.create_user(username='sub_org2_user', email='user@org2.com', password='password123')
        self.org2_user.profile.organization = self.org2
        self.org2_user.profile.role = self.admin_role
        self.org2_user.profile.save()

        # 5. Create Customers
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-00001',
            name='Acme Corp',
            email='billing@acme.com',
            currency='USD',
            metadata={'created_by_id': self.sales1.id}
        )

        self.customer2 = BillingCustomer.objects.create(
            organization=self.org2,
            customer_number='CUST-00002',
            name='Beta Corp',
            email='billing@beta.com',
            currency='USD',
            metadata={'created_by_id': self.org2_user.id}
        )

        self.list_url = reverse('billing-subscription-list')

    def test_subscription_creation_success(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            'customer': self.customer1.id,
            'collection_method': 'CHARGE_AUTOMATIC',
            'payment_terms_days': 30,
            'current_term_start': '2026-01-15',
            'billing_cycle': 'MONTHLY',
        }
        response = self.client.post(self.list_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['subscription_number'], 'SUB-00001')
        self.assertEqual(response.data['customer'], self.customer1.id)
        self.assertEqual(response.data['customer_name'], 'Acme Corp')
        self.assertEqual(response.data['status'], 'DRAFT')
        self.assertEqual(response.data['payment_terms_days'], 30)
        self.assertEqual(response.data['current_term_start'], '2026-01-15')
        self.assertEqual(response.data['current_term_end'], '2026-02-14')
        self.assertEqual(response.data['next_billing_date'], '2026-02-15')
        self.assertEqual(response.data['created_by'], self.admin_user.id)

    def test_subscription_number_auto_generation(self):
        self.client.force_authenticate(user=self.admin_user)
        sub1 = SubscriptionService.create_subscription(self.org1, self.admin_user, {'customer': self.customer1})
        sub2 = SubscriptionService.create_subscription(self.org1, self.admin_user, {'customer': self.customer1})
        self.assertEqual(sub1.subscription_number, 'SUB-00001')
        self.assertEqual(sub2.subscription_number, 'SUB-00002')

    def test_subscription_number_explicit_and_duplicate_rejection(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            'customer': self.customer1.id,
            'subscription_number': 'SUB-99999',
        }
        res1 = self.client.post(self.list_url, payload, format='json')
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res1.data['subscription_number'], 'SUB-99999')

        res2 = self.client.post(self.list_url, payload, format='json')
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        err_dict = res2.data.get('errors', res2.data)
        self.assertIn('subscription_number', err_dict)

    def test_subscription_number_collision_retry(self):
        # Seed SUB-00001
        Subscription.objects.create(customer=self.customer1, subscription_number='SUB-00001')
        orig_create = Subscription.objects.create
        with patch('billing.models.subscription.Subscription.objects.create') as mock_create:
            mock_create.side_effect = [
                IntegrityError("duplicate key value violates unique constraint 'subscription_number'"),
                orig_create(customer=self.customer1, subscription_number='SUB-00002')
            ]
            sub = SubscriptionService.create_subscription(self.org1, self.admin_user, {'customer': self.customer1})
            self.assertEqual(sub.subscription_number, 'SUB-00002')
            self.assertEqual(mock_create.call_count, 2)

    def test_subscription_number_immutability(self):
        sub = SubscriptionService.create_subscription(self.org1, self.admin_user, {'customer': self.customer1})
        detail_url = reverse('billing-subscription-detail', args=[sub.id])
        self.client.force_authenticate(user=self.admin_user)

        res = self.client.patch(detail_url, {'subscription_number': 'SUB-88888'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        err_dict = res.data.get('errors', res.data)
        self.assertIn('subscription_number', err_dict)

    def test_monthly_term_calculation(self):
        start, end, next_b = SubscriptionService.calculate_term_dates('2026-01-15', 'MONTHLY')
        self.assertEqual(start, date(2026, 1, 15))
        self.assertEqual(end, date(2026, 2, 14))
        self.assertEqual(next_b, date(2026, 2, 15))

    def test_yearly_term_calculation(self):
        start, end, next_b = SubscriptionService.calculate_term_dates('2026-01-15', 'YEARLY')
        self.assertEqual(start, date(2026, 1, 15))
        self.assertEqual(end, date(2027, 1, 14))
        self.assertEqual(next_b, date(2027, 1, 15))

    def test_month_end_edge_cases(self):
        # Jan 31 + 1 month in non-leap year (2026) -> Feb 28
        start, end, next_b = SubscriptionService.calculate_term_dates('2026-01-31', 'MONTHLY')
        self.assertEqual(start, date(2026, 1, 31))
        self.assertEqual(end, date(2026, 2, 27))
        self.assertEqual(next_b, date(2026, 2, 28))

        # Dec 15 -> Jan 15 crossover
        start2, end2, next_b2 = SubscriptionService.calculate_term_dates('2026-12-15', 'MONTHLY')
        self.assertEqual(start2, date(2026, 12, 15))
        self.assertEqual(end2, date(2027, 1, 14))
        self.assertEqual(next_b2, date(2027, 1, 15))

    def test_leap_year_edge_cases(self):
        # Leap year 2028: Jan 31 + 1 month -> Feb 29
        start, end, next_b = SubscriptionService.calculate_term_dates('2028-01-31', 'MONTHLY')
        self.assertEqual(start, date(2028, 1, 31))
        self.assertEqual(end, date(2028, 2, 28))
        self.assertEqual(next_b, date(2028, 2, 29))

        # Leap year 2028 Feb 29 + 1 year -> 2029 Feb 28 (non-leap year)
        start2, end2, next_b2 = SubscriptionService.calculate_term_dates('2028-02-29', 'YEARLY')
        self.assertEqual(start2, date(2028, 2, 29))
        self.assertEqual(end2, date(2029, 2, 27))
        self.assertEqual(next_b2, date(2029, 2, 28))

    def test_payment_terms_validation(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            'customer': self.customer1.id,
            'payment_terms_days': -5,
        }
        res = self.client.post(self.list_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        err_dict = res.data.get('errors', res.data)
        self.assertIn('payment_terms_days', err_dict)

    def test_tenant_isolation(self):
        sub_org1 = SubscriptionService.create_subscription(self.org1, self.admin_user, {'customer': self.customer1})
        sub_org2 = SubscriptionService.create_subscription(self.org2, self.org2_user, {'customer': self.customer2})

        self.client.force_authenticate(user=self.admin_user)
        res1 = self.client.get(self.list_url)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        sub_ids = [s['id'] for s in res1.data['results']] if isinstance(res1.data, dict) and 'results' in res1.data else [s['id'] for s in res1.data]
        self.assertIn(sub_org1.id, sub_ids)
        self.assertNotIn(sub_org2.id, sub_ids)

        # Cross tenant direct detail access blocked
        detail_url_org2 = reverse('billing-subscription-detail', args=[sub_org2.id])
        res_cross = self.client.get(detail_url_org2)
        self.assertIn(res_cross.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_rbac_admin_and_manager_access(self):
        sub = SubscriptionService.create_subscription(self.org1, self.admin_user, {'customer': self.customer1})
        detail_url = reverse('billing-subscription-detail', args=[sub.id])

        # Admin access
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get(detail_url)
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)

        # Manager access
        self.client.force_authenticate(user=self.manager_user)
        res_mgr = self.client.get(detail_url)
        self.assertEqual(res_mgr.status_code, status.HTTP_200_OK)

    def test_rbac_salesperson_ownership_restrictions(self):
        sub_sales1 = SubscriptionService.create_subscription(self.org1, self.sales1, {'customer': self.customer1})
        sub_sales2 = SubscriptionService.create_subscription(self.org1, self.sales2, {'customer': self.customer1})

        # Sales1 listing only shows sub_sales1
        self.client.force_authenticate(user=self.sales1)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        sub_ids = [s['id'] for s in res.data['results']] if 'results' in res.data else [s['id'] for s in res.data]
        self.assertIn(sub_sales1.id, sub_ids)
        self.assertNotIn(sub_sales2.id, sub_ids)

        # Sales1 accessing Sales2 subscription directly returns 404/403
        detail_sales2 = reverse('billing-subscription-detail', args=[sub_sales2.id])
        res_sales1_access_sales2 = self.client.get(detail_sales2)
        self.assertIn(res_sales1_access_sales2.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_serializer_validation(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {}  # missing customer
        res = self.client.post(self.list_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        err_dict = res.data.get('errors', res.data)
        self.assertIn('customer', err_dict)

    def test_api_list_search_and_status_filtering(self):
        sub1 = SubscriptionService.create_subscription(self.org1, self.admin_user, {
            'customer': self.customer1,
            'status': 'LIVE'
        })
        sub2 = SubscriptionService.create_subscription(self.org1, self.admin_user, {
            'customer': self.customer1,
            'status': 'DRAFT'
        })

        self.client.force_authenticate(user=self.admin_user)
        
        # Search by number
        res_search = self.client.get(f"{self.list_url}?search={sub1.subscription_number}")
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        results = res_search.data['results'] if 'results' in res_search.data else res_search.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], sub1.id)

        # Filter by status
        res_status = self.client.get(f"{self.list_url}?status=DRAFT")
        self.assertEqual(res_status.status_code, status.HTTP_200_OK)
        results_draft = res_status.data['results'] if 'results' in res_status.data else res_status.data
        self.assertTrue(all(s['status'] == 'DRAFT' for s in results_draft))

    def test_status_update_prohibited(self):
        sub = SubscriptionService.create_subscription(self.org1, self.admin_user, {'customer': self.customer1, 'status': 'DRAFT'})
        detail_url = reverse('billing-subscription-detail', args=[sub.id])
        self.client.force_authenticate(user=self.admin_user)

        res = self.client.patch(detail_url, {'status': 'LIVE'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        err_dict = res.data.get('errors', res.data)
        self.assertIn('status', err_dict)
