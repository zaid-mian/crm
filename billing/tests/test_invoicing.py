from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from accounts.models import Organization
from billing.models import BillingCustomer, Subscription, SubscriptionItem, AddOn, Invoice, InvoiceLine
from billing.services import InvoicingEngineService, SubscriptionItemService
from catalog.models.plan import PricingPlan
from catalog.models.product import Product
from roles.models import Role, RolePermission, CRMResource

from billing.tests.helpers import setup_billing_test_permissions

User = get_user_model()


class InvoicingEngineTestCase(APITestCase):
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

        setup_billing_test_permissions(admin_role=self.admin_role, sales_role=self.sales_role)

        # 3. Organizations
        self.org1 = Organization.objects.create(name="Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Org 2", is_active=True)

        # 4. Users
        self.admin_user = User.objects.create_user(username='inv_admin', email='admin@org1.com', password='password123')
        self.admin_user.profile.organization = self.org1
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()

        self.org2_user = User.objects.create_user(username='inv_org2_user', email='user@org2.com', password='password123')
        self.org2_user.profile.organization = self.org2
        self.org2_user.profile.role = self.admin_role
        self.org2_user.profile.save()

        # 5. Catalog Product & Plan & AddOn
        self.product = Product.objects.create(name='Cloud CRM', slug='cloud-crm', is_active=True)
        self.plan = PricingPlan.objects.create(
            product=self.product,
            name='Pro Plan',
            price=Decimal('100.00'),
            currency='USD',
            billing_cycle='monthly',
            is_active=True
        )
        self.addon = AddOn.objects.create(
            product=self.product,
            name='Extra Storage',
            code='STORAGE-10GB',
            price=Decimal('25.00'),
            currency='USD',
            billing_cycle='monthly',
            is_active=True
        )

        # 6. Customer & Subscription
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-00001',
            name='Acme Corp',
            email='billing@acme.com',
            currency='USD',
            metadata={'created_by_id': self.admin_user.id}
        )

        self.customer2 = BillingCustomer.objects.create(
            organization=self.org2,
            customer_number='CUST-00002',
            name='Beta Corp',
            email='billing@beta.com',
            currency='USD',
            metadata={'created_by_id': self.org2_user.id}
        )

        self.sub1 = Subscription.objects.create(
            subscription_number='SUB-00001',
            customer=self.customer1,
            status='LIVE',
            currency='USD',
            current_term_start=date(2026, 9, 1),
            current_term_end=date(2026, 9, 30),
            payment_terms_days=30,
            metadata={'created_by_id': self.admin_user.id}
        )

        # Attach line items with snapshot prices
        SubscriptionItemService.add_item_to_subscription(
            self.sub1, self.admin_user,
            {'item_type': 'PLAN', 'plan': self.plan, 'quantity': 1, 'discount_amount': Decimal('10.00')}
        )
        SubscriptionItemService.add_item_to_subscription(
            self.sub1, self.admin_user,
            {'item_type': 'ADDON', 'addon': self.addon, 'quantity': 2, 'discount_amount': Decimal('0.00')}
        )

    def test_invoice_generation_and_calculation(self):
        """Test generating invoice from subscription, line item calculation math, and header totals."""
        invoice = InvoicingEngineService.generate_invoice(
            subscription=self.sub1,
            billing_period_start=date(2026, 9, 1),
            billing_period_end=date(2026, 9, 30),
            issue_date=date(2026, 9, 1),
            user=self.admin_user
        )

        self.assertIsNotNone(invoice)
        self.assertTrue(invoice.invoice_number.startswith('INV-2026-'))
        self.assertEqual(invoice.status, 'POSTED')
        self.assertEqual(invoice.customer, self.customer1)
        self.assertEqual(invoice.subscription, self.sub1)
        self.assertEqual(invoice.due_date, date(2026, 10, 1))  # issue_date + net 30

        # Lines check
        lines = list(invoice.lines.all())
        self.assertEqual(len(lines), 2)

        # Plan line: 1 x $100 - $10 discount = $90 total
        plan_line = [l for l in lines if 'PLAN' in l.description][0]
        self.assertEqual(plan_line.unit_price, Decimal('100.00'))
        self.assertEqual(plan_line.subtotal, Decimal('100.00'))
        self.assertEqual(plan_line.discount_amount, Decimal('10.00'))
        self.assertEqual(plan_line.total_amount, Decimal('90.00'))

        # Addon line: 2 x $25 = $50 total
        addon_line = [l for l in lines if 'ADDON' in l.description][0]
        self.assertEqual(addon_line.unit_price, Decimal('25.00'))
        self.assertEqual(addon_line.subtotal, Decimal('50.00'))
        self.assertEqual(addon_line.total_amount, Decimal('50.00'))

        # Header totals: Subtotal $150, Discount $10, Total $140, Balance $140
        self.assertEqual(invoice.subtotal, Decimal('150.00'))
        self.assertEqual(invoice.discount_total, Decimal('10.00'))
        self.assertEqual(invoice.total_amount, Decimal('140.00'))
        self.assertEqual(invoice.paid_amount, Decimal('0.00'))
        self.assertEqual(invoice.balance, Decimal('140.00'))

    def test_idempotency_duplicate_prevention(self):
        """Verify that generating invoice for same subscription & period reuses existing invoice without duplicate."""
        inv1 = InvoicingEngineService.generate_invoice(
            subscription=self.sub1,
            billing_period_start=date(2026, 9, 1),
            user=self.admin_user
        )

        self.assertEqual(inv1.idempotency_key, f"inv_sub_{self.sub1.id}_period_2026-09-01")

        # Second call for same subscription + period
        inv2 = InvoicingEngineService.generate_invoice(
            subscription=self.sub1,
            billing_period_start=date(2026, 9, 1),
            user=self.admin_user
        )

        self.assertEqual(inv1.id, inv2.id)
        self.assertEqual(Invoice.objects.filter(subscription=self.sub1).count(), 1)

    def test_historical_pricing_snapshot_preservation(self):
        """Verify modifying catalog plan price does NOT alter generated invoice lines."""
        # Catalog price updated from $100 -> $200
        self.plan.price = Decimal('200.00')
        self.plan.save()

        invoice = InvoicingEngineService.generate_invoice(
            subscription=self.sub1,
            billing_period_start=date(2026, 9, 1),
            user=self.admin_user
        )

        plan_line = [l for l in invoice.lines.all() if 'PLAN' in l.description][0]
        # Should still be $100.00 from historical snapshot
        self.assertEqual(plan_line.unit_price, Decimal('100.00'))

    def test_posted_invoice_immutability(self):
        """Verify editing financial fields on POSTED invoice raises ValidationError."""
        invoice = InvoicingEngineService.generate_invoice(
            subscription=self.sub1,
            billing_period_start=date(2026, 9, 1),
            user=self.admin_user
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-invoice-detail', kwargs={'pk': invoice.id})

        response = self.client.patch(url, {'total_amount': '1.00'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('immutable', str(response.data))

    def test_api_generate_invoice_endpoint(self):
        """POST /api/v1/billing/invoices/ generates invoice via API."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-invoice-list')

        response = self.client.post(url, {
            'subscription': self.sub1.id,
            'billing_period_start': '2026-09-01'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'POSTED')
        self.assertEqual(response.data['total_amount'], '140.00')

    def test_pdf_endpoint_success(self):
        """GET /api/v1/billing/invoices/<id>/pdf/ streams PDF response."""
        invoice = InvoicingEngineService.generate_invoice(
            subscription=self.sub1,
            billing_period_start=date(2026, 9, 1),
            user=self.admin_user
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-invoice-pdf', kwargs={'pk': invoice.id})

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(f'filename="invoice-{invoice.invoice_number}.pdf"', response['Content-Disposition'])

    def test_tenant_isolation_invoice_access(self):
        """User in Org 1 cannot generate or view invoice for subscription in Org 2."""
        sub2 = Subscription.objects.create(
            subscription_number='SUB-00002',
            customer=self.customer2,
            status='LIVE',
            currency='USD',
            current_term_start=date(2026, 9, 1),
            current_term_end=date(2026, 9, 30),
            metadata={'created_by_id': self.org2_user.id}
        )
        SubscriptionItemService.add_item_to_subscription(
            sub2, self.org2_user,
            {'item_type': 'PLAN', 'plan': self.plan, 'quantity': 1}
        )

        self.client.force_authenticate(user=self.admin_user)

        # Attempt API generation for Org 2 subscription
        url = reverse('billing-invoice-list')
        response = self.client.post(url, {
            'subscription': sub2.id,
            'billing_period_start': '2026-09-01'
        }, format='json')
        self.assertIn(response.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))
