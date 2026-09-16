import calendar
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
from billing.models import (
    BillingCustomer,
    Subscription,
    SubscriptionItem,
    AddOn,
    SubscriptionAuditLog,
    SubscriptionChangeLog,
    Invoice,
    CreditNote,
    DebitNote,
)
from billing.services import (
    ProrationService,
    SubscriptionAmendmentService,
    SubscriptionItemService,
    InvoicingEngineService,
)
from roles.models import Role, RolePermission, CRMResource

from billing.tests.helpers import setup_billing_test_permissions

User = get_user_model()


class SubscriptionProrationTestCase(APITestCase):
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
        self.admin_user = User.objects.create_user(username='proration_admin', email='admin@org1.com', password='password123')
        self.admin_user.profile.organization = self.org1
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()

        self.sales1 = User.objects.create_user(username='proration_sales1', email='sales1@org1.com', password='password123')
        self.sales1.profile.organization = self.org1
        self.sales1.profile.role = self.sales_role
        self.sales1.profile.save()

        self.sales2 = User.objects.create_user(username='proration_sales2', email='sales2@org1.com', password='password123')
        self.sales2.profile.organization = self.org1
        self.sales2.profile.role = self.sales_role
        self.sales2.profile.save()

        self.user_no_perm = User.objects.create_user(username='proration_noperm', email='noperm@org1.com', password='password123')
        self.user_no_perm.profile.organization = self.org1
        self.user_no_perm.profile.role = self.no_perm_role
        self.user_no_perm.profile.save()

        self.org2_user = User.objects.create_user(username='proration_org2_user', email='user@org2.com', password='password123')
        self.org2_user.profile.organization = self.org2
        self.org2_user.profile.role = self.admin_role
        self.org2_user.profile.save()

        # 5. Customers
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-12001',
            name='Acme Corp',
            email='billing@acme.com',
            currency='USD',
            metadata={'created_by_id': self.sales1.id}
        )

        self.customer2 = BillingCustomer.objects.create(
            organization=self.org2,
            customer_number='CUST-12002',
            name='Beta Corp',
            email='billing@beta.com',
            currency='USD',
            metadata={'created_by_id': self.org2_user.id}
        )

        # 6. Catalog Products, Plans & Addons
        self.product = Product.objects.create(name='AdaptCRM Pro', is_active=True)

        self.starter_plan = PricingPlan.objects.create(
            product=self.product,
            name='Starter Plan',
            price=Decimal('100.00'),
            currency='USD',
            billing_cycle='monthly',
            is_active=True
        )

        self.pro_plan = PricingPlan.objects.create(
            product=self.product,
            name='Professional Plan',
            price=Decimal('200.00'),
            currency='USD',
            billing_cycle='monthly',
            is_active=True
        )

        self.enterprise_plan = PricingPlan.objects.create(
            product=self.product,
            name='Enterprise Plan',
            price=Decimal('500.00'),
            currency='USD',
            billing_cycle='monthly',
            is_active=True
        )

        self.annual_plan = PricingPlan.objects.create(
            product=self.product,
            name='Annual Starter',
            price=Decimal('1200.00'),
            currency='USD',
            billing_cycle='yearly',
            is_active=True
        )

        self.addon_storage = AddOn.objects.create(
            product=self.product,
            name='Extra Storage 10GB',
            code='addon-storage-10gb',
            price=Decimal('10.00'),
            currency='USD',
            billing_cycle='monthly',
            max_quantity=10,
            is_active=True
        )

        self.addon_seats = AddOn.objects.create(
            product=self.product,
            name='Additional User Seat',
            code='addon-user-seat',
            price=Decimal('25.00'),
            currency='USD',
            billing_cycle='monthly',
            max_quantity=50,
            is_active=True
        )

    def _create_live_subscription(self, plan, term_start=None, term_end=None, customer=None, created_by_id=None):
        if not customer:
            customer = self.customer1
        if not term_start:
            term_start = date(2026, 9, 1)
        if not term_end:
            term_end = date(2026, 9, 30)

        sub = Subscription.objects.create(
            subscription_number=f'SUB-12{Subscription.objects.count():03d}',
            customer=customer,
            status='LIVE',
            currency='USD',
            collection_method='CHARGE_AUTOMATIC',
            current_term_start=term_start,
            current_term_end=term_end,
            next_billing_date=term_end + timedelta(days=1),
            metadata={'created_by_id': created_by_id} if created_by_id else {}
        )

        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=plan,
            quantity=1,
            unit_price=plan.price,
            discount_amount=Decimal('0.00'),
            start_date=term_start,
            end_date=term_end
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)
        sub.refresh_from_db()
        return sub

    # ----------------------------------------------------
    # 1. Mid-cycle Plan Upgrade
    # ----------------------------------------------------
    def test_mid_cycle_plan_upgrade(self):
        # 30-day term: Sep 1 to Sep 30. Effective Sep 15.
        # D_total = 30. D_consumed = 14. D_remaining = 16.
        # Starter ($100): Credit = (100 / 30) * 16 = 53.3333 -> 53.33
        # Pro ($200): Charge = (200 / 30) * 16 = 106.6666 -> 106.67
        # Net = 106.67 - 53.33 = 53.34
        sub = self._create_live_subscription(self.starter_plan)

        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 9, 15)
        )

        self.assertEqual(proration['term_days_total'], 30)
        self.assertEqual(proration['term_days_consumed'], 14)
        self.assertEqual(proration['term_days_remaining'], 16)
        self.assertEqual(proration['total_credit'], '53.33')
        self.assertEqual(proration['total_charge'], '106.67')
        self.assertEqual(proration['net_amount'], '53.34')
        self.assertTrue(proration['is_upgrade'])

        # Commit amendment
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            reason="Upgrading to Pro tier",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )

        sub.refresh_from_db()
        self.assertEqual(sub.cached_mrr, Decimal('200.00'))
        self.assertEqual(sub.items.filter(item_type='PLAN').count(), 1)
        self.assertEqual(sub.items.first().plan, self.pro_plan)
        self.assertIsNotNone(res['invoice'])
        self.assertEqual(res['invoice'].total_amount, Decimal('53.34'))
        self.assertEqual(res['invoice'].status, 'POSTED')

    # ----------------------------------------------------
    # 2. Mid-cycle Plan Downgrade
    # ----------------------------------------------------
    def test_mid_cycle_plan_downgrade(self):
        # 30-day term: Pro ($200) -> Starter ($100). Effective Sep 15.
        # Credit = 106.67, Charge = 53.33, Net = -53.34
        sub = self._create_live_subscription(self.pro_plan)

        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.starter_plan.id,
            reason="Downgrading to Starter tier",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )

        sub.refresh_from_db()
        self.assertEqual(sub.cached_mrr, Decimal('100.00'))
        self.assertEqual(sub.items.first().plan, self.starter_plan)
        # Downgrade must NOT create an invoice, CreditNote, or DebitNote
        self.assertIsNone(res['invoice'])
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 0)
        self.assertEqual(CreditNote.objects.count(), 0)
        self.assertEqual(DebitNote.objects.count(), 0)

        # Check SubscriptionChangeLog
        change_log = SubscriptionChangeLog.objects.filter(subscription=sub).first()
        self.assertIsNotNone(change_log)
        self.assertEqual(change_log.change_type, 'PLAN_DOWNGRADE')
        self.assertEqual(change_log.proration_amount, Decimal('-53.34'))

    # ----------------------------------------------------
    # 3. Annual Subscription Proration
    # ----------------------------------------------------
    def test_annual_subscription_proration(self):
        # Jan 1 2026 to Dec 31 2026 (365 days).
        # Effective July 2 2026 (Day 183 of 365, D_consumed = 182, D_remaining = 183).
        sub = self._create_live_subscription(
            self.annual_plan,
            term_start=date(2026, 1, 1),
            term_end=date(2026, 12, 31)
        )
        # Create annual pro plan ($2400)
        annual_pro = PricingPlan.objects.create(
            product=self.product,
            name='Annual Pro',
            price=Decimal('2400.00'),
            billing_cycle='yearly',
            is_active=True
        )

        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=annual_pro.id,
            effective_date=date(2026, 7, 2)
        )

        self.assertEqual(proration['term_days_total'], 365)
        self.assertEqual(proration['term_days_consumed'], 182)
        self.assertEqual(proration['term_days_remaining'], 183)

        # 1200 / 365 * 183 = 601.6438 -> 601.64 credit
        # 2400 / 365 * 183 = 1203.2876 -> 1203.29 charge
        # Net = 1203.29 - 601.64 = 601.65
        self.assertEqual(proration['total_credit'], '601.64')
        self.assertEqual(proration['total_charge'], '1203.29')
        self.assertEqual(proration['net_amount'], '601.65')

    # ----------------------------------------------------
    # 4. Jan 31 Month-End Handling
    # ----------------------------------------------------
    def test_january_month_end_handling(self):
        # Jan 1 to Jan 31 (31 days). Effective Jan 31.
        # D_total = 31. D_consumed = 30. D_remaining = 1.
        sub = self._create_live_subscription(
            self.starter_plan,
            term_start=date(2026, 1, 1),
            term_end=date(2026, 1, 31)
        )
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 1, 31)
        )
        self.assertEqual(proration['term_days_total'], 31)
        self.assertEqual(proration['term_days_remaining'], 1)
        # Credit: 100 / 31 * 1 = 3.23. Charge: 200 / 31 * 1 = 6.45. Net = 3.22.
        self.assertEqual(proration['total_credit'], '3.23')
        self.assertEqual(proration['total_charge'], '6.45')
        self.assertEqual(proration['net_amount'], '3.22')

    # ----------------------------------------------------
    # 5. Feb 28 Non-Leap Year Handling
    # ----------------------------------------------------
    def test_february_non_leap_year_handling(self):
        # Feb 1 2025 to Feb 28 2025 (28 days). Effective Feb 15 2025.
        sub = self._create_live_subscription(
            self.starter_plan,
            term_start=date(2025, 2, 1),
            term_end=date(2025, 2, 28)
        )
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2025, 2, 15)
        )
        self.assertEqual(proration['term_days_total'], 28)
        self.assertEqual(proration['term_days_consumed'], 14)
        self.assertEqual(proration['term_days_remaining'], 14)

    # ----------------------------------------------------
    # 6. Feb 29 Leap Year Handling
    # ----------------------------------------------------
    def test_february_leap_year_handling(self):
        # Feb 1 2028 to Feb 29 2028 (29 days in leap year 2028).
        sub = self._create_live_subscription(
            self.starter_plan,
            term_start=date(2028, 2, 1),
            term_end=date(2028, 2, 29)
        )
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2028, 2, 15)
        )
        self.assertEqual(proration['term_days_total'], 29)
        self.assertEqual(proration['term_days_consumed'], 14)
        self.assertEqual(proration['term_days_remaining'], 15)

    # ----------------------------------------------------
    # 7. D_remaining = 1 (effective_date == current_term_end)
    # ----------------------------------------------------
    def test_effective_date_at_term_end(self):
        sub = self._create_live_subscription(self.starter_plan)
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 9, 30)
        )
        self.assertEqual(proration['term_days_remaining'], 1)

    # ----------------------------------------------------
    # 8. D_remaining = D_total (effective_date == current_term_start)
    # ----------------------------------------------------
    def test_effective_date_at_term_start(self):
        sub = self._create_live_subscription(self.starter_plan)
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 9, 1)
        )
        self.assertEqual(proration['term_days_remaining'], 30)
        self.assertEqual(proration['term_days_consumed'], 0)
        self.assertEqual(proration['total_credit'], '100.00')
        self.assertEqual(proration['total_charge'], '200.00')
        self.assertEqual(proration['net_amount'], '100.00')

    # ----------------------------------------------------
    # 9. ROUND_HALF_UP Precision Behavior
    # ----------------------------------------------------
    def test_round_half_up_precision(self):
        # 100 / 30 * 16 = 53.333333 -> 53.33
        # 200 / 30 * 16 = 106.666666 -> 106.67
        sub = self._create_live_subscription(self.starter_plan)
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 9, 15)
        )
        self.assertEqual(proration['total_credit'], '53.33')
        self.assertEqual(proration['total_charge'], '106.67')

    # ----------------------------------------------------
    # 10 & 11. Historical Snapshot Pricing Integrity
    # ----------------------------------------------------
    def test_historical_snapshot_pricing_preserved(self):
        # Subscription created when Starter Plan was $100.
        sub = self._create_live_subscription(self.starter_plan)

        # Later, catalog price of Starter Plan is increased to $150.
        self.starter_plan.price = Decimal('150.00')
        self.starter_plan.save()

        # Proration calculation must use snapshot price ($100), not catalog price ($150)
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 9, 15)
        )
        self.assertEqual(proration['total_credit'], '53.33')

    # ----------------------------------------------------
    # 12. Exactly One Active PLAN After Replacement
    # ----------------------------------------------------
    def test_exactly_one_active_plan_after_amendment(self):
        sub = self._create_live_subscription(self.starter_plan)
        SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            reason="Plan upgrade",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        sub.refresh_from_db()
        self.assertEqual(sub.items.filter(item_type='PLAN').count(), 1)
        self.assertEqual(sub.items.first().plan, self.pro_plan)

    # ----------------------------------------------------
    # 13. Add-on ADD Action
    # ----------------------------------------------------
    def test_addon_add_action(self):
        # Add 2 storage addons ($10 each = $20 term cost) on Sep 15 (16 days rem).
        # Charge: (20 / 30) * 16 = 10.6666 -> 10.67
        sub = self._create_live_subscription(self.starter_plan)
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            add_ons=[{"addon_id": self.addon_storage.id, "quantity": 2, "action": "ADD"}],
            reason="Adding 2 storage units",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        sub.refresh_from_db()
        self.assertEqual(sub.items.filter(item_type='ADDON').count(), 1)
        addon_item = sub.items.filter(item_type='ADDON').first()
        self.assertEqual(addon_item.quantity, 2)
        self.assertEqual(addon_item.unit_price, Decimal('10.00'))
        self.assertEqual(sub.cached_mrr, Decimal('120.00'))  # $100 plan + 2 * $10
        self.assertEqual(res['invoice'].total_amount, Decimal('10.67'))

    # ----------------------------------------------------
    # 14. Add-on CHANGE Action
    # ----------------------------------------------------
    def test_addon_change_action(self):
        # Initial subscription has 2 storage addons ($20).
        sub = self._create_live_subscription(self.starter_plan)
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='ADDON',
            addon=self.addon_storage,
            quantity=2,
            unit_price=Decimal('10.00'),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        # Change quantity to 5 on Sep 15.
        # Credit old (2): 20 / 30 * 16 = 10.67
        # Charge new (5): 50 / 30 * 16 = 26.67
        # Net = 26.67 - 10.67 = 16.00
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            add_ons=[{"addon_id": self.addon_storage.id, "quantity": 5, "action": "CHANGE"}],
            reason="Increasing storage to 5 units",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        sub.refresh_from_db()
        self.assertEqual(sub.items.filter(item_type='ADDON').count(), 1)
        self.assertEqual(sub.items.filter(item_type='ADDON').first().quantity, 5)
        self.assertEqual(sub.cached_mrr, Decimal('150.00'))
        self.assertEqual(res['invoice'].total_amount, Decimal('16.00'))

    # ----------------------------------------------------
    # 15. Add-on REMOVE Action
    # ----------------------------------------------------
    def test_addon_remove_action(self):
        sub = self._create_live_subscription(self.starter_plan)
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='ADDON',
            addon=self.addon_storage,
            quantity=2,
            unit_price=Decimal('10.00'),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            add_ons=[{"addon_id": self.addon_storage.id, "action": "REMOVE"}],
            reason="Removing storage addon",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        sub.refresh_from_db()
        self.assertEqual(sub.items.filter(item_type='ADDON').count(), 0)
        self.assertEqual(sub.cached_mrr, Decimal('100.00'))
        self.assertIsNone(res['invoice'])

    # ----------------------------------------------------
    # 16. Add-on Max Quantity Enforcement
    # ----------------------------------------------------
    def test_addon_max_quantity_enforced(self):
        sub = self._create_live_subscription(self.starter_plan)
        # addon_storage has max_quantity=10. Requesting 15 should fail.
        with self.assertRaises(ValidationError):
            SubscriptionAmendmentService.apply_amendment(
                subscription=sub,
                add_ons=[{"addon_id": self.addon_storage.id, "quantity": 15, "action": "ADD"}],
                reason="Exceeding cap",
                user=self.admin_user
            )

    # ----------------------------------------------------
    # 17. Multiple Add-ons in Single Amendment
    # ----------------------------------------------------
    def test_multiple_addons_amendment(self):
        sub = self._create_live_subscription(self.starter_plan)
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            add_ons=[
                {"addon_id": self.addon_storage.id, "quantity": 2, "action": "ADD"},
                {"addon_id": self.addon_seats.id, "quantity": 1, "action": "ADD"}
            ],
            reason="Upgrading and adding storage & seats",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        sub.refresh_from_db()
        self.assertEqual(sub.items.filter(item_type='PLAN').count(), 1)
        self.assertEqual(sub.items.filter(item_type='ADDON').count(), 2)
        # MRR: Pro ($200) + 2*10 ($20) + 1*25 ($25) = $245.00
        self.assertEqual(sub.cached_mrr, Decimal('245.00'))
        self.assertIsNotNone(res['invoice'])

    # ----------------------------------------------------
    # 18. Add-on Co-Termination Semantics
    # ----------------------------------------------------
    def test_addon_co_termination_dates(self):
        sub = self._create_live_subscription(self.starter_plan)
        SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            add_ons=[{"addon_id": self.addon_storage.id, "quantity": 1, "action": "ADD"}],
            reason="Co-term test",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        sub.refresh_from_db()
        addon_item = sub.items.filter(item_type='ADDON').first()
        self.assertEqual(addon_item.start_date, date(2026, 9, 15))
        self.assertEqual(addon_item.end_date, sub.current_term_end)

    # ----------------------------------------------------
    # 19. Preview Has Zero Database Mutations
    # ----------------------------------------------------
    def test_preview_has_zero_db_mutations(self):
        sub = self._create_live_subscription(self.starter_plan)
        items_count_before = SubscriptionItem.objects.count()
        invoices_count_before = Invoice.objects.count()
        audit_count_before = SubscriptionAuditLog.objects.count()
        change_count_before = SubscriptionChangeLog.objects.count()

        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post(
            f"/api/v1/billing/subscriptions/{sub.id}/preview-amend/",
            {
                "new_plan_id": self.pro_plan.id,
                "add_ons": [{"addon_id": self.addon_storage.id, "quantity": 2, "action": "ADD"}],
                "effective_date": "2026-09-15"
            },
            format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(SubscriptionItem.objects.count(), items_count_before)
        self.assertEqual(Invoice.objects.count(), invoices_count_before)
        self.assertEqual(SubscriptionAuditLog.objects.count(), audit_count_before)
        self.assertEqual(SubscriptionChangeLog.objects.count(), change_count_before)

    # ----------------------------------------------------
    # 20. Commit Atomicity
    # ----------------------------------------------------
    def test_commit_atomicity(self):
        sub = self._create_live_subscription(self.starter_plan)
        # Provide invalid reason (empty) -> must fail and leave DB unchanged
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post(
            f"/api/v1/billing/subscriptions/{sub.id}/amend/",
            {
                "new_plan_id": self.pro_plan.id,
                "reason": "   "
            },
            format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        sub.refresh_from_db()
        self.assertEqual(sub.items.first().plan, self.starter_plan)

    # ----------------------------------------------------
    # 21. Positive Proration Invoice Created
    # ----------------------------------------------------
    def test_positive_proration_invoice_created(self):
        sub = self._create_live_subscription(self.starter_plan)
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            reason="Upgrade",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        self.assertIsNotNone(res['invoice'])
        self.assertEqual(res['invoice'].status, 'POSTED')
        self.assertGreater(res['invoice'].total_amount, Decimal('0.00'))

    # ----------------------------------------------------
    # 22. Zero Proration Amendment (No Invoice)
    # ----------------------------------------------------
    def test_zero_proration_creates_no_invoice(self):
        # Create equal price plan ($100)
        lateral_plan = PricingPlan.objects.create(
            product=self.product,
            name='Starter Lateral',
            price=Decimal('100.00'),
            billing_cycle='monthly',
            is_active=True
        )
        sub = self._create_live_subscription(self.starter_plan)
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=lateral_plan.id,
            reason="Lateral plan switch",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        self.assertIsNone(res['invoice'])
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 0)
        # Audit and change logs must still be created
        self.assertEqual(SubscriptionAuditLog.objects.filter(subscription=sub).count(), 1)
        self.assertEqual(SubscriptionChangeLog.objects.filter(subscription=sub).count(), 1)

    # ----------------------------------------------------
    # 23 & 24. Negative Proration Invariants
    # ----------------------------------------------------
    def test_negative_proration_creates_no_negative_invoice_or_credit_note(self):
        sub = self._create_live_subscription(self.pro_plan)
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.starter_plan.id,
            reason="Downgrade",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        self.assertIsNone(res['invoice'])
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(CreditNote.objects.count(), 0)

    # ----------------------------------------------------
    # 25 to 30. Blocked Subscription States
    # ----------------------------------------------------
    def test_blocked_subscription_states(self):
        blocked_statuses = ['PAUSED', 'NON_RENEWING', 'PAST_DUE', 'UNPAID', 'CANCELLED', 'DRAFT', 'FUTURE', 'TRIAL']
        for st in blocked_statuses:
            sub = self._create_live_subscription(self.starter_plan)
            sub.status = st
            sub.save()

            with self.assertRaises(ValidationError):
                ProrationService.calculate_proration(
                    subscription=sub,
                    new_plan_id=self.pro_plan.id
                )

            with self.assertRaises(ValidationError):
                SubscriptionAmendmentService.apply_amendment(
                    subscription=sub,
                    new_plan_id=self.pro_plan.id,
                    reason="Test blocked state",
                    user=self.admin_user
                )

    # ----------------------------------------------------
    # 31. RBAC ALL Permitted
    # ----------------------------------------------------
    def test_rbac_all_permitted(self):
        sub = self._create_live_subscription(self.starter_plan)
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post(
            f"/api/v1/billing/subscriptions/{sub.id}/preview-amend/",
            {"new_plan_id": self.pro_plan.id},
            format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ----------------------------------------------------
    # 32. RBAC OWN Permitted on Owned Subscription
    # ----------------------------------------------------
    def test_rbac_own_permitted_on_owned(self):
        sub = self._create_live_subscription(self.starter_plan, created_by_id=self.sales1.id)
        self.client.force_authenticate(user=self.sales1)
        resp = self.client.post(
            f"/api/v1/billing/subscriptions/{sub.id}/preview-amend/",
            {"new_plan_id": self.pro_plan.id},
            format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ----------------------------------------------------
    # 33. RBAC OWN Denied (404) on Unowned Subscription
    # ----------------------------------------------------
    def test_rbac_own_denied_on_unowned(self):
        sub = self._create_live_subscription(self.starter_plan, created_by_id=self.sales2.id)
        self.client.force_authenticate(user=self.sales1)
        resp = self.client.post(
            f"/api/v1/billing/subscriptions/{sub.id}/preview-amend/",
            {"new_plan_id": self.pro_plan.id},
            format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # ----------------------------------------------------
    # 34. RBAC NONE Denied (403)
    # ----------------------------------------------------
    def test_rbac_none_denied(self):
        sub = self._create_live_subscription(self.starter_plan)
        self.client.force_authenticate(user=self.user_no_perm)
        resp = self.client.post(
            f"/api/v1/billing/subscriptions/{sub.id}/preview-amend/",
            {"new_plan_id": self.pro_plan.id},
            format="json"
        )
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    # ----------------------------------------------------
    # 35. Cross-Tenant Isolation Blocked (404)
    # ----------------------------------------------------
    def test_cross_tenant_isolation(self):
        sub_org2 = self._create_live_subscription(self.starter_plan, customer=self.customer2)
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post(
            f"/api/v1/billing/subscriptions/{sub_org2.id}/preview-amend/",
            {"new_plan_id": self.pro_plan.id},
            format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # ----------------------------------------------------
    # 36. Mandatory Reason Required on Commit
    # ----------------------------------------------------
    def test_mandatory_reason_required_on_commit(self):
        sub = self._create_live_subscription(self.starter_plan)
        with self.assertRaises(ValidationError):
            SubscriptionAmendmentService.apply_amendment(
                subscription=sub,
                new_plan_id=self.pro_plan.id,
                reason="",
                user=self.admin_user
            )

    # ----------------------------------------------------
    # 37. Invalid Effective Date Rejected
    # ----------------------------------------------------
    def test_invalid_effective_date_rejected(self):
        sub = self._create_live_subscription(self.starter_plan)  # Sep 1 to Sep 30
        # Date before start
        with self.assertRaises(ValidationError):
            ProrationService.calculate_proration(
                subscription=sub,
                new_plan_id=self.pro_plan.id,
                effective_date=date(2026, 8, 31)
            )
        # Date after end
        with self.assertRaises(ValidationError):
            ProrationService.calculate_proration(
                subscription=sub,
                new_plan_id=self.pro_plan.id,
                effective_date=date(2026, 10, 1)
            )

    # ----------------------------------------------------
    # 38. Effective Date == current_term_end Permitted
    # ----------------------------------------------------
    def test_effective_date_at_term_end_permitted(self):
        sub = self._create_live_subscription(self.starter_plan)
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 9, 30)
        )
        self.assertEqual(proration['term_days_remaining'], 1)

    # ----------------------------------------------------
    # 39. No-op Amendment Rejected
    # ----------------------------------------------------
    def test_no_op_amendment_rejected(self):
        sub = self._create_live_subscription(self.starter_plan)
        with self.assertRaises(ValidationError):
            ProrationService.calculate_proration(
                subscription=sub,
                new_plan_id=self.starter_plan.id
            )

    # ----------------------------------------------------
    # 40. Commit Recalculates Proration Authoritatively
    # ----------------------------------------------------
    def test_commit_recalculates_on_server(self):
        sub = self._create_live_subscription(self.starter_plan)
        # Client requests preview at current pro_plan price ($200)
        proration = ProrationService.calculate_proration(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            effective_date=date(2026, 9, 15)
        )
        self.assertEqual(proration['net_amount'], '53.34')

        # Price of pro plan is updated in catalog to $250 before commit
        self.pro_plan.price = Decimal('250.00')
        self.pro_plan.save()

        # Commit recalculates authoritatively using $250
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            reason="Upgrade after price change",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        # Charge: 250 / 30 * 16 = 133.33, Credit = 53.33, Net = 80.00
        self.assertEqual(res['invoice'].total_amount, Decimal('80.00'))

    # ----------------------------------------------------
    # 41. Repeated Amendment Invoice Idempotency
    # ----------------------------------------------------
    def test_repeated_amendment_invoice_idempotency(self):
        sub = self._create_live_subscription(self.starter_plan)
        res1 = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            reason="First upgrade call",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        inv1_id = res1['invoice'].id

        # Simulating invoice generation call with same proration result & date
        inv2 = InvoicingEngineService.generate_amendment_proration_invoice(
            subscription=sub,
            proration_result=res1['proration'],
            effective_date=date(2026, 9, 15)
        )
        self.assertEqual(inv1_id, inv2.id)
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 1)

    # ----------------------------------------------------
    # 42. Distinct Invoices for Same-Day Same-Amount Add-on Amendments
    # ----------------------------------------------------
    def test_different_sameday_addon_amendments_distinct_invoices(self):
        sub = self._create_live_subscription(self.starter_plan)

        addon_feature_a = AddOn.objects.create(
            product=self.product,
            name='Feature Pack A',
            code='addon-feature-a',
            price=Decimal('20.00'),
            currency='USD',
            billing_cycle='monthly',
            max_quantity=10,
            is_active=True
        )
        addon_feature_b = AddOn.objects.create(
            product=self.product,
            name='Feature Pack B',
            code='addon-feature-b',
            price=Decimal('20.00'),
            currency='USD',
            billing_cycle='monthly',
            max_quantity=10,
            is_active=True
        )

        # 1. First amendment: Add Feature A on 2026-09-15 (Net = $10.67)
        res_a = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            add_ons=[{'addon_id': addon_feature_a.id, 'action': 'ADD', 'quantity': 1}],
            reason="Add Feature Pack A",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        inv_a = res_a['invoice']
        self.assertIsNotNone(inv_a)
        self.assertEqual(inv_a.total_amount, Decimal('10.67'))

        # 2. Second amendment on same day: Add Feature B (Net = $10.67)
        sub.refresh_from_db()
        res_b = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            add_ons=[{'addon_id': addon_feature_b.id, 'action': 'ADD', 'quantity': 1}],
            reason="Add Feature Pack B",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        inv_b = res_b['invoice']
        self.assertIsNotNone(inv_b)
        self.assertEqual(inv_b.total_amount, Decimal('10.67'))

        # Verify two distinct invoices were created without collision
        self.assertNotEqual(inv_a.id, inv_b.id)
        self.assertNotEqual(inv_a.idempotency_key, inv_b.idempotency_key)
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 2)

    # ----------------------------------------------------
    # 43. Combined Plan & Add-on Amendment Idempotency
    # ----------------------------------------------------
    def test_combined_plan_and_addon_amendment_idempotency(self):
        sub = self._create_live_subscription(self.starter_plan)

        # Add initial storage add-on
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='ADDON',
            addon=self.addon_storage,
            quantity=1,
            unit_price=self.addon_storage.price,
            discount_amount=Decimal('0.00'),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        # Apply combined upgrade (Plan to Pro + Storage CHANGE to 3)
        res = SubscriptionAmendmentService.apply_amendment(
            subscription=sub,
            new_plan_id=self.pro_plan.id,
            add_ons=[{'addon_id': self.addon_storage.id, 'action': 'CHANGE', 'quantity': 3}],
            reason="Upgrade tier and expand storage",
            user=self.admin_user,
            effective_date=date(2026, 9, 15)
        )
        inv1 = res['invoice']
        self.assertIsNotNone(inv1)

        # Repeating invoice generation with exact same combined proration payload
        inv2 = InvoicingEngineService.generate_amendment_proration_invoice(
            subscription=sub,
            proration_result=res['proration'],
            effective_date=date(2026, 9, 15)
        )
        self.assertEqual(inv1.id, inv2.id)
        self.assertEqual(inv1.idempotency_key, inv2.idempotency_key)
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 1)

