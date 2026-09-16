from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import Organization
from billing.models import (
    BillingCustomer,
    Subscription,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    CreditNote,
    CreditNoteAllocation,
    DebitNote,
    SubscriptionChangeLog,
)
from billing.services import (
    CreditNoteService,
    DebitNoteService,
    CreditNoteAllocationService,
    PaymentService,
    PaymentAllocationService,
)

User = get_user_model()


class BillingCreditAndDebitNotesTestCase(TestCase):
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
            organization=self.org2,
            metadata={"created_by_id": self.user_tenant2.id}
        )

        # Standard posted invoice for customer 1 ($100.00 total, $100.00 balance)
        self.invoice1 = Invoice.objects.create(
            invoice_number="INV-2026-00001",
            customer=self.customer1,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 9, 15),
            subtotal=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            paid_amount=Decimal('0.00'),
            balance=Decimal('100.00'),
            status='POSTED'
        )
        InvoiceLine.objects.create(
            invoice=self.invoice1,
            description="Professional Tier Monthly",
            quantity=1,
            unit_price=Decimal('100.00'),
            subtotal=Decimal('100.00'),
            total_amount=Decimal('100.00')
        )

        # Second posted invoice for customer 1 ($70.00 total, $70.00 balance)
        self.invoice2 = Invoice.objects.create(
            invoice_number="INV-2026-00002",
            customer=self.customer1,
            issue_date=date(2026, 9, 2),
            due_date=date(2026, 9, 16),
            subtotal=Decimal('70.00'),
            total_amount=Decimal('70.00'),
            paid_amount=Decimal('0.00'),
            balance=Decimal('70.00'),
            status='POSTED'
        )

        # Invoice for customer 2 (Tenant 2)
        self.invoice_tenant2 = Invoice.objects.create(
            invoice_number="INV-2026-00099",
            customer=self.customer2,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 9, 15),
            subtotal=Decimal('200.00'),
            total_amount=Decimal('200.00'),
            paid_amount=Decimal('0.00'),
            balance=Decimal('200.00'),
            status='POSTED'
        )

        self.client = APIClient()

    # -------------------------------------------------------------------------
    # 1. Credit Note Issuance & Integrity
    # -------------------------------------------------------------------------

    def test_01_credit_note_issuance_success(self):
        """1. Credit Note can be issued with valid customer and amount."""
        cn = CreditNoteService.issue_credit_note(
            customer=self.customer1,
            amount=Decimal('150.00'),
            reason='GOODWILL',
            user=self.user_sales
        )
        self.assertIsNotNone(cn.id)
        self.assertTrue(cn.credit_note_number.startswith('CN-'))
        self.assertEqual(cn.status, 'ISSUED')
        self.assertEqual(cn.reason, 'GOODWILL')
        self.assertEqual(cn.total_amount, Decimal('150.00'))
        self.assertEqual(cn.unallocated_amount, Decimal('150.00'))
        self.assertEqual(cn.subtotal, Decimal('150.00'))
        self.assertEqual(cn.tax_total, Decimal('0.00'))

    def test_02_correct_amount_stored_with_precision(self):
        """2. Correct Decimal amount stored with 2 decimal places precision."""
        cn = CreditNoteService.issue_credit_note(
            customer=self.customer1,
            amount=Decimal('49.994'),  # should quantize to 49.99
            subtotal=Decimal('49.994'),
            tax_total=Decimal('0.00')
        )
        self.assertEqual(cn.total_amount, Decimal('49.99'))
        self.assertEqual(cn.unallocated_amount, Decimal('49.99'))

    def test_03_credit_note_with_invoice_association(self):
        """3. Correct customer and invoice association when attached."""
        cn = CreditNoteService.issue_credit_note(
            customer=self.customer1,
            amount=Decimal('30.00'),
            reason='CORRECTION',
            invoice=self.invoice1,
            user=self.user_sales
        )
        self.assertEqual(cn.customer, self.customer1)
        self.assertEqual(cn.invoice, self.invoice1)

    def test_04_tenant_isolation_on_credit_note_issuance(self):
        """4. Tenant isolation prevents issuing credit note for customer in another organization."""
        with self.assertRaises(PermissionDenied):
            CreditNoteService.issue_credit_note(
                customer=self.customer2,  # Org 2
                amount=Decimal('50.00'),
                user=self.user_sales  # Org 1
            )

    def test_05_invalid_amounts_rejected(self):
        """5. Invalid monetary amounts (zero, negative, None, invalid types) are rejected."""
        with self.assertRaises(ValidationError):
            CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('0.00'))

        with self.assertRaises(ValidationError):
            CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('-25.00'))

        with self.assertRaises(ValidationError):
            CreditNoteService.issue_credit_note(customer=self.customer1, amount=None)

        with self.assertRaises(ValidationError):
            CreditNoteService.issue_credit_note(customer=self.customer1, amount="invalid_num")

    def test_06_posted_invoice_remains_unchanged_on_credit_note_issuance(self):
        """6. Issuing a credit note referencing an invoice does NOT modify original posted invoice totals or lines."""
        cn = CreditNoteService.issue_credit_note(
            customer=self.customer1,
            amount=Decimal('50.00'),
            reason='CORRECTION',
            invoice=self.invoice1
        )
        self.invoice1.refresh_from_db()
        self.assertEqual(self.invoice1.total_amount, Decimal('100.00'))
        self.assertEqual(self.invoice1.subtotal, Decimal('100.00'))
        self.assertEqual(self.invoice1.balance, Decimal('100.00'))
        self.assertEqual(self.invoice1.status, 'POSTED')
        self.assertEqual(self.invoice1.lines.count(), 1)

    # -------------------------------------------------------------------------
    # 2. Allocation Mechanics (Partial, Full, Over-allocation)
    # -------------------------------------------------------------------------

    def test_07_partial_allocation(self):
        """7-10. Partial allocation reduces invoice balance and credit note remaining balance."""
        cn = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('100.00'))
        # invoice2 outstanding balance is $70.00. Allocate $40.00.
        result = CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=cn.id,
            allocations_data=[{'invoice_id': self.invoice2.id, 'amount': Decimal('40.00')}],
            user=self.user_sales
        )

        cn.refresh_from_db()
        self.invoice2.refresh_from_db()

        # 8. Invoice balance decreases from $70 to $30
        self.assertEqual(self.invoice2.balance, Decimal('30.00'))
        self.assertEqual(self.invoice2.status, 'PARTIALLY_PAID')

        # 9. Credit Note remaining balance decreases from $100 to $60
        self.assertEqual(cn.unallocated_amount, Decimal('60.00'))

        # 10. Customer unapplied credit is now $60.00
        unapplied = CreditNoteService.get_customer_unapplied_credit(self.customer1)
        self.assertEqual(unapplied, Decimal('60.00'))

        # Allocation record verification
        self.assertEqual(len(result['allocations']), 1)
        self.assertEqual(result['allocations'][0].amount, Decimal('40.00'))

    def test_11_full_allocation_settles_invoice(self):
        """11-12. Full allocation settles invoice to zero balance and marks it PAID."""
        cn = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('100.00'))
        # invoice1 total balance is $100.00. Allocate $100.00.
        result = CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=cn.id,
            allocations_data=[{'invoice_id': self.invoice1.id, 'amount': Decimal('100.00')}],
            user=self.user_sales
        )

        cn.refresh_from_db()
        self.invoice1.refresh_from_db()

        self.assertEqual(self.invoice1.balance, Decimal('0.00'))
        self.assertEqual(self.invoice1.status, 'PAID')
        self.assertIsNotNone(self.invoice1.paid_at)

        self.assertEqual(cn.unallocated_amount, Decimal('0.00'))
        unapplied = CreditNoteService.get_customer_unapplied_credit(self.customer1)
        self.assertEqual(unapplied, Decimal('0.00'))

    def test_13_cannot_allocate_more_than_credit_note_balance(self):
        """13. Attempting to allocate more than Credit Note's remaining balance is rejected."""
        cn = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('50.00'))
        with self.assertRaises(ValidationError) as ctx:
            CreditNoteAllocationService.allocate_credit_note(
                credit_note_id=cn.id,
                allocations_data=[{'invoice_id': self.invoice1.id, 'amount': Decimal('75.00')}],
                user=self.user_sales
            )
        self.assertIn("exceeds available credit note balance", str(ctx.exception))

    def test_14_cannot_allocate_more_than_invoice_balance(self):
        """14. Attempting to allocate more than Invoice remaining balance is rejected."""
        cn = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('100.00'))
        # invoice2 balance is $70.00. Allocate $80.00.
        with self.assertRaises(ValidationError) as ctx:
            CreditNoteAllocationService.allocate_credit_note(
                credit_note_id=cn.id,
                allocations_data=[{'invoice_id': self.invoice2.id, 'amount': Decimal('80.00')}],
                user=self.user_sales
            )
        self.assertIn("exceeds invoice", str(ctx.exception))

    def test_15_sequential_multi_allocation_settlement(self):
        """15. Multi-step allocation correctly tracks remaining balances across invoices."""
        cn = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('100.00'))

        # Step 1: Allocate $40 to invoice2 ($70 -> $30)
        CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=cn.id,
            allocations_data=[{'invoice_id': self.invoice2.id, 'amount': Decimal('40.00')}],
            user=self.user_sales
        )

        # Step 2: Allocate remaining $30 to settle invoice2 completely ($30 -> $0)
        CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=cn.id,
            allocations_data=[{'invoice_id': self.invoice2.id, 'amount': Decimal('30.00')}],
            user=self.user_sales
        )

        self.invoice2.refresh_from_db()
        cn.refresh_from_db()
        self.assertEqual(self.invoice2.balance, Decimal('0.00'))
        self.assertEqual(self.invoice2.status, 'PAID')
        self.assertEqual(cn.unallocated_amount, Decimal('30.00'))

        # Step 3: Allocate remaining $30 to invoice1 ($100 -> $70)
        CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=cn.id,
            allocations_data=[{'invoice_id': self.invoice1.id, 'amount': Decimal('30.00')}],
            user=self.user_sales
        )

        self.invoice1.refresh_from_db()
        cn.refresh_from_db()
        self.assertEqual(self.invoice1.balance, Decimal('70.00'))
        self.assertEqual(cn.unallocated_amount, Decimal('0.00'))

        # Step 4: Further allocation from empty CN must fail
        with self.assertRaises(ValidationError):
            CreditNoteAllocationService.allocate_credit_note(
                credit_note_id=cn.id,
                allocations_data=[{'invoice_id': self.invoice1.id, 'amount': Decimal('10.00')}],
                user=self.user_sales
            )

    def test_16_cross_tenant_allocation_prevention(self):
        """16. Cross-tenant allocation is rejected cleanly."""
        cn1 = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('100.00'))
        with self.assertRaises((ValidationError, PermissionDenied)):
            CreditNoteAllocationService.allocate_credit_note(
                credit_note_id=cn1.id,
                allocations_data=[{'invoice_id': self.invoice_tenant2.id, 'amount': Decimal('50.00')}],
                user=self.user_sales
            )

    # -------------------------------------------------------------------------
    # 3. Debit Note Issuance & Immutability
    # -------------------------------------------------------------------------

    def test_17_debit_note_issuance(self):
        """17-18. Debit Note is issued with correct amount and sequential number."""
        dn = DebitNoteService.issue_debit_note(
            invoice=self.invoice1,
            amount=Decimal('25.00'),
            reason="Late payment penalty fee",
            user=self.user_sales
        )
        self.assertIsNotNone(dn.id)
        self.assertTrue(dn.debit_note_number.startswith('DN-'))
        self.assertEqual(dn.amount, Decimal('25.00'))
        self.assertEqual(dn.invoice, self.invoice1)
        self.assertEqual(dn.reason, "Late payment penalty fee")

    def test_19_debit_note_preserves_posted_invoice_immutability(self):
        """19. Issuing Debit Note does NOT rewrite or modify original posted invoice lines or totals."""
        dn = DebitNoteService.issue_debit_note(
            invoice=self.invoice1,
            amount=Decimal('35.00'),
            reason="Usage overage surcharge"
        )
        self.invoice1.refresh_from_db()
        self.assertEqual(self.invoice1.total_amount, Decimal('100.00'))
        self.assertEqual(self.invoice1.subtotal, Decimal('100.00'))
        self.assertEqual(self.invoice1.lines.count(), 1)
        self.assertEqual(self.invoice1.lines.first().total_amount, Decimal('100.00'))

    def test_20_debit_note_tenant_isolation(self):
        """Cannot issue Debit Note for another tenant's invoice."""
        with self.assertRaises(PermissionDenied):
            DebitNoteService.issue_debit_note(
                invoice=self.invoice_tenant2,
                amount=Decimal('10.00'),
                user=self.user_sales
            )

    # -------------------------------------------------------------------------
    # 4. Immutability & Serializer Protection
    # -------------------------------------------------------------------------

    def test_21_credit_note_immutability_enforced(self):
        """21. Issued Credit Note financial identity fields cannot be modified via serializer."""
        cn = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('100.00'))
        self.client.force_authenticate(user=self.user_admin)
        res = self.client.patch(f'/api/v1/billing/credit-notes/{cn.id}/', {'total_amount': '200.00'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_22_debit_note_immutability_enforced(self):
        """22. Issued Debit Note financial identity fields cannot be modified via serializer."""
        dn = DebitNoteService.issue_debit_note(invoice=self.invoice1, amount=Decimal('25.00'))
        self.client.force_authenticate(user=self.user_admin)
        res = self.client.patch(f'/api/v1/billing/debit-notes/{dn.id}/', {'amount': '50.00'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------------------------------------------------------
    # 5. Regression Safety & Dual Settlement
    # -------------------------------------------------------------------------

    def test_23_dual_settlement_credit_note_and_payment(self):
        """23. An invoice can be settled with a combination of Credit Note and Payment."""
        # invoice1 balance = $100.00
        # 1. Apply $40.00 Credit Note
        cn = CreditNoteService.issue_credit_note(customer=self.customer1, amount=Decimal('40.00'))
        CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=cn.id,
            allocations_data=[{'invoice_id': self.invoice1.id, 'amount': Decimal('40.00')}]
        )

        self.invoice1.refresh_from_db()
        self.assertEqual(self.invoice1.balance, Decimal('60.00'))
        self.assertEqual(self.invoice1.status, 'PARTIALLY_PAID')

        # 2. Record and allocate $60.00 Payment
        payment = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal('60.00'),
            payment_method='CREDIT_CARD'
        )
        PaymentAllocationService.allocate_payment(
            payment_id=payment.id,
            allocations_data=[{'invoice_id': self.invoice1.id, 'amount': Decimal('60.00')}]
        )

        self.invoice1.refresh_from_db()
        self.assertEqual(self.invoice1.balance, Decimal('0.00'))
        self.assertEqual(self.invoice1.paid_amount, Decimal('60.00'))
        self.assertEqual(self.invoice1.status, 'PAID')
        self.assertIsNotNone(self.invoice1.paid_at)

    def test_24_rest_api_endpoints(self):
        """24. REST endpoints POST /credit-notes/, POST /credit-notes/<id>/allocate/, POST /debit-notes/."""
        self.client.force_authenticate(user=self.user_admin)

        # 1. Create Credit Note via API
        res_cn = self.client.post('/api/v1/billing/credit-notes/', {
            'customer_id': self.customer1.id,
            'amount': '80.00',
            'reason': 'GOODWILL'
        })
        self.assertEqual(res_cn.status_code, status.HTTP_201_CREATED)
        cn_id = res_cn.data['id']
        self.assertEqual(res_cn.data['unallocated_amount'], '80.00')

        # 2. Allocate Credit Note via API
        res_alloc = self.client.post(f'/api/v1/billing/credit-notes/{cn_id}/allocate/', {
            'invoice_id': self.invoice2.id,
            'amount': '50.00'
        })
        self.assertEqual(res_alloc.status_code, status.HTTP_200_OK)
        self.assertEqual(res_alloc.data['unallocated_amount'], '30.00')

        self.invoice2.refresh_from_db()
        self.assertEqual(self.invoice2.balance, Decimal('20.00'))

        # 3. Create Debit Note via API
        res_dn = self.client.post('/api/v1/billing/debit-notes/', {
            'invoice_id': self.invoice1.id,
            'amount': '15.00',
            'reason': 'Adjustment fee'
        })
        self.assertEqual(res_dn.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_dn.data['amount'], '15.00')

        # 4. Check unapplied credit endpoint
        res_credit = self.client.get(f'/api/v1/billing/credit-notes/unapplied-credit/?customer_id={self.customer1.id}')
        self.assertEqual(res_credit.status_code, status.HTTP_200_OK)
        self.assertEqual(res_credit.data['unapplied_credit'], '30.00')

    def test_25_phase12_downgrade_integration_preservation(self):
        """25. Phase 12 downgrade credit recorded in SubscriptionChangeLog can be formalized as a Credit Note."""
        # Simulate Phase 12 downgrade change log entry with negative proration delta
        sub = Subscription.objects.create(
            subscription_number="SUB-00001",
            customer=self.customer1,
            current_term_start=date(2026, 9, 1),
            current_term_end=date(2026, 9, 30),
            next_billing_date=date(2026, 10, 1),
            status='LIVE'
        )
        change_log = SubscriptionChangeLog.objects.create(
            subscription=sub,
            change_type='DOWNGRADE',
            proration_amount=Decimal('-45.00'),
            effective_date=date(2026, 9, 15),
            details={'reason': 'Customer downgraded to Starter Plan', 'net_proration_amount': '-45.00'}
        )

        # Authorized user formalizes the credit as a formal Credit Note
        net_credit = abs(change_log.proration_amount)
        cn = CreditNoteService.issue_credit_note(
            customer=self.customer1,
            amount=net_credit,
            reason='REFUND',
            user=self.user_sales
        )
        self.assertEqual(cn.total_amount, Decimal('45.00'))
        self.assertEqual(cn.unallocated_amount, Decimal('45.00'))
        self.assertEqual(cn.reason, 'REFUND')

