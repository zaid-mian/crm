from django.contrib import admin
from .models import Organization, OwnerProfile, RegistrationRequest

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active',)


@admin.register(OwnerProfile)
class OwnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'cnic', 'phone_number', 'country')
    search_fields = ('user__username', 'user__email', 'organization__name', 'cnic')
    list_filter = ('country',)


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('owner_profile', 'status', 'submitted_at', 'reviewed_at')
    search_fields = ('owner_profile__user__username', 'owner_profile__user__email', 'owner_profile__organization__name')
    list_filter = ('status', 'submitted_at')
