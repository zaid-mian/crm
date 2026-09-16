from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError


class AddOn(models.Model):
    BILLING_CYCLE_CHOICES = [
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('one_time', 'One-time'),
    ]

    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='addons',
        help_text="Product this add-on belongs to"
    )
    name = models.CharField(max_length=255, help_text="Name of the add-on item")
    code = models.SlugField(max_length=100, unique=True, help_text="Unique slug code for add-on identification")
    description = models.TextField(blank=True, help_text="Detailed description of the add-on")
    price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Price per unit of the add-on")
    currency = models.CharField(max_length=10, default='USD', help_text="Three-letter currency code")
    billing_cycle = models.CharField(
        max_length=20,
        choices=BILLING_CYCLE_CHOICES,
        default='monthly',
        help_text="Billing frequency for the add-on"
    )
    unit_label = models.CharField(
        max_length=50,
        default='unit',
        help_text="Custom unit label (e.g. 'per seat', 'per 1,000 emails', 'GB')"
    )
    max_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum quantity allowed per subscription if capped"
    )
    is_active = models.BooleanField(default=True, db_index=True, help_text="Designates whether this add-on is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        verbose_name = 'Add-On'
        verbose_name_plural = 'Add-Ons'

    def clean(self):
        if self.price is not None:
            self.price = Decimal(str(self.price)).quantize(Decimal('0.01'))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} - {self.name} ({self.code})"
