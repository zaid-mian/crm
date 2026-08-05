from django.db import models

class Module(models.Model):
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='modules',
        help_text="The product this module belongs to"
    )
    name = models.CharField(max_length=255, help_text="Short name of the module (e.g. Lead Management)")
    code = models.SlugField(help_text="Code identifier for permission checks. Unique per product.")
    description = models.TextField(blank=True, help_text="Detailed description of what this module offers")
    is_active = models.BooleanField(default=True, db_index=True, help_text="Designates whether this module is active")
    display_order = models.PositiveIntegerField(default=0, db_index=True, help_text="Order in which this module is displayed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'code')
        ordering = ['display_order', 'id']

    def __str__(self):
        return f"{self.product.name} - {self.name}"
