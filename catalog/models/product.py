import os
from django.db import models
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver

def validate_product_image(file):
    # Limit upload size to 5 MB
    max_size_mb = 5.0
    if file.size > max_size_mb * 1024 * 1024:
        raise ValidationError(f"Maximum upload size is {max_size_mb} MB.")

    # Accept only image formats (jpg, jpeg, png, webp)
    ext = os.path.splitext(file.name)[1].lower()
    valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    if ext not in valid_extensions:
        raise ValidationError("Unsupported file extension. Only JPG, JPEG, PNG, and WEBP are allowed.")

    # Validate image content using Pillow
    from PIL import Image
    try:
        file.seek(0)
        img = Image.open(file)
        img.verify()
        file.seek(0)
    except Exception:
        raise ValidationError("Invalid image file. The uploaded file is corrupt or not a valid image.")


class Product(models.Model):
    name = models.CharField(max_length=255, help_text="Name of the SaaS module/service (e.g. Sales CRM)")
    slug = models.SlugField(unique=True, help_text="Unique slug for URL routing")
    description = models.TextField(blank=True, help_text="Detailed description of the product")
    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True,
        validators=[validate_product_image]
    )
    is_active = models.BooleanField(default=True, db_index=True, help_text="Designates whether this product is active and visible")
    display_order = models.PositiveIntegerField(default=0, db_index=True, help_text="Order in which this product is displayed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.name


@receiver(post_delete, sender=Product)
def delete_product_image_on_delete(sender, instance, **kwargs):
    """Deletes image file from filesystem when corresponding Product object is deleted."""
    if instance.image:
        try:
            if os.path.isfile(instance.image.path):
                os.remove(instance.image.path)
        except ValueError:
            pass


@receiver(pre_save, sender=Product)
def delete_product_image_on_change(sender, instance, **kwargs):
    """Deletes old image file from filesystem when corresponding Product object is updated with a new image."""
    if not instance.pk:
        return False

    try:
        old_image = Product.objects.get(pk=instance.pk).image
    except Product.DoesNotExist:
        return False

    new_image = instance.image
    if old_image and old_image != new_image:
        try:
            if os.path.isfile(old_image.path):
                os.remove(old_image.path)
        except ValueError:
            pass
