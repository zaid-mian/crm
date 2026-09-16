from decimal import Decimal
import datetime
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from catalog.models.product import Product
from catalog.models.plan import PricingPlan
from accounts.models import Organization
from billing.models import (
    AddOn,
    BillingCustomer,
    Subscription,
    SubscriptionItem,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    CreditNote,
    CreditNoteAllocation,
    DebitNote,
    SubscriptionAuditLog,
    SubscriptionChangeLog,
    DunningLog,
)


class BillingModelIntegrityTestCase(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="AdaptCRM Core",
            slug="adaptcrm-core",
            description="Core CRM product"
        )
        self.plan = PricingPlan.objects.create(
            product=self.product,
            name="Professional",
            price=Decimal('99.99'),
            currency='USD',
            billing_cycle='monthly'
        )
        self.organization = Organization.objects.create(
            name="Acme Corp",
            is_active=True
        )

    def test_addon_creation_and_decimal_precision(self):
        addon = AddOn.objects.create(
            product=self.product,
            name="Extra Seats",
            code="extra-seats",
            price=Decimal('15.5000'),
            currency="USD",
            billing_cycle="monthly",
            unit_label="per seat",
            max_quantity=100
        )
        self.assertEqual(addon.price, Decimal('15.50'))
        self.assertEqual(str(addon), "AdaptCRM Core - Extra Seats (extra-seats)")

    def test_billing_customer_creation_and_organization_link(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00001",
            name="Acme Billing Account",
            email="billing@acme.com",
            currency="USD",
            organization=self.organization,
            external_reference_id="EXT-ACME-01"
        )
        self.assertEqual(customer.organization, self.organization)
        self.assertTrue(customer.is_active)
        self.assertEqual(str(customer), "CUST-00001 - Acme Billing Account")

    def test_customer_number_uniqueness(self):
        BillingCustomer.objects.create(
            customer_number="CUST-00001",
            name="First Customer"
        )
        with self.assertRaises(IntegrityError):
            BillingCustomer.objects.create(
                customer_number="CUST-00001",
                name="Duplicate Customer"
            )

    def test_subscription_header_defaults_and_decimal_precision(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00002",
            name="Beta Corp"
        )
        sub = Subscription.objects.create(
            subscription_number="SUB-00001",
            customer=customer,
            status="LIVE",
            collection_method="CHARGE_AUTOMATIC",
            cached_mrr=Decimal('99.999'),
            cached_arr=Decimal('1199.888')
        )
        self.assertEqual(sub.cached_mrr, Decimal('100.00'))
        self.assertEqual(sub.cached_arr, Decimal('1199.89'))
        self.assertEqual(sub.status, 'LIVE')

    def test_subscription_item_plan_xor_addon_constraint(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00003",
            name="Gamma Corp"
        )
        sub = Subscription.objects.create(
            subscription_number="SUB-00002",
            customer=customer,
            status="LIVE"
        )
        addon = AddOn.objects.create(
            product=self.product,
            name="Storage 100GB",
            code="storage-100gb",
            price=Decimal('25.00')
        )

        # Valid PLAN item
        plan_item = SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan,
            quantity=1,
            unit_price=Decimal('99.99')
        )
        self.assertIsNotNone(plan_item.pk)

        # Valid ADDON item
        addon_item = SubscriptionItem.objects.create(
            subscription=sub,
            item_type='ADDON',
            addon=addon,
            quantity=2,
            unit_price=Decimal('25.00')
        )
        self.assertIsNotNone(addon_item.pk)

        # Invalid item: both plan and addon set
        with self.assertRaises((ValidationError, IntegrityError)):
            SubscriptionItem.objects.create(
                subscription=sub,
                item_type='PLAN',
                plan=self.plan,
                addon=addon,
                quantity=1,
                unit_price=Decimal('99.99')
            )

        # Invalid item: neither plan nor addon set
        with self.assertRaises((ValidationError, IntegrityError)):
            SubscriptionItem.objects.create(
                subscription=sub,
                item_type='PLAN',
                quantity=1,
                unit_price=Decimal('99.99')
            )

    def test_invoice_and_invoiceline_creation(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00004",
            name="Delta Corp"
        )
        today = datetime.date.today()
        invoice = Invoice.objects.create(
            invoice_number="INV-2026-00001",
            customer=customer,
            issue_date=today,
            due_date=today + datetime.timedelta(days=30),
            subtotal=Decimal('100.00'),
            tax_total=Decimal('10.00'),
            total_amount=Decimal('110.00'),
            balance=Decimal('110.00'),
            idempotency_key="inv_sub_1_period_20260901"
        )
        line = InvoiceLine.objects.create(
            invoice=invoice,
            description="Professional Plan Monthly",
            quantity=1,
            unit_price=Decimal('100.00'),
            subtotal=Decimal('100.00'),
            total_amount=Decimal('100.00')
        )
        self.assertEqual(invoice.lines.count(), 1)
        self.assertEqual(line.unit_price, Decimal('100.00'))

    def test_invoice_idempotency_key_uniqueness(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00005",
            name="Epsilon Corp"
        )
        today = datetime.date.today()
        Invoice.objects.create(
            invoice_number="INV-2026-00002",
            customer=customer,
            issue_date=today,
            due_date=today,
            idempotency_key="unique-key-123"
        )
        with self.assertRaises(IntegrityError):
            Invoice.objects.create(
                invoice_number="INV-2026-00003",
                customer=customer,
                issue_date=today,
                due_date=today,
                idempotency_key="unique-key-123"
            )

    def test_payment_and_payment_allocation(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00006",
            name="Zeta Corp"
        )
        today = datetime.date.today()
        invoice = Invoice.objects.create(
            invoice_number="INV-2026-00004",
            customer=customer,
            issue_date=today,
            due_date=today,
            total_amount=Decimal('100.00'),
            balance=Decimal('100.00')
        )
        payment = Payment.objects.create(
            payment_number="PAY-00001",
            customer=customer,
            amount=Decimal('100.00'),
            payment_date=today,
            unallocated_amount=Decimal('100.00'),
            status="SUCCEEDED"
        )
        allocation = PaymentAllocation.objects.create(
            payment=payment,
            invoice=invoice,
            amount=Decimal('100.00')
        )
        self.assertEqual(payment.allocations.count(), 1)
        self.assertEqual(allocation.amount, Decimal('100.00'))

    def test_credit_note_and_debit_note(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00007",
            name="Eta Corp"
        )
        today = datetime.date.today()
        invoice = Invoice.objects.create(
            invoice_number="INV-2026-00005",
            customer=customer,
            issue_date=today,
            due_date=today,
            total_amount=Decimal('150.00'),
            balance=Decimal('150.00')
        )
        cn = CreditNote.objects.create(
            credit_note_number="CN-00001",
            customer=customer,
            invoice=invoice,
            reason="GOODWILL",
            total_amount=Decimal('50.00'),
            unallocated_amount=Decimal('50.00'),
            status="ISSUED",
            issued_date=today
        )
        cn_alloc = CreditNoteAllocation.objects.create(
            credit_note=cn,
            invoice=invoice,
            amount=Decimal('50.00')
        )
        dn = DebitNote.objects.create(
            debit_note_number="DN-00001",
            invoice=invoice,
            amount=Decimal('15.00'),
            reason="Late payment fee",
            issued_date=today
        )
        self.assertEqual(cn_alloc.amount, Decimal('50.00'))
        self.assertEqual(dn.amount, Decimal('15.00'))

    def test_audit_and_operational_logs(self):
        customer = BillingCustomer.objects.create(
            customer_number="CUST-00008",
            name="Theta Corp"
        )
        sub = Subscription.objects.create(
            subscription_number="SUB-00003",
            customer=customer,
            status="LIVE"
        )
        today = datetime.date.today()
        audit_log = SubscriptionAuditLog.objects.create(
            subscription=sub,
            actor_id="admin_1",
            actor_type="USER",
            action="STATUS_CHANGE",
            old_state="DRAFT",
            new_state="LIVE",
            reason="Initial activation"
        )
        change_log = SubscriptionChangeLog.objects.create(
            subscription=sub,
            change_type="ADD_ITEM",
            proration_amount=Decimal('12.50'),
            effective_date=today
        )
        dunning_log = DunningLog.objects.create(
            subscription=sub,
            attempt_number=1,
            status="FAILED",
            error_code="card_declined",
            error_message="Insufficient funds"
        )
        self.assertEqual(sub.audit_logs.count(), 1)
        self.assertEqual(sub.change_logs.count(), 1)
        self.assertEqual(sub.dunning_logs.count(), 1)
