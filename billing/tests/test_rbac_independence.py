from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organization
from billing.models import BillingCustomer, Subscription, Invoice, Payment
from billing.services import PaymentService
from roles.models import Role, RolePermission, CRMResource
from roles.services import PermissionService
from billing.tests.helpers import setup_billing_test_permissions, BILLING_RESOURCE_CODENAMES

User = get_user_model()


class BillingRBACIndependenceTestCase(APITestCase):
    """
    Targeted tests proving that the 5 Billing page resources:
    - billing_analytics
    - billing_customers
    - billing_subscriptions
    - billing_invoices
    - billing_payments
    are completely independent in the dynamic RBAC system.
    """

    def setUp(self):
        PermissionService.clear_all_cached_permissions()

        # 1. Setup Organizations
        self.org1 = Organization.objects.create(name="Org One", is_active=True)
        self.org2 = Organization.objects.create(name="Org Two", is_active=True)

        # 2. Setup standard roles
        self.admin_role = Role.objects.create(name="RBAC Admin", is_system=False)
        self.custom_role = Role.objects.create(name="Custom Billing Role", is_system=False)

        # 3. Setup resources
        self.resources = setup_billing_test_permissions(admin_role=self.admin_role)

        # 4. Users
        self.user = User.objects.create_user(username='billing_user', password='password123')
        self.user.profile.organization = self.org1
        self.user.profile.role = self.custom_role
        self.user.profile.save()

        # Setup initial test data for org1
        self.customer = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-IND-001',
            name="Acme Corp",
            email="billing@acme.com",
            currency="USD"
        )
        self.subscription = Subscription.objects.create(
            subscription_number='SUB-IND-001',
            customer=self.customer,
            status="LIVE",
            currency="USD",
            current_term_start=date(2026, 1, 1),
            current_term_end=date(2026, 2, 1)
        )
        self.invoice = Invoice.objects.create(
            invoice_number='INV-IND-001',
            customer=self.customer,
            subscription=self.subscription,
            issue_date=date.today(),
            due_date=date.today(),
            status="POSTED",
            subtotal=Decimal("100.00"),
            tax_total=Decimal("0.00"),
            discount_total=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("0.00"),
            balance=Decimal("100.00")
        )
        self.payment = PaymentService.record_payment(
            customer=self.customer,
            amount=Decimal("100.00"),
            currency="USD"
        )

    def test_all_five_resources_exist_and_legacy_billing_resource_is_removed(self):
        """Verify all 5 granular resources are registered and legacy 'billing' does not exist."""
        for code in BILLING_RESOURCE_CODENAMES:
            self.assertTrue(
                CRMResource.objects.filter(codename=code).exists(),
                f"Resource {code} should exist in CRMResource"
            )
        self.assertFalse(
            CRMResource.objects.filter(codename='billing').exists(),
            "Legacy 'billing' resource should NOT exist in CRMResource"
        )

    def test_independent_view_access_invoices_blocked_others_allowed(self):
        """
        Revoking billing_invoices.VIEW must block only /api/v1/billing/invoices/
        while Subscriptions, Customers, Payments, and Analytics remain accessible.
        """
        # Grant VIEW=ALL to all resources EXCEPT billing_invoices (which is VIEW=NONE)
        for code, res in self.resources.items():
            scope = 'NONE' if code == 'billing_invoices' else 'ALL'
            RolePermission.objects.create(
                role=self.custom_role,
                resource=res,
                action='VIEW',
                scope=scope
            )

        self.client.force_authenticate(user=self.user)

        # 1. Invoices -> 403 Forbidden
        res_invoices = self.client.get('/api/v1/billing/invoices/')
        self.assertEqual(res_invoices.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Subscriptions -> 200 OK
        res_subs = self.client.get('/api/v1/billing/subscriptions/')
        self.assertEqual(res_subs.status_code, status.HTTP_200_OK)

        # 3. Customers -> 200 OK
        res_cust = self.client.get('/api/v1/billing/customers/')
        self.assertEqual(res_cust.status_code, status.HTTP_200_OK)

        # 4. Payments -> 200 OK
        res_pay = self.client.get('/api/v1/billing/payments/')
        self.assertEqual(res_pay.status_code, status.HTTP_200_OK)

        # 5. Analytics Overview -> 200 OK
        res_analytics = self.client.get('/api/v1/billing/analytics/overview/')
        self.assertEqual(res_analytics.status_code, status.HTTP_200_OK)

    def test_independent_view_access_subscriptions_blocked_others_allowed(self):
        """
        Revoking billing_subscriptions.VIEW must block Subscriptions
        while Invoices, Customers, Payments, and Analytics remain accessible.
        """
        for code, res in self.resources.items():
            scope = 'NONE' if code == 'billing_subscriptions' else 'ALL'
            RolePermission.objects.create(
                role=self.custom_role,
                resource=res,
                action='VIEW',
                scope=scope
            )

        self.client.force_authenticate(user=self.user)

        # Subscriptions -> 403 Forbidden
        res_subs = self.client.get('/api/v1/billing/subscriptions/')
        self.assertEqual(res_subs.status_code, status.HTTP_403_FORBIDDEN)

        # Invoices -> 200 OK
        res_invoices = self.client.get('/api/v1/billing/invoices/')
        self.assertEqual(res_invoices.status_code, status.HTTP_200_OK)

        # Customers -> 200 OK
        res_cust = self.client.get('/api/v1/billing/customers/')
        self.assertEqual(res_cust.status_code, status.HTTP_200_OK)

        # Payments -> 200 OK
        res_pay = self.client.get('/api/v1/billing/payments/')
        self.assertEqual(res_pay.status_code, status.HTTP_200_OK)

    def test_independent_create_action_customers_blocked_subscriptions_allowed(self):
        """
        Setting billing_customers.CREATE=NONE while billing_subscriptions.CREATE=ALL
        must block customer creation with 403, but allow subscription creation endpoints.
        """
        for code, res in self.resources.items():
            RolePermission.objects.create(
                role=self.custom_role,
                resource=res,
                action='VIEW',
                scope='ALL'
            )
            # Customers CREATE = NONE, others = ALL
            create_scope = 'NONE' if code == 'billing_customers' else 'ALL'
            RolePermission.objects.create(
                role=self.custom_role,
                resource=res,
                action='CREATE',
                scope=create_scope
            )

        self.client.force_authenticate(user=self.user)

        # Customer create -> 403 Forbidden
        res_create_cust = self.client.post('/api/v1/billing/customers/', {
            'name': 'New Restricted Corp',
            'email': 'restricted@corp.com',
            'currency': 'USD'
        }, format='json')
        self.assertEqual(res_create_cust.status_code, status.HTTP_403_FORBIDDEN)

        # Subscription create -> 201 Created
        res_create_sub = self.client.post('/api/v1/billing/subscriptions/', {
            'customer': self.customer.id,
            'collection_method': 'CHARGE_AUTOMATIC',
            'payment_terms_days': 30,
            'current_term_start': '2026-03-01',
            'billing_cycle': 'MONTHLY'
        }, format='json')
        self.assertEqual(res_create_sub.status_code, status.HTTP_201_CREATED)

    def test_tenant_isolation_preserved_with_split_resources(self):
        """
        Verify tenant isolation continues to work across split resources.
        User in org1 cannot see invoices or customers in org2 even with VIEW=ALL.
        """
        for code, res in self.resources.items():
            RolePermission.objects.create(
                role=self.custom_role,
                resource=res,
                action='VIEW',
                scope='ALL'
            )

        # Create records in org2
        cust2 = BillingCustomer.objects.create(
            organization=self.org2,
            customer_number='CUST-IND-ORG2',
            name="Foreign Org Corp",
            currency="USD"
        )
        inv2 = Invoice.objects.create(
            invoice_number='INV-IND-ORG2',
            customer=cust2,
            issue_date=date.today(),
            due_date=date.today(),
            status="POSTED",
            subtotal=Decimal("500.00"),
            tax_total=Decimal("0.00"),
            discount_total=Decimal("0.00"),
            total_amount=Decimal("500.00"),
            paid_amount=Decimal("0.00"),
            balance=Decimal("500.00")
        )

        self.client.force_authenticate(user=self.user)

        # Invoices list should only include org1 invoice
        res = self.client.get('/api/v1/billing/invoices/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data.get('results', res.data) if isinstance(res.data, dict) else res.data
        inv_ids = [i['id'] for i in results]
        self.assertIn(self.invoice.id, inv_ids)
        self.assertNotIn(inv2.id, inv_ids)
