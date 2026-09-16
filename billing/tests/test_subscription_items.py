from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organization
from billing.models import BillingCustomer, Subscription, SubscriptionItem, AddOn
from catalog.models.plan import PricingPlan
from catalog.models.product import Product
from roles.models import Role, RolePermission, CRMResource

User = get_user_model()


from billing.tests.helpers import setup_billing_test_permissions


class SubscriptionItemServiceAndAPITestCase(APITestCase):
    def setUp(self):
        # 1. Setup CRM permissions
        self.admin_role, _ = Role.objects.get_or_create(
            name='Administrator',
            defaults={'is_system': True, 'description': 'Admin'}
        )
        setup_billing_test_permissions(admin_role=self.admin_role)

        # 2. Setup Organizations and Users
        self.org1 = Organization.objects.create(name="Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Org 2", is_active=True)

        self.user1 = User.objects.create_user(username='item_user1', email='item1@org1.com', password='password123')
        self.user1.profile.organization = self.org1
        self.user1.profile.role = self.admin_role
        self.user1.profile.save()

        self.user2 = User.objects.create_user(username='item_user2', email='item2@org2.com', password='password123')
        self.user2.profile.organization = self.org2
        self.user2.profile.role = self.admin_role
        self.user2.profile.save()

        # 3. Create Product, PricingPlans, and AddOns
        self.product = Product.objects.create(name="Core Product", is_active=True)

        self.plan_monthly = PricingPlan.objects.create(
            product=self.product,
            name="Monthly Plan",
            price=Decimal('100.00'),
            billing_cycle='monthly',
            is_active=True
        )
        self.plan_yearly = PricingPlan.objects.create(
            product=self.product,
            name="Yearly Plan",
            price=Decimal('1200.00'),
            billing_cycle='yearly',
            is_active=True
        )

        self.addon_storage = AddOn.objects.create(
            product=self.product,
            name="Extra Storage",
            code="extra-storage",
            price=Decimal('20.00'),
            billing_cycle='monthly',
            max_quantity=5,
            is_active=True
        )

        self.addon_onetime = AddOn.objects.create(
            product=self.product,
            name="Setup Fee",
            code="setup-fee",
            price=Decimal('150.00'),
            billing_cycle='one_time',
            is_active=True
        )

        # 4. Create Customers and Subscriptions
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-10001',
            name='Acme Corp',
            email='acme@corp.com'
        )

        self.subscription1 = Subscription.objects.create(
            customer=self.customer1,
            subscription_number='SUB-10001',
            status='LIVE',
            current_term_start=date.today() - timedelta(days=5),
            current_term_end=date.today() + timedelta(days=25),
            metadata={'created_by_id': self.user1.id}
        )

    def test_plan_transactional_replacement_option_1a(self):
        """
        Attaching a new PLAN replaces the existing PLAN item transactionally (Option 1A).
        """
        self.client.force_authenticate(user=self.user1)
        url = reverse('billing-subscription-items', kwargs={'pk': self.subscription1.id})

        # Attach first plan
        resp1 = self.client.post(url, {'item_type': 'PLAN', 'plan': self.plan_monthly.id}, format='json')
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.subscription1.items.filter(item_type='PLAN').count(), 1)
        self.assertEqual(self.subscription1.items.get(item_type='PLAN').plan, self.plan_monthly)

        # Attach second plan
        resp2 = self.client.post(url, {'item_type': 'PLAN', 'plan': self.plan_yearly.id}, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)

        # Confirm exact 1 PLAN item exists, and it is plan_yearly
        self.assertEqual(self.subscription1.items.filter(item_type='PLAN').count(), 1)
        self.assertEqual(self.subscription1.items.get(item_type='PLAN').plan, self.plan_yearly)

    def test_multiple_addons_allowed(self):
        """
        Multiple ADDON items are allowed on a single subscription.
        """
        self.client.force_authenticate(user=self.user1)
        url = reverse('billing-subscription-items', kwargs={'pk': self.subscription1.id})

        resp1 = self.client.post(url, {'item_type': 'ADDON', 'addon': self.addon_storage.id, 'quantity': 2}, format='json')
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        resp2 = self.client.post(url, {'item_type': 'ADDON', 'addon': self.addon_onetime.id, 'quantity': 1}, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)

        self.assertEqual(self.subscription1.items.filter(item_type='ADDON').count(), 2)

    def test_historical_pricing_snapshot(self):
        """
        Snapshot price is recorded at item creation. Updating catalog price does not affect active subscription items.
        """
        self.client.force_authenticate(user=self.user1)
        url = reverse('billing-subscription-items', kwargs={'pk': self.subscription1.id})

        resp = self.client.post(url, {'item_type': 'PLAN', 'plan': self.plan_monthly.id}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        item = self.subscription1.items.get(item_type='PLAN')
        self.assertEqual(item.unit_price, Decimal('100.00'))

        # Alter catalog price
        self.plan_monthly.price = Decimal('150.00')
        self.plan_monthly.save()

        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal('100.00'))

    def test_addon_max_quantity_validation(self):
        """
        Quantity exceeding add-on max_quantity is rejected.
        """
        self.client.force_authenticate(user=self.user1)
        url = reverse('billing-subscription-items', kwargs={'pk': self.subscription1.id})

        # max_quantity for addon_storage is 5
        resp = self.client.post(url, {'item_type': 'ADDON', 'addon': self.addon_storage.id, 'quantity': 10}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        errs = resp.data.get('errors') if isinstance(resp.data, dict) and 'errors' in resp.data else resp.data
        self.assertIn('quantity', errs)

    def test_mrr_calculation_and_active_date_filtering_option_2a(self):
        """
        MRR calculation sums active items based on option 2A (start_date <= today <= end_date or null).
        Yearly plans contribute price / 12 to MRR. One-time addons contribute 0.
        """
        self.client.force_authenticate(user=self.user1)
        url = reverse('billing-subscription-items', kwargs={'pk': self.subscription1.id})

        # Add active monthly plan ($100/mo) -> MRR 100
        self.client.post(url, {'item_type': 'PLAN', 'plan': self.plan_monthly.id}, format='json')
        # Add active storage addon ($20/mo x 2) -> MRR 40
        self.client.post(url, {'item_type': 'ADDON', 'addon': self.addon_storage.id, 'quantity': 2}, format='json')
        # Add setup fee addon ($150 one_time) -> MRR 0
        self.client.post(url, {'item_type': 'ADDON', 'addon': self.addon_onetime.id, 'quantity': 1}, format='json')

        self.subscription1.refresh_from_db()
        self.assertEqual(self.subscription1.cached_mrr, Decimal('140.00'))
        self.assertEqual(self.subscription1.cached_arr, Decimal('1680.00'))

        # Add expired item (end_date in past) -> Should NOT contribute to MRR
        SubscriptionItem.objects.create(
            subscription=self.subscription1,
            item_type='ADDON',
            addon=self.addon_storage,
            quantity=3,
            unit_price=Decimal('20.00'),
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() - timedelta(days=1)
        )
        from billing.services import SubscriptionItemService
        SubscriptionItemService.recalculate_subscription_mrr_arr(self.subscription1)

        self.subscription1.refresh_from_db()
        self.assertEqual(self.subscription1.cached_mrr, Decimal('140.00'))

    def test_catalog_selection_apis_option_3a(self):
        """
        GET available-plans and available-addons returns active catalog items.
        """
        self.client.force_authenticate(user=self.user1)
        url_plans = reverse('billing-subscription-available-plans')
        url_addons = reverse('billing-subscription-available-addons')

        res_plans = self.client.get(url_plans)
        self.assertEqual(res_plans.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_plans.data), 2)

        res_addons = self.client.get(url_addons)
        self.assertEqual(res_addons.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_addons.data), 2)

    def test_delete_subscription_item_option_4a(self):
        """
        DELETE /api/v1/billing/subscriptions/<id>/items/<item_id>/ removes item and recalculates MRR.
        """
        self.client.force_authenticate(user=self.user1)
        url_add = reverse('billing-subscription-items', kwargs={'pk': self.subscription1.id})
        res_add = self.client.post(url_add, {'item_type': 'PLAN', 'plan': self.plan_monthly.id}, format='json')
        item_id = res_add.data['id']

        self.subscription1.refresh_from_db()
        self.assertEqual(self.subscription1.cached_mrr, Decimal('100.00'))

        url_delete = reverse('billing-subscription-remove-item', kwargs={'pk': self.subscription1.id, 'item_id': item_id})
        res_del = self.client.delete(url_delete)
        self.assertEqual(res_del.status_code, status.HTTP_204_NO_CONTENT)

        self.subscription1.refresh_from_db()
        self.assertEqual(self.subscription1.cached_mrr, Decimal('0.00'))
        self.assertEqual(self.subscription1.items.count(), 0)

    def test_tenant_isolation_on_item_operations(self):
        """
        User from Org 2 cannot attach or delete items on Org 1 subscription.
        """
        self.client.force_authenticate(user=self.user2)
        url_add = reverse('billing-subscription-items', kwargs={'pk': self.subscription1.id})

        res_add = self.client.post(url_add, {'item_type': 'PLAN', 'plan': self.plan_monthly.id}, format='json')
        self.assertEqual(res_add.status_code, status.HTTP_404_NOT_FOUND)
