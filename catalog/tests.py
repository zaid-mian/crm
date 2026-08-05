from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.core.exceptions import ValidationError
from catalog.models import Product, Module, PricingPlan, PlanModule, Service, ServiceFeature, Discount

class CatalogModelIntegrityTest(TestCase):
    def setUp(self):
        # Create base product and service
        self.product = Product.objects.create(
            name="Sales CRM",
            slug="sales-crm",
            description="CRM SaaS module"
        )
        self.service = Service.objects.create(
            name="Professional Setup",
            slug="professional-setup",
            short_description="Setup consult"
        )
        
        # Modules
        self.module_leads = Module.objects.create(
            product=self.product,
            name="Lead Management",
            code="lead_mgmt"
        )
        self.module_reports = Module.objects.create(
            product=self.product,
            name="Reports",
            code="reports"
        )

        # Base Pricing Plans
        self.plan_product = PricingPlan.objects.create(
            product=self.product,
            name="Starter Plan",
            price=20.00,
            billing_cycle="monthly"
        )
        self.plan_service = PricingPlan.objects.create(
            service=self.service,
            name="Consulting Plan",
            price=150.00,
            billing_cycle="one_time"
        )

    def test_plan_exclusivity(self):
        """A pricing plan must be linked to either a Product or a Service, not both or neither."""
        # Neither Product nor Service
        invalid_plan = PricingPlan(name="Orphan Plan", price=10.00, billing_cycle="monthly")
        with self.assertRaises(ValidationError):
            invalid_plan.full_clean()

        # Both Product and Service
        invalid_plan2 = PricingPlan(
            product=self.product,
            service=self.service,
            name="Double Link Plan",
            price=10.00,
            billing_cycle="monthly"
        )
        with self.assertRaises(ValidationError):
            invalid_plan2.full_clean()

    def test_pricing_plan_name_uniqueness(self):
        """Pricing plan name must be unique within product/service scope."""
        # Duplicate name under same Product
        duplicate_plan = PricingPlan(
            product=self.product,
            name="Starter Plan",
            price=30.00,
            billing_cycle="monthly"
        )
        with self.assertRaises(ValidationError):
            duplicate_plan.full_clean()

        # Same name but under Service (allowed)
        allowed_plan = PricingPlan(
            service=self.service,
            name="Starter Plan",
            price=30.00,
            billing_cycle="monthly"
        )
        # Should not raise validation error
        allowed_plan.full_clean()
        allowed_plan.save()

    def test_plan_module_cross_product_validation(self):
        """A plan module can only link a pricing plan and a module belonging to the same product."""
        # Second product
        product2 = Product.objects.create(name="HRM", slug="hrm")
        module_hrm = Module.objects.create(product=product2, name="Leave Tracker", code="leaves")

        # Starter Plan belongs to Sales CRM. Linking to HRM Module should fail.
        invalid_link = PlanModule(plan=self.plan_product, module=module_hrm)
        with self.assertRaises(ValidationError):
            invalid_link.full_clean()

    def test_discount_bounds_percentage(self):
        """Percentage discounts must be between 0 and 100."""
        invalid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Invalid %",
            discount_type="percentage",
            value=120.00,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount.full_clean()

        invalid_discount2 = Discount(
            pricing_plan=self.plan_product,
            name="Negative %",
            discount_type="percentage",
            value=-10.00,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount2.full_clean()

    def test_discount_bounds_fixed(self):
        """Fixed discounts must be greater than 0 and not exceed plan price."""
        # Value > plan price
        invalid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Over plan price",
            discount_type="fixed",
            value=30.00,  # plan price is 20.00
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount.full_clean()

        # Value <= 0
        invalid_discount2 = Discount(
            pricing_plan=self.plan_product,
            name="Negative Fixed",
            discount_type="fixed",
            value=-5.00,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount2.full_clean()

    def test_discount_date_chronology(self):
        """Discount start date must be before end date."""
        now = timezone.now()
        invalid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Time traveler",
            discount_type="percentage",
            value=10.00,
            start_date=now + timedelta(days=2),
            end_date=now,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount.full_clean()

    def test_discount_overlap_constraint(self):
        """Only one active discount can overlap in a pricing plan."""
        now = timezone.now()
        # Active discount 1 (Starts now, ends in 5 days)
        Discount.objects.create(
            pricing_plan=self.plan_product,
            name="Summer Sale",
            discount_type="percentage",
            value=10.00,
            start_date=now,
            end_date=now + timedelta(days=5),
            is_active=True
        )

        # Overlapping active discount 2 (Starts in 2 days, ends in 7 days)
        overlapping_discount = Discount(
            pricing_plan=self.plan_product,
            name="Flash Sale",
            discount_type="percentage",
            value=15.00,
            start_date=now + timedelta(days=2),
            end_date=now + timedelta(days=7),
            is_active=True
        )
        with self.assertRaises(ValidationError):
            overlapping_discount.full_clean()

        # Non-overlapping active discount 3 (Starts in 6 days, ends in 10 days)
        valid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Autumn Sale",
            discount_type="percentage",
            value=20.00,
            start_date=now + timedelta(days=6),
            end_date=now + timedelta(days=10),
            is_active=True
        )
        # Should clean successfully
        valid_discount.full_clean()
        valid_discount.save()
