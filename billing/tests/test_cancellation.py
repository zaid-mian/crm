from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from accounts.models import Organization
from catalog.models.plan import PricingPlan
from catalog.models.product import Product
from billing.models import BillingCustomer, Subscription, SubscriptionItem, SubscriptionAuditLog, Invoice
from billing.services import SubscriptionLifecycleService, SubscriptionRenewalService, InvoicingEngineService
from roles.models import Role, RolePermission, CRMResource

from billing.tests.helpers import setup_billing_test_permissions

User = get_user_model()


class SubscriptionCancellationTestCase(APITestCase):
    def setUp(self):
        # 1. Roles & Permissions
        self.admin_role, _ = Role.objects.get_or_create(
            name='Administrator',
            defaults={'is_system': True, 'description': 'Admin'}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name='Salesperson',
            defaults={'is_system': True, 'description': 'Salesperson'}
        )
        self.no_perm_role, _ = Role.objects.get_or_create(
            name='NoPermRole',
            defaults={'is_system': False, 'description': 'No Billing Perms'}
        )

        resources = setup_billing_test_permissions(admin_role=self.admin_role, sales_role=self.sales_role)
        for res in resources.values():
            for act in ('VIEW', 'CREATE', 'EDIT', 'DELETE'):
                RolePermission.objects.get_or_create(role=self.no_perm_role, resource=res, action=act, defaults={'scope': 'NONE'})

        # 3. Organizations
        self.org1 = Organization.objects.create(name="Acme Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Beta Org 2", is_active=True)

        # 4. Users
        self.admin_user = User.objects.create_user(username='phase11_admin', email='admin@org1.com', password='password123')
        self.admin_user.profile.organization = self.org1
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()

        self.sales1 = User.objects.create_user(username='phase11_sales1', email='sales1@org1.com', password='password123')
        self.sales1.profile.organization = self.org1
        self.sales1.profile.role = self.sales_role
        self.sales1.profile.save()

        self.sales2 = User.objects.create_user(username='phase11_sales2', email='sales2@org1.com', password='password123')
        self.sales2.profile.organization = self.org1
        self.sales2.profile.role = self.sales_role
        self.sales2.profile.save()

        self.user_no_perm = User.objects.create_user(username='phase11_noperm', email='noperm@org1.com', password='password123')
        self.user_no_perm.profile.organization = self.org1
        self.user_no_perm.profile.role = self.no_perm_role
        self.user_no_perm.profile.save()

        self.org2_user = User.objects.create_user(username='phase11_org2_user', email='user@org2.com', password='password123')
        self.org2_user.profile.organization = self.org2
        self.org2_user.profile.role = self.admin_role
        self.org2_user.profile.save()

        # 5. Customers
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-11001',
            name='Acme Corp',
            email='billing@acme.com',
            currency='USD',
            metadata={'created_by_id': self.sales1.id}
        )

        self.customer2 = BillingCustomer.objects.create(
            organization=self.org2,
            customer_number='CUST-11002',
            name='Beta Corp',
            email='billing@beta.com',
            currency='USD',
            metadata={'created_by_id': self.org2_user.id}
        )

        # 6. Product & Plan
        self.product = Product.objects.create(name='Test CRM Pro', is_active=True)
        self.plan = PricingPlan.objects.create(
            product=self.product,
            name='Starter Plan',
            price=Decimal('100.00'),
            currency='USD',
            billing_cycle='monthly',
            is_active=True
        )

    def _create_subscription(self, customer, status='LIVE', created_by_id=None, pause_date=None, resume_date=None):
        sub = Subscription.objects.create(
            subscription_number=f'SUB-11{Subscription.objects.count():03d}',
            customer=customer,
            status=status,
            currency='USD',
            collection_method='CHARGE_AUTOMATIC',
            current_term_start=date(2026, 9, 1),
            current_term_end=date(2026, 10, 1),
            next_billing_date=date(2026, 10, 1),
            pause_date=pause_date,
            resume_date=resume_date,
            metadata={'created_by_id': created_by_id} if created_by_id else {}
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan,
            quantity=1,
            unit_price=self.plan.price
        )
        return sub

    # --- Unit / Service Tests ---

    def test_immediate_cancellation_service(self):
        sub = self._create_subscription(self.customer1, status='LIVE')
        updated = SubscriptionLifecycleService.cancel_subscription(
            subscription=sub,
            cancel_type='IMMEDIATE',
            reason='Customer requested termination',
            user=self.admin_user
        )
        self.assertEqual(updated.status, 'CANCELLED')
        self.assertIsNotNone(updated.cancelled_at)
        self.assertFalse(updated.cancel_at_period_end)

        # Verify audit log
        audit = SubscriptionAuditLog.objects.filter(subscription=updated).latest('timestamp')
        self.assertEqual(audit.new_state, 'CANCELLED')
        self.assertEqual(audit.reason, 'Customer requested termination')

    def test_cancellation_requires_reason(self):
        sub = self._create_subscription(self.customer1, status='LIVE')
        with self.assertRaises(ValidationError) as ctx:
            SubscriptionLifecycleService.cancel_subscription(
                subscription=sub,
                cancel_type='IMMEDIATE',
                reason='',
                user=self.admin_user
            )
        self.assertIn('reason', str(ctx.exception))

    def test_cancelled_terminal_behavior(self):
        sub = self._create_subscription(self.customer1, status='CANCELLED')
        with self.assertRaises(ValidationError):
            SubscriptionLifecycleService.cancel_subscription(
                subscription=sub,
                cancel_type='IMMEDIATE',
                reason='Cancel again',
                user=self.admin_user
            )
        with self.assertRaises(ValidationError):
            SubscriptionLifecycleService.pause_subscription(
                subscription=sub,
                reason='Pause cancelled sub',
                user=self.admin_user
            )
        with self.assertRaises(ValidationError):
            SubscriptionLifecycleService.resume_subscription(
                subscription=sub,
                user=self.admin_user
            )

    def test_period_end_cancellation_service(self):
        sub = self._create_subscription(self.customer1, status='LIVE')
        updated = SubscriptionLifecycleService.cancel_subscription(
            subscription=sub,
            cancel_type='PERIOD_END',
            reason='Non-renewing at end of contract',
            user=self.admin_user
        )
        self.assertEqual(updated.status, 'NON_RENEWING')
        self.assertTrue(updated.cancel_at_period_end)

        # Verify renewal at term end transitions to CANCELLED without invoice
        sub.next_billing_date = date.today() - timedelta(days=1)
        sub.save()

        res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res['status'], 'CANCELLED')
        self.assertIsNone(res['invoice'])
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'CANCELLED')

    def test_re_enable_period_end_cancellation(self):
        sub = self._create_subscription(self.customer1, status='NON_RENEWING')
        sub.cancel_at_period_end = True
        sub.save()

        updated = SubscriptionLifecycleService.re_enable_auto_renewal(
            subscription=sub,
            user=self.admin_user,
            reason='Customer decided to stay'
        )
        self.assertEqual(updated.status, 'LIVE')
        self.assertFalse(updated.cancel_at_period_end)

    def test_pause_service(self):
        sub = self._create_subscription(self.customer1, status='LIVE')
        updated = SubscriptionLifecycleService.pause_subscription(
            subscription=sub,
            reason='Winter freeze',
            user=self.admin_user
        )
        self.assertEqual(updated.status, 'PAUSED')
        self.assertEqual(updated.pause_date, date.today())

    def test_pause_requires_reason(self):
        sub = self._create_subscription(self.customer1, status='LIVE')
        with self.assertRaises(ValidationError) as ctx:
            SubscriptionLifecycleService.pause_subscription(
                subscription=sub,
                reason='',
                user=self.admin_user
            )
        self.assertIn('reason', str(ctx.exception))

    def test_past_due_and_unpaid_cannot_pause(self):
        sub_past_due = self._create_subscription(self.customer1, status='PAST_DUE')
        with self.assertRaises(ValidationError):
            SubscriptionLifecycleService.pause_subscription(
                subscription=sub_past_due,
                reason='Try pause past due',
                user=self.admin_user
            )

        sub_unpaid = self._create_subscription(self.customer1, status='UNPAID')
        with self.assertRaises(ValidationError):
            SubscriptionLifecycleService.pause_subscription(
                subscription=sub_unpaid,
                reason='Try pause unpaid',
                user=self.admin_user
            )

    def test_paused_subscription_renewal_guard(self):
        sub = self._create_subscription(self.customer1, status='PAUSED', pause_date=date.today())
        sub.next_billing_date = date.today() - timedelta(days=1)
        sub.save()

        res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res['status'], 'SKIPPED')
        self.assertIsNone(res['invoice'])

        # Run batch renewals
        batch_res = SubscriptionRenewalService.process_due_renewals(organization=self.org1, user=self.admin_user)
        self.assertEqual(batch_res['renewed'], 0)
        self.assertEqual(batch_res['cancelled'], 0)

    def test_resume_service_term_extension(self):
        # Subscription term: Sept 1 to Oct 1 (30 days). Next billing date: Oct 1.
        # Paused on Sept 5, resumed on Sept 19 (14 days paused).
        sub = self._create_subscription(self.customer1, status='PAUSED')
        sub.current_term_start = date(2026, 9, 1)
        sub.current_term_end = date(2026, 10, 1)
        sub.next_billing_date = date(2026, 10, 1)
        sub.pause_date = date(2026, 9, 5)
        sub.save()

        resume_d = date(2026, 9, 19)
        updated = SubscriptionLifecycleService.resume_subscription(
            subscription=sub,
            user=self.admin_user,
            resume_date=resume_d
        )

        self.assertEqual(updated.status, 'LIVE')
        self.assertEqual(updated.resume_date, resume_d)
        # Term start is preserved (not reset)
        self.assertEqual(updated.current_term_start, date(2026, 9, 1))
        # 14 days added to current_term_end: Oct 1 + 14 days = Oct 15
        self.assertEqual(updated.current_term_end, date(2026, 10, 15))
        # 14 days added to next_billing_date: Oct 1 + 14 days = Oct 15
        self.assertEqual(updated.next_billing_date, date(2026, 10, 15))

    def test_resume_only_from_paused(self):
        sub_live = self._create_subscription(self.customer1, status='LIVE')
        with self.assertRaises(ValidationError):
            SubscriptionLifecycleService.resume_subscription(subscription=sub_live, user=self.admin_user)

    # --- API Endpoint & RBAC Tests ---

    def test_api_cancel_immediate(self):
        sub = self._create_subscription(self.customer1, status='LIVE', created_by_id=self.sales1.id)
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-subscription-cancel', kwargs={'pk': sub.pk})
        resp = self.client.post(url, {'cancel_type': 'IMMEDIATE', 'reason': 'API immediate cancel'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'CANCELLED')

    def test_api_cancel_period_end(self):
        sub = self._create_subscription(self.customer1, status='LIVE', created_by_id=self.sales1.id)
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-subscription-cancel', kwargs={'pk': sub.pk})
        resp = self.client.post(url, {'cancel_type': 'PERIOD_END', 'reason': 'API period end cancel'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'NON_RENEWING')
        self.assertTrue(resp.data['cancel_at_period_end'])

    def test_api_pause(self):
        sub = self._create_subscription(self.customer1, status='LIVE', created_by_id=self.sales1.id)
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-subscription-pause', kwargs={'pk': sub.pk})
        resp = self.client.post(url, {'reason': 'API pause'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'PAUSED')

    def test_api_resume(self):
        sub = self._create_subscription(self.customer1, status='PAUSED', pause_date=date.today() - timedelta(days=5))
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-subscription-resume', kwargs={'pk': sub.pk})
        resp = self.client.post(url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'LIVE')

    def test_rbac_own_salesperson_allowed_for_owned_subscription(self):
        sub = self._create_subscription(self.customer1, status='LIVE', created_by_id=self.sales1.id)
        self.client.force_authenticate(user=self.sales1)
        url = reverse('billing-subscription-pause', kwargs={'pk': sub.pk})
        resp = self.client.post(url, {'reason': 'Salesperson pausing own subscription'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'PAUSED')

    def test_rbac_own_salesperson_denied_for_unowned_subscription(self):
        sub = self._create_subscription(self.customer1, status='LIVE', created_by_id=self.sales2.id)
        self.client.force_authenticate(user=self.sales1)
        url = reverse('billing-subscription-pause', kwargs={'pk': sub.pk})
        resp = self.client.post(url, {'reason': 'Salesperson trying to pause unowned'}, format='json')
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_rbac_none_denied(self):
        sub = self._create_subscription(self.customer1, status='LIVE', created_by_id=self.sales1.id)
        self.client.force_authenticate(user=self.user_no_perm)
        url = reverse('billing-subscription-cancel', kwargs={'pk': sub.pk})
        resp = self.client.post(url, {'cancel_type': 'IMMEDIATE', 'reason': 'No perm user'}, format='json')
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_cross_tenant_isolation(self):
        sub_org2 = self._create_subscription(self.customer2, status='LIVE', created_by_id=self.org2_user.id)
        self.client.force_authenticate(user=self.admin_user) # Org 1 Admin
        url = reverse('billing-subscription-cancel', kwargs={'pk': sub_org2.pk})
        resp = self.client.post(url, {'cancel_type': 'IMMEDIATE', 'reason': 'Cross tenant cancel'}, format='json')
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
