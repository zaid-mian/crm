from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import Organization
from billing.models import BillingCustomer, Subscription, Invoice, Payment, PaymentAllocation
from billing.services import PaymentService, PaymentAllocationService

User = get_user_model()


class BillingPaymentEngineTestCase(TestCase):
    def setUp(self):
        self.org1 = Organization.objects.create(name="Tenant Org 1")
        self.org2 = Organization.objects.create(name="Tenant Org 2")

        self.user_admin = User.objects.create_user(
            username="admin_user",
            email="admin@tenant1.com",
            password="Password123!",
            is_staff=True,
            is_superuser=True
        )

        self.user_sales = User.objects.create_user(
            username="sales_user",
            email="sales@tenant1.com",
            password="Password123!"
        )
        if hasattr(self.user_sales, 'profile'):
            self.user_sales.profile.organization = self.org1
            self.user_sales.profile.save()

        self.user_tenant2 = User.objects.create_user(
            username="tenant2_user",
            email="user@tenant2.com",
            password="Password123!"
        )
        if hasattr(self.user_tenant2, 'profile'):
            self.user_tenant2.profile.organization = self.org2
            self.user_tenant2.profile.save()

        self.customer1 = BillingCustomer.objects.create(
            customer_number="CUST-00001",
            name="Acme Corp",
            email="billing@acme.com",
            organization=self.org1,
            metadata={"created_by_id": self.user_sales.id}
        )

        self.customer2 = BillingCustomer.objects.create(
            customer_number="CUST-00002",
            name="Beta Inc",
            email="billing@beta.com",
            organization=self.org1,
            metadata={"created_by_id": 999}
        )

        self.customer_t2 = BillingCustomer.objects.create(
            customer_number="CUST-00099",
            name="Tenant 2 Corp",
            email="info@tenant2.com",
            organization=self.org2
        )

        self.subscription1 = Subscription.objects.create(
            subscription_number="SUB-00001",
            customer=self.customer1,
            status="LIVE",
            current_term_start=date.today(),
            current_term_end=date.today()
        )

        self.invoice1 = Invoice.objects.create(
            invoice_number="INV-2026-00001",
            subscription=self.subscription1,
            customer=self.customer1,
            issue_date=date.today(),
            due_date=date.today(),
            status="POSTED",
            subtotal=Decimal('100.00'),
            tax_total=Decimal('0.00'),
            discount_total=Decimal('0.00'),
            total_amount=Decimal('100.00'),
            paid_amount=Decimal('0.00'),
            balance=Decimal('100.00')
        )

        self.invoice2 = Invoice.objects.create(
            invoice_number="INV-2026-00002",
            subscription=self.subscription1,
            customer=self.customer1,
            issue_date=date.today(),
            due_date=date.today(),
            status="POSTED",
            subtotal=Decimal('80.00'),
            tax_total=Decimal('0.00'),
            discount_total=Decimal('0.00'),
            total_amount=Decimal('80.00'),
            paid_amount=Decimal('0.00'),
            balance=Decimal('80.00')
        )

        self.invoice_draft = Invoice.objects.create(
            invoice_number="INV-2026-00003",
            subscription=self.subscription1,
            customer=self.customer1,
            issue_date=date.today(),
            due_date=date.today(),
            status="DRAFT",
            subtotal=Decimal('50.00'),
            total_amount=Decimal('50.00'),
            balance=Decimal('50.00')
        )

        self.invoice_t2 = Invoice.objects.create(
            invoice_number="INV-2026-00099",
            customer=self.customer_t2,
            issue_date=date.today(),
            due_date=date.today(),
            status="POSTED",
            subtotal=Decimal('200.00'),
            total_amount=Decimal('200.00'),
            balance=Decimal('200.00')
        )

        self.client = APIClient()

    def test_payment_recording_service(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('150.00'),
            currency='USD',
            payment_method='BANK_TRANSFER',
            gateway_transaction_id='TXN-1001',
            notes='Test Payment'
        )
        self.assertTrue(payment.payment_number.startswith('PAY-'))
        self.assertEqual(payment.amount, Decimal('150.00'))
        self.assertEqual(payment.unallocated_amount, Decimal('150.00'))
        self.assertEqual(payment.status, 'SUCCEEDED')
        self.assertEqual(payment.customer, self.customer1)

    def test_full_invoice_allocation(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('100.00')
        )
        result = PaymentAllocationService.allocate_payment(
            payment_id=payment.id,
            allocations_data=[{"invoice_id": self.invoice1.id, "amount": "100.00"}]
        )
        payment.refresh_from_db()
        self.invoice1.refresh_from_db()

        self.assertEqual(payment.unallocated_amount, Decimal('0.00'))
        self.assertEqual(self.invoice1.paid_amount, Decimal('100.00'))
        self.assertEqual(self.invoice1.balance, Decimal('0.00'))
        self.assertEqual(self.invoice1.status, 'PAID')
        self.assertIsNotNone(self.invoice1.paid_at)

    def test_partial_invoice_allocation(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('40.00')
        )
        PaymentAllocationService.allocate_payment(
            payment_id=payment.id,
            allocations_data=[{"invoice_id": self.invoice1.id, "amount": "40.00"}]
        )
        payment.refresh_from_db()
        self.invoice1.refresh_from_db()

        self.assertEqual(payment.unallocated_amount, Decimal('0.00'))
        self.assertEqual(self.invoice1.paid_amount, Decimal('40.00'))
        self.assertEqual(self.invoice1.balance, Decimal('60.00'))
        self.assertEqual(self.invoice1.status, 'PARTIALLY_PAID')

    def test_multi_invoice_allocation(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('150.00')
        )
        PaymentAllocationService.allocate_payment(
            payment_id=payment.id,
            allocations_data=[
                {"invoice_id": self.invoice1.id, "amount": "100.00"},
                {"invoice_id": self.invoice2.id, "amount": "50.00"}
            ]
        )
        payment.refresh_from_db()
        self.invoice1.refresh_from_db()
        self.invoice2.refresh_from_db()

        self.assertEqual(payment.unallocated_amount, Decimal('0.00'))
        self.assertEqual(self.invoice1.status, 'PAID')
        self.assertEqual(self.invoice1.balance, Decimal('0.00'))
        self.assertEqual(self.invoice2.status, 'PARTIALLY_PAID')
        self.assertEqual(self.invoice2.paid_amount, Decimal('50.00'))
        self.assertEqual(self.invoice2.balance, Decimal('30.00'))

    def test_overpayment_preserves_unallocated_credit(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('150.00')
        )
        # Allocate $100 to invoice1 ($100 balance)
        PaymentAllocationService.allocate_payment(
            payment_id=payment.id,
            allocations_data=[{"invoice_id": self.invoice1.id, "amount": "100.00"}]
        )
        payment.refresh_from_db()
        self.invoice1.refresh_from_db()

        self.assertEqual(self.invoice1.status, 'PAID')
        self.assertEqual(payment.unallocated_amount, Decimal('50.00'))

    def test_allocation_exceeds_unallocated_fails(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('50.00')
        )
        with self.assertRaises(ValidationError):
            PaymentAllocationService.allocate_payment(
                payment_id=payment.id,
                allocations_data=[{"invoice_id": self.invoice1.id, "amount": "100.00"}]
            )

    def test_allocation_exceeds_invoice_balance_fails(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('150.00')
        )
        with self.assertRaises(ValidationError):
            PaymentAllocationService.allocate_payment(
                payment_id=payment.id,
                allocations_data=[{"invoice_id": self.invoice1.id, "amount": "150.00"}]
            )

    def test_cannot_allocate_to_draft_or_paid_invoice(self):
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('100.00')
        )
        # Allocation to DRAFT fails
        with self.assertRaises(ValidationError):
            PaymentAllocationService.allocate_payment(
                payment_id=payment.id,
                allocations_data=[{"invoice_id": self.invoice_draft.id, "amount": "50.00"}]
            )

        # Settle invoice1 completely
        PaymentAllocationService.allocate_payment(
            payment_id=payment.id,
            allocations_data=[{"invoice_id": self.invoice1.id, "amount": "100.00"}]
        )

        payment2 = PaymentService.record_payment(customer=self.customer1, amount=Decimal('50.00'))
        # Allocation to already PAID invoice fails
        with self.assertRaises(ValidationError):
            PaymentAllocationService.allocate_payment(
                payment_id=payment2.id,
                allocations_data=[{"invoice_id": self.invoice1.id, "amount": "10.00"}]
            )

    def test_cross_customer_allocation_rejected(self):
        payment = PaymentService.record_payment(customer=self.customer1, amount=Decimal('100.00'))
        with self.assertRaises(ValidationError):
            PaymentAllocationService.allocate_payment(
                payment_id=payment.id,
                allocations_data=[{"invoice_id": self.invoice_t2.id, "amount": "100.00"}]
            )

    def test_payment_api_endpoints_and_tenant_isolation(self):
        self.client.force_authenticate(user=self.user_admin)

        # Create payment via API
        res = self.client.post('/api/v1/billing/payments/', {
            "customer": self.customer1.id,
            "amount": "200.00",
            "payment_method": "BANK_TRANSFER",
            "notes": "API Record"
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        pay_id = res.data['id']

        # Allocate via API
        alloc_res = self.client.post(f'/api/v1/billing/payments/{pay_id}/allocate/', {
            "allocations": [
                {"invoice_id": self.invoice1.id, "amount": "100.00"},
                {"invoice_id": self.invoice2.id, "amount": "80.00"}
            ]
        }, format='json')
        self.assertEqual(alloc_res.status_code, status.HTTP_200_OK)
        self.assertEqual(alloc_res.data['unallocated_amount'], '20.00')

        # Tenant isolation check for tenant2
        self.client.force_authenticate(user=self.user_tenant2)
        get_res = self.client.get(f'/api/v1/billing/payments/{pay_id}/')
        self.assertEqual(get_res.status_code, status.HTTP_404_NOT_FOUND)
