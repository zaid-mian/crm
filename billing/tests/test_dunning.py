from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import Organization
from roles.models import Role, RolePermission, CRMResource

from billing.models import BillingCustomer, Subscription, SubscriptionItem, Invoice, Payment, PaymentAllocation, SubscriptionAuditLog, DunningLog, WebhookInbox
from catalog.models.plan import PricingPlan
from catalog.models.product import Product

from billing.services import SubscriptionService, SubscriptionRenewalService, SubscriptionStateMachineService, InvoicingEngineService, DunningService, PaymentService, PaymentAllocationService
from billing.gateways.stripe import StripeGatewayService

User = get_user_model()


from billing.tests.helpers import setup_billing_test_permissions


class DunningManagementTestCase(TestCase):
    def setUp(self):
        # 1. Setup RBAC permissions
        self.admin_role, _ = Role.objects.get_or_create(
            name='Administrator',
            defaults={'is_system': True, 'description': 'Admin'}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name='Salesperson',
            defaults={'is_system': True, 'description': 'Salesperson'}
        )
        self.unauth_role, _ = Role.objects.get_or_create(
            name='Unauthorized Role',
            defaults={'is_system': False, 'description': 'No Billing Access'}
        )

        resources = setup_billing_test_permissions(admin_role=self.admin_role, sales_role=self.sales_role)
        for res in resources.values():
            for act in ('VIEW', 'CREATE', 'EDIT', 'DELETE'):
                RolePermission.objects.get_or_create(role=self.unauth_role, resource=res, action=act, defaults={'scope': 'NONE'})

        # 2. Organizations
        self.org1 = Organization.objects.create(name="Dunning Tenant Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Dunning Tenant Org 2", is_active=True)

        # 3. Users
        self.admin_user = User.objects.create_user(
            username="dunning_admin",
            email="admin@dunning.com",
            password="Password123!",
            is_active=True
        )
        if hasattr(self.admin_user, 'profile'):
            self.admin_user.profile.organization = self.org1
            self.admin_user.profile.role = self.admin_role
            self.admin_user.profile.save()
        if hasattr(self.admin_user, 'roles'):
            self.admin_user.roles.add(self.admin_role)

        self.sales_user = User.objects.create_user(
            username="dunning_sales",
            email="sales@dunning.com",
            password="Password123!",
            is_active=True
        )
        if hasattr(self.sales_user, 'profile'):
            self.sales_user.profile.organization = self.org1
            self.sales_user.profile.role = self.sales_role
            self.sales_user.profile.save()
        if hasattr(self.sales_user, 'roles'):
            self.sales_user.roles.add(self.sales_role)

        self.org2_user = User.objects.create_user(
            username="org2_admin",
            email="admin@org2.com",
            password="Password123!",
            is_active=True
        )
        if hasattr(self.org2_user, 'profile'):
            self.org2_user.profile.organization = self.org2
            self.org2_user.profile.role = self.admin_role
            self.org2_user.profile.save()
        if hasattr(self.org2_user, 'roles'):
            self.org2_user.roles.add(self.admin_role)

        # 4. Catalog Product & Plan
        self.product = Product.objects.create(name="Enterprise Cloud", is_active=True)
        self.plan = PricingPlan.objects.create(
            name="Pro Monthly",
            product=self.product,
            price=Decimal('100.00'),
            currency='USD',
            billing_cycle='MONTHLY',
            is_active=True
        )

        # 5. Customer with Default Payment Method
        self.customer = BillingCustomer.objects.create(
            customer_number="CUST-70001",
            organization=self.org1,
            name="Acme Corp",
            email="billing@acme.com",
            default_payment_method_id="pm_card_visa"
        )

        # 6. Customer without Payment Method
        self.customer_no_pm = BillingCustomer.objects.create(
            customer_number="CUST-70002",
            organization=self.org1,
            name="No Card Corp",
            email="nocard@acme.com",
            default_payment_method_id=""
        )

        # 7. Subscription LIVE
        self.sub = Subscription.objects.create(
            subscription_number="SUB-70001",
            customer=self.customer,
            status='LIVE',
            current_term_start=date.today() - timedelta(days=30),
            current_term_end=date.today(),
            next_billing_date=date.today(),
            collection_method='CHARGE_AUTOMATIC',
            currency='USD'
        )
        SubscriptionItem.objects.create(
            subscription=self.sub,
            item_type='PLAN',
            plan=self.plan,
            quantity=1,
            unit_price=Decimal('100.00')
        )

        self.client = APIClient()

    # 1. Failed Renewal -> PAST_DUE & Initial DunningLog (Attempt 0)
    def test_failed_renewal_transitions_to_past_due(self):
        with patch('billing.gateways.stripe.StripeGatewayService.create_payment_intent') as mock_pi:
            mock_pi.return_value = {
                "success": False,
                "status": "failed",
                "error_code": "card_declined",
                "error_message": "Your card was declined."
            }
            res = SubscriptionRenewalService.renew_subscription(self.sub)

            self.sub.refresh_from_db()
            self.assertEqual(self.sub.status, 'PAST_DUE')
            self.assertTrue(DunningLog.objects.filter(subscription=self.sub, attempt_number=0, status='FAILED').exists())

    # 2. Missing Payment Method -> PAST_DUE without fake payment records
    def test_missing_payment_method_renewal_failure(self):
        sub_no_pm = Subscription.objects.create(
            subscription_number="SUB-70002",
            customer=self.customer_no_pm,
            status='LIVE',
            current_term_start=date.today() - timedelta(days=30),
            current_term_end=date.today(),
            next_billing_date=date.today(),
            collection_method='CHARGE_AUTOMATIC',
            currency='USD'
        )
        SubscriptionItem.objects.create(
            subscription=sub_no_pm,
            item_type='PLAN',
            plan=self.plan,
            quantity=1,
            unit_price=Decimal('100.00')
        )

        res = SubscriptionRenewalService.renew_subscription(sub_no_pm)
        sub_no_pm.refresh_from_db()

        self.assertEqual(sub_no_pm.status, 'PAST_DUE')
        log = DunningLog.objects.filter(subscription=sub_no_pm, attempt_number=0).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.error_code, 'MISSING_PAYMENT_METHOD')
        self.assertEqual(Payment.objects.filter(customer=self.customer_no_pm).count(), 0)

    # 3. Day 3 / Day 7 / Day 14 Retry Schedule Progression & Exhaustion -> UNPAID
    def test_dunning_retry_schedule_progression_and_exhaustion(self):
        # Initial failure at day 0
        invoice = InvoicingEngineService.generate_invoice(self.sub, billing_period_start=date.today())
        DunningService.handle_failed_renewal(self.sub, invoice=invoice, error_code='card_declined')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'PAST_DUE')

        # Backdate initial log to 3 days ago for Day 3 retry
        initial_log = DunningLog.objects.get(subscription=self.sub, attempt_number=0)
        DunningLog._base_manager.filter(id=initial_log.id).update(timestamp=timezone.now() - timedelta(days=3, hours=1))

        with patch('billing.gateways.stripe.StripeGatewayService.create_payment_intent') as mock_pi:
            mock_pi.return_value = {"success": False, "status": "failed", "error_code": "card_declined"}
            # Attempt 1 (Day 3 retry)
            res1 = DunningService.process_dunning_retries(organization=self.org1)
            self.assertEqual(res1['failed'], 1)
            self.assertTrue(DunningLog.objects.filter(subscription=self.sub, attempt_number=1, status='FAILED').exists())

            # Backdate to 7 days ago for Day 7 retry
            DunningLog._base_manager.filter(id=initial_log.id).update(timestamp=timezone.now() - timedelta(days=7, hours=1))

            # Attempt 2 (Day 7 retry)
            res2 = DunningService.process_dunning_retries(organization=self.org1)
            self.assertEqual(res2['failed'], 1)
            self.assertTrue(DunningLog.objects.filter(subscription=self.sub, attempt_number=2, status='FAILED').exists())

            # Backdate to 14 days ago for Day 14 retry
            DunningLog._base_manager.filter(id=initial_log.id).update(timestamp=timezone.now() - timedelta(days=14, hours=1))

            # Attempt 3 (Day 14 retry -> Exhaustion)
            res3 = DunningService.process_dunning_retries(organization=self.org1)
            self.assertEqual(res3['failed'], 1)
            self.assertEqual(res3['exhausted'], 1)
            self.assertTrue(DunningLog.objects.filter(subscription=self.sub, attempt_number=3, status='EXHAUSTED').exists())

            self.sub.refresh_from_db()
            self.assertEqual(self.sub.status, 'UNPAID')

    # 4. Successful Retry -> LIVE & Invoice Settle
    def test_successful_retry_restores_live(self):
        invoice = InvoicingEngineService.generate_invoice(self.sub, billing_period_start=date.today())
        DunningService.handle_failed_renewal(self.sub, invoice=invoice, error_code='card_declined')

        initial_log = DunningLog.objects.get(subscription=self.sub, attempt_number=0)
        DunningLog._base_manager.filter(id=initial_log.id).update(timestamp=timezone.now() - timedelta(days=3, hours=1))

        with patch('billing.gateways.stripe.StripeGatewayService.create_payment_intent') as mock_pi:
            mock_pi.return_value = {
                "success": True,
                "status": "succeeded",
                "payment_intent_id": "pi_dunning_success_123"
            }
            res = DunningService.process_dunning_retries(organization=self.org1)
            self.assertEqual(res['succeeded'], 1)

            self.sub.refresh_from_db()
            self.assertEqual(self.sub.status, 'LIVE')

            invoice.refresh_from_db()
            self.assertEqual(invoice.status, 'PAID')
            self.assertEqual(invoice.balance, Decimal('0.00'))

    # 5. Deterministic Stripe Idempotency Key & Row Locking
    def test_stripe_idempotency_key_generation(self):
        invoice = InvoicingEngineService.generate_invoice(self.sub, billing_period_start=date.today())
        DunningService.handle_failed_renewal(self.sub, invoice=invoice)

        initial_log = DunningLog.objects.get(subscription=self.sub, attempt_number=0)
        DunningLog._base_manager.filter(id=initial_log.id).update(timestamp=timezone.now() - timedelta(days=3, hours=1))

        with patch('billing.gateways.stripe.StripeGatewayService.create_payment_intent') as mock_pi:
            mock_pi.return_value = {"success": True, "status": "succeeded", "payment_intent_id": "pi_idemp_1"}
            DunningService.process_dunning_retries(organization=self.org1)

            expected_key = f"dunning_sub_{self.sub.id}_inv_{invoice.id}_attempt_1"
            mock_pi.assert_called_once()
            _, kwargs = mock_pi.call_args
            self.assertEqual(kwargs.get('idempotency_key'), expected_key)

    # 6. Duplicate Scheduler Execution Idempotency
    def test_duplicate_scheduler_execution_is_idempotent(self):
        invoice = InvoicingEngineService.generate_invoice(self.sub, billing_period_start=date.today())
        DunningService.handle_failed_renewal(self.sub, invoice=invoice)

        initial_log = DunningLog.objects.get(subscription=self.sub, attempt_number=0)
        DunningLog._base_manager.filter(id=initial_log.id).update(timestamp=timezone.now() - timedelta(days=3, hours=1))

        with patch('billing.gateways.stripe.StripeGatewayService.create_payment_intent') as mock_pi:
            mock_pi.return_value = {"success": False, "status": "failed", "error_code": "card_declined"}
            res1 = DunningService.process_dunning_retries(organization=self.org1)
            self.assertEqual(res1['processed'], 1)

            # Second call immediately after should skip because attempt 1 is logged
            res2 = DunningService.process_dunning_retries(organization=self.org1)
            self.assertEqual(res2['processed'], 0)

    # 7. Manual Payment Recovery
    def test_manual_payment_recovery(self):
        invoice = InvoicingEngineService.generate_invoice(self.sub, billing_period_start=date.today())
        DunningService.handle_failed_renewal(self.sub, invoice=invoice)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'PAST_DUE')

        # Manually record payment and allocate
        pay = PaymentService.record_payment(
            customer=self.customer,
            amount=Decimal('100.00'),
            currency='USD',
            notes="Manual payment recovery"
        )
        PaymentAllocationService.allocate_payment(
            payment_id=pay.id,
            allocations_data=[{'invoice_id': invoice.id, 'amount': Decimal('100.00')}]
        )

        DunningService.handle_manual_payment_recovery(self.sub, invoice, pay)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'LIVE')

    # 8. Tenant Isolation Enforcement
    def test_tenant_isolation_on_dunning_processing(self):
        sub_org2 = Subscription.objects.create(
            subscription_number="SUB-70099",
            customer=BillingCustomer.objects.create(
                customer_number="CUST-70099",
                organization=self.org2,
                name="Org2 Customer"
            ),
            status='PAST_DUE',
            collection_method='CHARGE_AUTOMATIC'
        )

        res = DunningService.process_dunning_retries(organization=self.org1)
        sub_org2.refresh_from_db()
        self.assertEqual(sub_org2.status, 'PAST_DUE')

    # 9. RBAC Verification on run_dunning Endpoint
    def test_rbac_run_dunning_endpoint(self):
        url = '/api/v1/billing/subscriptions/run-dunning/'

        # Admin with ALL scope -> HTTP 200
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Salesperson with OWN scope -> HTTP 403
        self.client.force_authenticate(user=self.sales_user)
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # 10. Dunning History API
    def test_dunning_history_api(self):
        invoice = InvoicingEngineService.generate_invoice(self.sub, billing_period_start=date.today())
        DunningService.handle_failed_renewal(self.sub, invoice=invoice)

        url = f'/api/v1/billing/subscriptions/{self.sub.id}/dunning-history/'
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]['subscription_number'], self.sub.subscription_number)
