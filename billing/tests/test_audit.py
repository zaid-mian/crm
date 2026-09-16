from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import Organization
from catalog.models.product import Product
from catalog.models.plan import PricingPlan
from billing.models import (
    BillingCustomer,
    Subscription,
    SubscriptionItem,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    CreditNote,
    DebitNote,
    DunningLog,
    SubscriptionAuditLog,
    SubscriptionChangeLog,
)
from billing.services import (
    BillingAuditService,
    CustomerService,
    SubscriptionService,
    SubscriptionStateMachineService,
    SubscriptionLifecycleService,
    SubscriptionAmendmentService,
    SubscriptionRenewalService,
    PaymentService,
    PaymentAllocationService,
    CreditNoteService,
    CreditNoteAllocationService,
    DebitNoteService,
)
from roles.models import Role, RolePermission, CRMResource
from leads.models import UserProfile


class BillingAuditTestSuite(TestCase):
    def setUp(self):
        self.org1 = Organization.objects.create(name="Audit Org 1")
        self.org2 = Organization.objects.create(name="Audit Org 2")

        # Roles
        self.admin_role, _ = Role.objects.get_or_create(name="Administrator", defaults={"is_system": True})
        self.sales_role, _ = Role.objects.get_or_create(name="Salesperson", defaults={"is_system": True})

        self.billing_resource, _ = CRMResource.objects.get_or_create(codename="billing", defaults={"name": "Billing"})
        RolePermission.objects.get_or_create(role=self.admin_role, resource=self.billing_resource, action="VIEW", defaults={"scope": "ALL"})
        RolePermission.objects.get_or_create(role=self.admin_role, resource=self.billing_resource, action="CREATE", defaults={"scope": "ALL"})
        RolePermission.objects.get_or_create(role=self.sales_role, resource=self.billing_resource, action="VIEW", defaults={"scope": "OWN"})
        RolePermission.objects.get_or_create(role=self.sales_role, resource=self.billing_resource, action="CREATE", defaults={"scope": "OWN"})

        # Users
        self.admin_user = User.objects.create_user(username="admin_audit", password="password123", email="admin@audit.com")
        if hasattr(self.admin_user, 'profile'):
            self.admin_user.profile.organization = self.org1
            self.admin_user.profile.role = self.admin_role
            self.admin_user.profile.save()
        else:
            UserProfile.objects.create(user=self.admin_user, organization=self.org1, role=self.admin_role)

        self.sales_user = User.objects.create_user(username="sales_audit", password="password123", email="sales@audit.com")
        if hasattr(self.sales_user, 'profile'):
            self.sales_user.profile.organization = self.org1
            self.sales_user.profile.role = self.sales_role
            self.sales_user.profile.save()
        else:
            UserProfile.objects.create(user=self.sales_user, organization=self.org1, role=self.sales_role)

        self.org2_user = User.objects.create_user(username="org2_user", password="password123", email="org2@audit.com")
        if hasattr(self.org2_user, 'profile'):
            self.org2_user.profile.organization = self.org2
            self.org2_user.profile.role = self.admin_role
            self.org2_user.profile.save()
        else:
            UserProfile.objects.create(user=self.org2_user, organization=self.org2, role=self.admin_role)

        self.client = APIClient()

        # Customer & Subscription setup in Org 1
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number="CUST-90001",
            name="Audit Test Corp",
            email="corp@audit.com",
            currency="USD",
            metadata={"created_by_id": self.sales_user.id}
        )

        self.product = Product.objects.create(name="Audit Product", slug="audit-product", is_active=True)
        self.plan1 = PricingPlan.objects.create(
            product=self.product,
            name="Audit Standard Plan",
            price=Decimal("100.00"),
            billing_cycle="monthly",
            is_active=True
        )

        self.subscription1 = SubscriptionService.create_subscription(
            organization=self.org1,
            user=self.sales_user,
            validated_data={
                "customer": self.customer1,
                "billing_cycle": "MONTHLY",
                "current_term_start": date.today(),
                "status": "DRAFT",
                "metadata": {"created_by_id": self.sales_user.id}
            }
        )
        self.item1 = SubscriptionItem.objects.create(
            subscription=self.subscription1,
            item_type="PLAN",
            plan=self.plan1,
            unit_price=Decimal("100.00"),
            quantity=1
        )
        self.subscription1.cached_mrr = Decimal("100.00")
        self.subscription1.cached_arr = Decimal("1200.00")
        self.subscription1.save()

    # =========================================================================
    # 1. IMMUTABILITY ENFORCEMENT
    # =========================================================================

    def test_audit_log_modification_blocked(self):
        """1. SubscriptionAuditLog cannot be modified once created."""
        log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1).first()
        self.assertIsNotNone(log)

        log.reason = "Tampered reason"
        with self.assertRaises(ValidationError) as ctx:
            log.save()
        self.assertIn("Historical audit records are immutable", str(ctx.exception))

    def test_audit_log_deletion_blocked(self):
        """2. SubscriptionAuditLog cannot be deleted once created."""
        log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1).first()
        with self.assertRaises(ValidationError) as ctx:
            log.delete()
        self.assertIn("Historical audit records are immutable", str(ctx.exception))

    def test_change_log_immutability(self):
        """3. SubscriptionChangeLog cannot be modified or deleted."""
        chg = SubscriptionChangeLog.objects.create(
            subscription=self.subscription1,
            change_type="ADD_ITEM",
            details={"item": "Extra storage"},
            proration_amount=Decimal("15.00"),
            effective_date=date.today()
        )
        chg.proration_amount = Decimal("99.00")
        with self.assertRaises(ValidationError):
            chg.save()

        with self.assertRaises(ValidationError):
            chg.delete()

    def test_dunning_log_immutability(self):
        """4. DunningLog cannot be modified or deleted."""
        dunn = DunningLog.objects.create(
            subscription=self.subscription1,
            attempt_number=1,
            status="FAILED",
            error_code="CARD_DECLINED",
            error_message="Card declined by bank"
        )
        dunn.status = "SUCCESS"
        with self.assertRaises(ValidationError):
            dunn.save()

        with self.assertRaises(ValidationError):
            dunn.delete()

    def test_queryset_bulk_update_and_delete_blocked(self):
        """5. Bulk ORM update and delete queries on audit tables are rejected."""
        qs = SubscriptionAuditLog.objects.filter(subscription=self.subscription1)
        self.assertTrue(qs.exists())

        with self.assertRaises(ValidationError):
            qs.update(reason="Bulk malicious update")

        with self.assertRaises(ValidationError):
            qs.delete()

    def test_api_write_methods_rejected_with_405(self):
        """6. POST, PUT, PATCH, DELETE to /api/v1/billing/audit/ return 405 Method Not Allowed."""
        self.client.force_authenticate(user=self.admin_user)

        res_post = self.client.post('/api/v1/billing/audit/', {'action': 'HACK'}, format='json')
        self.assertEqual(res_post.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1).first()
        res_put = self.client.put(f'/api/v1/billing/audit/{log.id}/', {'reason': 'HACK'}, format='json')
        self.assertEqual(res_put.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        res_del = self.client.delete(f'/api/v1/billing/audit/{log.id}/')
        self.assertEqual(res_del.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # =========================================================================
    # 2. MUTATION COVERAGE & AUDIT GENERATION
    # =========================================================================

    def test_subscription_creation_creates_audit_log(self):
        """7. Subscription creation produces an immutable SUBSCRIPTION_CREATED audit log."""
        logs = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, action="SUBSCRIPTION_CREATED")
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.actor_id, str(self.sales_user.id))
        self.assertEqual(log.actor_type, "USER")
        self.assertEqual(log.new_state, "DRAFT")

    def test_lifecycle_transitions_produce_audit_logs(self):
        """8. State machine transitions produce STATE_TRANSITION logs with state deltas."""
        # DRAFT -> LIVE
        SubscriptionStateMachineService.transition(
            subscription=self.subscription1,
            to_status="LIVE",
            user=self.admin_user,
            reason="Approved onboarding"
        )
        log_live = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, new_state="LIVE").first()
        self.assertIsNotNone(log_live)
        self.assertEqual(log_live.old_state, "DRAFT")
        self.assertEqual(log_live.actor_id, str(self.admin_user.id))
        self.assertEqual(log_live.reason, "Approved onboarding")

        # LIVE -> PAUSED
        SubscriptionLifecycleService.pause_subscription(
            subscription=self.subscription1,
            reason="Customer seasonal pause",
            user=self.admin_user
        )
        log_paused = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, new_state="PAUSED").first()
        self.assertIsNotNone(log_paused)
        self.assertEqual(log_paused.old_state, "LIVE")
        self.assertEqual(log_paused.reason, "Customer seasonal pause")

        # PAUSED -> LIVE (Resume)
        SubscriptionLifecycleService.resume_subscription(
            subscription=self.subscription1,
            user=self.admin_user
        )
        log_resumed = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, old_state="PAUSED", new_state="LIVE").first()
        self.assertIsNotNone(log_resumed)

    def test_pause_and_resume_api_actor_attribution(self):
        """8b. REST API pause and resume endpoints accurately attribute logs to the authenticated requesting user."""
        # 1. Transition to LIVE
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        # 2. Authenticate as sales_user and pause
        self.client.force_authenticate(user=self.sales_user)
        res_pause = self.client.post(
            f'/api/v1/billing/subscriptions/{self.subscription1.id}/pause/',
            {'reason': 'Sales user pausing subscription for client review'},
            format='json'
        )
        self.assertEqual(res_pause.status_code, status.HTTP_200_OK)

        pause_log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, new_state="PAUSED").order_by('-id').first()
        self.assertIsNotNone(pause_log)
        self.assertEqual(pause_log.actor_id, str(self.sales_user.id))
        self.assertEqual(pause_log.metadata.get('actor_username'), self.sales_user.username)

        # 3. Authenticate as admin_user and resume
        self.client.force_authenticate(user=self.admin_user)
        res_resume = self.client.post(
            f'/api/v1/billing/subscriptions/{self.subscription1.id}/resume/',
            {},
            format='json'
        )
        self.assertEqual(res_resume.status_code, status.HTTP_200_OK)

        resume_log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, old_state="PAUSED", new_state="LIVE").order_by('-id').first()
        self.assertIsNotNone(resume_log)
        self.assertEqual(resume_log.actor_id, str(self.admin_user.id))
        self.assertEqual(resume_log.metadata.get('actor_username'), self.admin_user.username)

        # 4. Fetch unified audit feed and verify both events have distinct, correct actor attribution
        res_feed = self.client.get(f'/api/v1/billing/subscriptions/{self.subscription1.id}/audit-logs/')
        self.assertEqual(res_feed.status_code, status.HTTP_200_OK)

        feed_pause = next((item for item in res_feed.data if item['action'] == 'STATE_TRANSITION' and item.get('state_delta', {}).get('new') == 'PAUSED'), None)
        self.assertIsNotNone(feed_pause)
        self.assertEqual(feed_pause['actor_id'], str(self.sales_user.id))
        self.assertEqual(feed_pause['actor_name'], self.sales_user.username)

        feed_resume = next((item for item in res_feed.data if item['action'] == 'STATE_TRANSITION' and item.get('state_delta', {}).get('new') == 'LIVE' and item.get('state_delta', {}).get('old') == 'PAUSED'), None)
        self.assertIsNotNone(feed_resume)
        self.assertEqual(feed_resume['actor_id'], str(self.admin_user.id))
        self.assertEqual(feed_resume['actor_name'], self.admin_user.username)

    def test_cancellation_produces_audit_log(self):
        """9. Immediate and period-end cancellations produce audit records with reasons."""
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        SubscriptionLifecycleService.cancel_subscription(
            subscription=self.subscription1,
            cancel_type="PERIOD_END",
            reason="Customer switching vendors",
            user=self.sales_user
        )
        log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, new_state="NON_RENEWING").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.reason, "Customer switching vendors")
        self.assertEqual(log.metadata.get("cancel_type"), "PERIOD_END")

    def test_amendment_creates_audit_and_change_logs(self):
        """10. Subscription amendment creates both a change log with proration and an audit log."""
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        new_plan = PricingPlan.objects.create(
            product=self.product,
            name="Audit Enterprise Plan",
            price=Decimal("300.00"),
            billing_cycle="monthly",
            is_active=True
        )

        result = SubscriptionAmendmentService.apply_amendment(
            subscription=self.subscription1,
            new_plan_id=new_plan.id,
            reason="Upgrade to Enterprise",
            user=self.sales_user
        )

        # Check SubscriptionChangeLog
        change_logs = SubscriptionChangeLog.objects.filter(subscription=self.subscription1)
        self.assertEqual(change_logs.count(), 1)
        chg = change_logs.first()
        self.assertEqual(chg.change_type, "PLAN_UPGRADE")
        self.assertGreater(chg.proration_amount, Decimal("0.00"))

        # Check SubscriptionAuditLog
        audit = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, action="SUBSCRIPTION_AMENDED").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor_id, str(self.sales_user.id))
        self.assertEqual(audit.reason, "Upgrade to Enterprise")

    def test_renewal_creates_system_audit_log(self):
        """11. Subscription renewal logs SYSTEM actor and RENEWAL_COMPLETED action."""
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        # Set next_billing_date to today so it is eligible for renewal
        self.subscription1.next_billing_date = date.today()
        self.subscription1.save()

        # Execute renewal
        res = SubscriptionRenewalService.renew_subscription(
            subscription=self.subscription1,
            user=None
        )
        self.assertIsNotNone(res.get('invoice'))

        log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, action="RENEWAL_COMPLETED").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor_type, "SYSTEM")
        self.assertEqual(log.actor_id, "SYSTEM")

    def test_financial_adjustments_create_audit_logs(self):
        """12. Credit Note and Debit Note issuance & allocations create financial audit logs."""
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        # Invoice
        inv = Invoice.objects.create(
            customer=self.customer1,
            subscription=self.subscription1,
            invoice_number="INV-2026-90001",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            balance=Decimal("100.00"),
            status="POSTED",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=14)
        )

        # 1. Issue Credit Note against invoice
        cn = CreditNoteService.issue_credit_note(
            customer=self.customer1,
            amount=Decimal("40.00"),
            invoice=inv,
            reason="GOODWILL",
            user=self.admin_user
        )
        cn_log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, action="CREDIT_NOTE_ISSUED").first()
        self.assertIsNotNone(cn_log)
        self.assertEqual(cn_log.metadata.get("credit_note_number"), cn.credit_note_number)

        # 2. Allocate Credit Note to invoice
        CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=cn.id,
            allocations_data=[{"invoice_id": inv.id, "amount": Decimal("40.00")}],
            user=self.admin_user
        )
        alloc_log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, action="CREDIT_NOTE_ALLOCATED").first()
        self.assertIsNotNone(alloc_log)
        self.assertEqual(alloc_log.metadata.get("allocated_amount"), "40.00")

        # 3. Issue Debit Note against invoice
        dn = DebitNoteService.issue_debit_note(
            invoice=inv,
            amount=Decimal("15.00"),
            reason="Late fee penalty",
            user=self.admin_user
        )
        dn_log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, action="DEBIT_NOTE_ISSUED").first()
        self.assertIsNotNone(dn_log)
        self.assertEqual(dn_log.metadata.get("debit_note_number"), dn.debit_note_number)

    def test_payment_allocation_creates_audit_log(self):
        """13. Payment allocation creates PAYMENT_ALLOCATED financial audit record."""
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        inv = Invoice.objects.create(
            customer=self.customer1,
            subscription=self.subscription1,
            invoice_number="INV-2026-90002",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            balance=Decimal("100.00"),
            status="POSTED",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=14)
        )

        pmt = PaymentService.record_payment(
            customer=self.customer1,
            amount=Decimal("100.00"),
            payment_method="BANK_TRANSFER"
        )

        PaymentAllocationService.allocate_payment(
            payment_id=pmt.id,
            allocations_data=[{"invoice_id": inv.id, "amount": Decimal("100.00")}],
            user=self.admin_user
        )

        pmt_log = SubscriptionAuditLog.objects.filter(subscription=self.subscription1, action="PAYMENT_ALLOCATED").first()
        self.assertIsNotNone(pmt_log)
        self.assertEqual(pmt_log.metadata.get("payment_number"), pmt.payment_number)
        self.assertEqual(pmt_log.metadata.get("allocated_amount"), "100.00")

    # =========================================================================
    # 3. SECURITY, TENANT ISOLATION, RBAC & SANITIZATION
    # =========================================================================

    def test_tenant_isolation_enforced_on_audit_api(self):
        """14. Org 2 user cannot query or view Org 1 audit logs."""
        self.client.force_authenticate(user=self.org2_user)

        res = self.client.get('/api/v1/billing/audit/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Should be empty for Org 2
        results = res.data if isinstance(res.data, list) else res.data.get('results', [])
        self.assertEqual(len(results), 0)

        # Direct access to Org 1 subscription audit logs endpoint
        res_sub = self.client.get(f'/api/v1/billing/subscriptions/{self.subscription1.id}/audit-logs/')
        self.assertEqual(res_sub.status_code, status.HTTP_404_NOT_FOUND)

    def test_rbac_all_vs_own_scoping(self):
        """15. Admin (ALL) sees all tenant logs; Salesperson (OWN) sees only owned subscription logs."""
        # Create un-owned subscription in Org 1
        other_cust = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number="CUST-90002",
            name="Other Corp",
            currency="USD",
            metadata={"created_by_id": 9999}
        )
        other_sub = SubscriptionService.create_subscription(
            organization=self.org1,
            user=None,
            validated_data={
                "customer": other_cust,
                "billing_cycle": "MONTHLY",
                "status": "DRAFT",
                "metadata": {"created_by_id": 9999}
            }
        )

        # Sales user (OWN scope)
        self.client.force_authenticate(user=self.sales_user)
        res_sales = self.client.get('/api/v1/billing/audit/')
        sales_results = res_sales.data if isinstance(res_sales.data, list) else res_sales.data.get('results', [])
        sub_ids = [r['subscription'] for r in sales_results]
        self.assertIn(self.subscription1.id, sub_ids)
        self.assertNotIn(other_sub.id, sub_ids)

        # Admin user (ALL scope)
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get('/api/v1/billing/audit/')
        admin_results = res_admin.data if isinstance(res_admin.data, list) else res_admin.data.get('results', [])
        admin_sub_ids = [r['subscription'] for r in admin_results]
        self.assertIn(self.subscription1.id, admin_sub_ids)
        self.assertIn(other_sub.id, admin_sub_ids)

    def test_sensitive_metadata_sanitization(self):
        """16. BillingAuditService recursively scrubs sensitive keys from audit logs."""
        raw_metadata = {
            "token": "tok_123456789",
            "password": "supersecretpassword",
            "cvv": "123",
            "card_number": "4242424242424242",
            "safe_field": "visible_value",
            "nested": {
                "secret_key": "sk_test_999",
                "amount": Decimal("50.00")
            }
        }
        sanitized = BillingAuditService._sanitize_metadata(raw_metadata)

        self.assertEqual(sanitized['token'], '[REDACTED]')
        self.assertEqual(sanitized['password'], '[REDACTED]')
        self.assertEqual(sanitized['cvv'], '[REDACTED]')
        self.assertEqual(sanitized['card_number'], '[REDACTED]')
        self.assertEqual(sanitized['safe_field'], 'visible_value')
        self.assertEqual(sanitized['nested']['secret_key'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['amount'], '50.00')

    # =========================================================================
    # 4. UNIFIED ACTIVITY FEED & ORDERING
    # =========================================================================

    def test_unified_activity_feed_endpoint(self):
        """17. GET /api/v1/billing/subscriptions/<id>/audit-logs/ returns combined chronological feed."""
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        # Create ChangeLog
        SubscriptionChangeLog.objects.create(
            subscription=self.subscription1,
            change_type="ADD_ITEM",
            details={"reason": "Added add-on"},
            proration_amount=Decimal("20.00"),
            effective_date=date.today()
        )

        # Create DunningLog
        DunningLog.objects.create(
            subscription=self.subscription1,
            attempt_number=1,
            status="FAILED",
            error_code="CARD_EXPIRED",
            error_message="Card expired"
        )

        self.client.force_authenticate(user=self.admin_user)
        res = self.client.get(f'/api/v1/billing/subscriptions/{self.subscription1.id}/audit-logs/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        data = res.data
        self.assertGreaterEqual(len(data), 3)

        categories = {item['category'] for item in data}
        self.assertIn('LIFECYCLE', categories)
        self.assertIn('AMENDMENT', categories)
        self.assertIn('DUNNING', categories)

    def test_audit_logs_category_filtering(self):
        """18. Category query parameter filters feed to only matching categories."""
        SubscriptionStateMachineService.transition(subscription=self.subscription1, to_status="LIVE", user=self.admin_user, reason="Activation")

        SubscriptionChangeLog.objects.create(
            subscription=self.subscription1,
            change_type="ADD_ITEM",
            details={"reason": "Added add-on"},
            proration_amount=Decimal("20.00"),
            effective_date=date.today()
        )

        self.client.force_authenticate(user=self.admin_user)
        
        # Filter by AMENDMENT
        res_amend = self.client.get(f'/api/v1/billing/subscriptions/{self.subscription1.id}/audit-logs/?category=AMENDMENT')
        self.assertEqual(res_amend.status_code, status.HTTP_200_OK)
        for item in res_amend.data:
            self.assertEqual(item['category'], 'AMENDMENT')
        self.assertTrue(any(item['category'] == 'AMENDMENT' for item in res_amend.data))
        self.assertFalse(any(item['category'] == 'LIFECYCLE' for item in res_amend.data))

        # Filter by LIFECYCLE
        res_life = self.client.get(f'/api/v1/billing/subscriptions/{self.subscription1.id}/audit-logs/?category=LIFECYCLE')
        self.assertEqual(res_life.status_code, status.HTTP_200_OK)
        for item in res_life.data:
            self.assertEqual(item['category'], 'LIFECYCLE')
        self.assertTrue(any(item['category'] == 'LIFECYCLE' for item in res_life.data))
        self.assertFalse(any(item['category'] == 'AMENDMENT' for item in res_life.data))

    def test_transactional_rollback_safety(self):
        """19. If a domain transaction rolls back, no audit records are committed."""
        count_before = SubscriptionAuditLog.objects.count()

        try:
            with transaction.atomic():
                BillingAuditService.log_subscription_lifecycle(
                    subscription=self.subscription1,
                    action="SHOULD_ROLL_BACK",
                    actor=self.admin_user,
                    reason="Test rollback"
                )
                raise RuntimeError("Simulated transaction failure")
        except RuntimeError:
            pass

        count_after = SubscriptionAuditLog.objects.count()
        self.assertEqual(count_before, count_after)
