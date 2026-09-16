from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import Organization
from roles.models import Role, RolePermission, CRMResource

from billing.models import BillingCustomer, Subscription, SubscriptionItem, Invoice, Payment, PaymentAllocation, SubscriptionAuditLog, AddOn
from catalog.models.plan import PricingPlan
from catalog.models.product import Product

from billing.services import SubscriptionService, SubscriptionRenewalService, SubscriptionStateMachineService, InvoicingEngineService
from billing.gateways.stripe import StripeGatewayService

User = get_user_model()


from billing.tests.helpers import setup_billing_test_permissions, BILLING_RESOURCE_CODENAMES


class AutomatedSubscriptionRenewalTestCase(TestCase):
    def setUp(self):
        # 1. Setup RBAC permissions
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
        self.sp_manager_role, _ = Role.objects.get_or_create(
            name='Salesperson Manager',
            defaults={'is_system': False, 'description': 'Salesperson Manager'}
        )
        self.unauth_role, _ = Role.objects.get_or_create(
            name='Unauthorized Role',
            defaults={'is_system': False, 'description': 'No Billing Access'}
        )

        resources = setup_billing_test_permissions(admin_role=self.admin_role, manager_role=self.manager_role, sales_role=self.sales_role)
        for res in resources.values():
            for act in ('VIEW', 'CREATE', 'EDIT', 'DELETE'):
                RolePermission.objects.get_or_create(role=self.sp_manager_role, resource=res, action=act, defaults={'scope': 'ALL'})
                RolePermission.objects.get_or_create(role=self.unauth_role, resource=res, action=act, defaults={'scope': 'NONE'})


        # 2. Organizations
        self.org1 = Organization.objects.create(name="Tenant Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Tenant Org 2", is_active=True)

        # 3. Users
        self.admin_user = User.objects.create_user(
            username="admin_user",
            email="admin@tenant1.com",
            password="Password123!",
            is_staff=True,
            is_superuser=True
        )
        if hasattr(self.admin_user, 'profile'):
            self.admin_user.profile.organization = self.org1
            self.admin_user.profile.role = self.admin_role
            self.admin_user.profile.save()

        self.manager_user = User.objects.create_user(
            username="manager_user",
            email="manager@tenant1.com",
            password="Password123!"
        )
        if hasattr(self.manager_user, 'profile'):
            self.manager_user.profile.organization = self.org1
            self.manager_user.profile.role = self.manager_role
            self.manager_user.profile.save()

        self.sales_user = User.objects.create_user(
            username="sales_user",
            email="sales@tenant1.com",
            password="Password123!"
        )
        if hasattr(self.sales_user, 'profile'):
            self.sales_user.profile.organization = self.org1
            self.sales_user.profile.role = self.sales_role
            self.sales_user.profile.save()

        self.sp_manager_user = User.objects.create_user(
            username="sp_manager_user",
            email="spmanager@tenant1.com",
            password="Password123!"
        )
        if hasattr(self.sp_manager_user, 'profile'):
            self.sp_manager_user.profile.organization = self.org1
            self.sp_manager_user.profile.role = self.sp_manager_role
            self.sp_manager_user.profile.save()

        self.unauth_user = User.objects.create_user(
            username="unauth_user",
            email="unauth@tenant1.com",
            password="Password123!"
        )
        if hasattr(self.unauth_user, 'profile'):
            self.unauth_user.profile.organization = self.org1
            self.unauth_user.profile.role = self.unauth_role
            self.unauth_user.profile.save()


        # 4. Catalog Entities
        self.product = Product.objects.create(name="Cloud CRM Pro", slug="cloud-crm-pro")
        self.plan_monthly = PricingPlan.objects.create(
            product=self.product,
            name="Pro Monthly Plan",
            price=Decimal("100.00"),
            currency="USD",
            billing_cycle="monthly"
        )
        self.plan_yearly = PricingPlan.objects.create(
            product=self.product,
            name="Pro Yearly Plan",
            price=Decimal("1200.00"),
            currency="USD",
            billing_cycle="yearly"
        )



        # 5. Customers
        self.customer1 = BillingCustomer.objects.create(
            customer_number="CUST-00001",
            name="Acme Corp",
            email="billing@acme.com",
            organization=self.org1,
            default_payment_method_id="pm_test_card_123",
            metadata={"created_by_id": self.admin_user.id, "stripe_customer_id": "cus_test_111"}
        )

        self.customer_no_pm = BillingCustomer.objects.create(
            customer_number="CUST-00002",
            name="No PM Corp",
            email="billing@nopm.com",
            organization=self.org1,
            default_payment_method_id="",
            metadata={"created_by_id": self.admin_user.id}
        )

        self.customer_org2 = BillingCustomer.objects.create(
            customer_number="CUST-00003",
            name="Org2 Enterprise",
            email="billing@org2.com",
            organization=self.org2,
            default_payment_method_id="pm_test_org2",
            metadata={"created_by_id": 999}
        )

        self.client = APIClient()

    # -------------------------------------------------------------------------
    # Group 1: Renewal Eligibility Tests
    # -------------------------------------------------------------------------

    def test_due_live_subscription_renews(self):
        today = date.today()
        sub = Subscription.objects.create(
            subscription_number="SUB-00101",
            customer=self.customer1,
            status='LIVE',
            current_term_start=today - timedelta(days=30),
            current_term_end=today - timedelta(days=1),
            next_billing_date=today - timedelta(days=1),
            collection_method='CHARGE_AUTOMATIC'
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_monthly,
            quantity=1,
            unit_price=Decimal("100.00")
        )

        res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res['status'], 'RENEWED')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'LIVE')
        self.assertGreater(sub.next_billing_date, today)

        inv = res['invoice']
        self.assertIsNotNone(inv)
        self.assertEqual(inv.status, 'PAID')  # Auto-collected with mock default PM
        self.assertEqual(inv.total_amount, Decimal("100.00"))

        audit = SubscriptionAuditLog.objects.filter(subscription=sub, action='RENEWAL_COMPLETED').first()
        self.assertIsNotNone(audit)

    def test_future_live_subscription_skipped(self):
        today = date.today()
        sub = Subscription.objects.create(
            subscription_number="SUB-00102",
            customer=self.customer1,
            status='LIVE',
            current_term_start=today,
            current_term_end=today + timedelta(days=30),
            next_billing_date=today + timedelta(days=30),
        )
        res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res['status'], 'SKIPPED')

    def test_non_live_statuses_skipped(self):
        today = date.today()
        past_date = today - timedelta(days=2)
        non_live_statuses = ['DRAFT', 'FUTURE', 'TRIAL', 'PAUSED', 'PAST_DUE', 'UNPAID', 'CANCELLED']

        for st in non_live_statuses:
            sub = Subscription.objects.create(
                subscription_number=f"SUB-STATUS-{st}",
                customer=self.customer1,
                status=st,
                current_term_start=past_date - timedelta(days=30),
                current_term_end=past_date,
                next_billing_date=past_date,
            )
            res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
            self.assertEqual(res['status'], 'SKIPPED', f"Status '{st}' should be skipped for renewal")

    def test_non_renewing_subscription_cancels_at_term_end(self):
        today = date.today()
        past_date = today - timedelta(days=1)
        sub = Subscription.objects.create(
            subscription_number="SUB-00103",
            customer=self.customer1,
            status='NON_RENEWING',
            current_term_start=past_date - timedelta(days=30),
            current_term_end=past_date,
            next_billing_date=past_date,
            cancel_at_period_end=True
        )

        res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res['status'], 'CANCELLED')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'CANCELLED')
        self.assertIsNotNone(sub.cancelled_at)
        self.assertIsNone(res['invoice'])

    # -------------------------------------------------------------------------
    # Group 2: Term Date Calculation & Month-End Clamping Tests
    # -------------------------------------------------------------------------

    def test_monthly_term_advancement_jan_to_feb(self):
        start_date = date(2026, 1, 31)
        calc_start, calc_end, calc_next = SubscriptionService.calculate_term_dates(start_date, 'MONTHLY')
        self.assertEqual(calc_start, date(2026, 1, 31))
        self.assertEqual(calc_end, date(2026, 2, 27))
        self.assertEqual(calc_next, date(2026, 2, 28))

    def test_yearly_term_advancement_leap_year(self):
        start_date = date(2024, 2, 29)  # 2024 is a leap year
        calc_start, calc_end, calc_next = SubscriptionService.calculate_term_dates(start_date, 'YEARLY')
        self.assertEqual(calc_start, date(2024, 2, 29))
        self.assertEqual(calc_end, date(2025, 2, 27))
        self.assertEqual(calc_next, date(2025, 2, 28))  # 2025 is non-leap year

    # -------------------------------------------------------------------------
    # Group 3: Renewal Idempotency Tests
    # -------------------------------------------------------------------------

    def test_repeated_renewal_runs_idempotent(self):
        today = date.today()
        past_date = today - timedelta(days=1)
        sub = Subscription.objects.create(
            subscription_number="SUB-00104",
            customer=self.customer1,
            status='LIVE',
            current_term_start=past_date - timedelta(days=30),
            current_term_end=past_date,
            next_billing_date=past_date,
            collection_method='SEND_INVOICE'
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_monthly,
            quantity=1,
            unit_price=Decimal("100.00")
        )

        # Run 1
        res1 = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res1['status'], 'RENEWED')
        inv1 = res1['invoice']
        self.assertIsNotNone(inv1)

        # Run 2 (repeated execution)
        res2 = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res2['status'], 'SKIPPED')

        # Confirm total invoices for this subscription is exactly 1
        invoice_count = Invoice.objects.filter(subscription=sub).count()
        self.assertEqual(invoice_count, 1)

    # -------------------------------------------------------------------------
    # Group 4: Auto-Collection & Gateway Fallback Tests
    # -------------------------------------------------------------------------

    def test_auto_collection_no_payment_method(self):
        today = date.today()
        past_date = today - timedelta(days=1)
        sub = Subscription.objects.create(
            subscription_number="SUB-00105",
            customer=self.customer_no_pm,
            status='LIVE',
            current_term_start=past_date - timedelta(days=30),
            current_term_end=past_date,
            next_billing_date=past_date,
            collection_method='CHARGE_AUTOMATIC'
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_monthly,
            quantity=1,
 unit_price=Decimal("100.00")
        )

        res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res['status'], 'RENEWED')

        inv = res['invoice']
        self.assertEqual(inv.status, 'POSTED')
        self.assertEqual(inv.balance, Decimal("100.00"))
        self.assertEqual(Payment.objects.filter(customer=self.customer_no_pm).count(), 0)

    @patch('billing.gateways.stripe.StripeGatewayService.create_payment_intent')
    def test_stripe_gateway_exception_does_not_rollback_stage1(self, mock_create_intent):
        mock_create_intent.side_effect = Exception("Stripe API Connection Error")

        today = date.today()
        past_date = today - timedelta(days=1)
        sub = Subscription.objects.create(
            subscription_number="SUB-00106",
            customer=self.customer1,
            status='LIVE',
            current_term_start=past_date - timedelta(days=30),
            current_term_end=past_date,
            next_billing_date=past_date,
            collection_method='CHARGE_AUTOMATIC'
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_monthly,
            quantity=1,
            unit_price=Decimal("100.00")
        )

        res = SubscriptionRenewalService.renew_subscription(sub, user=self.admin_user)
        self.assertEqual(res['status'], 'RENEWED')

        sub.refresh_from_db()
        self.assertGreater(sub.next_billing_date, today)

        inv = res['invoice']
        self.assertIsNotNone(inv)
        self.assertEqual(inv.status, 'POSTED')

    # -------------------------------------------------------------------------
    # Group 6: RBAC Authorization & Multi-Tenant Tests
    # -------------------------------------------------------------------------

    def test_admin_manager_with_all_scope_allowed(self):
        self.client.force_authenticate(user=self.manager_user)
        response = self.client.post('/api/v1/billing/subscriptions/run-renewals/', {'batch_size': 10}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_salesperson_manager_with_all_scope_allowed(self):
        self.client.force_authenticate(user=self.sp_manager_user)
        response = self.client.post('/api/v1/billing/subscriptions/run-renewals/', {'batch_size': 10}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_run_renewals_salesperson_own_scope_denied(self):
        self.client.force_authenticate(user=self.sales_user)
        response = self.client.post('/api/v1/billing/subscriptions/run-renewals/', {'batch_size': 10}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthorized_user_none_scope_denied(self):
        self.client.force_authenticate(user=self.unauth_user)
        response = self.client.post('/api/v1/billing/subscriptions/run-renewals/', {'batch_size': 10}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_isolation(self):
        today = date.today()
        past_date = today - timedelta(days=1)
        sub_org2 = Subscription.objects.create(
            subscription_number="SUB-00108",
            customer=self.customer_org2,
            status='LIVE',
            current_term_start=past_date - timedelta(days=30),
            current_term_end=past_date,
            next_billing_date=past_date,
            collection_method='SEND_INVOICE'
        )
        SubscriptionItem.objects.create(
            subscription=sub_org2,
            item_type='PLAN',
            plan=self.plan_monthly,
            quantity=1,
            unit_price=Decimal("100.00")
        )

        # Authenticate as Org 1 Manager
        self.client.force_authenticate(user=self.manager_user)
        response = self.client.post('/api/v1/billing/subscriptions/run-renewals/', {'batch_size': 10}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Org 2 subscription must NOT have been renewed
        sub_org2.refresh_from_db()
        self.assertEqual(sub_org2.next_billing_date, past_date)
