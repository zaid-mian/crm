from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from .models import Organization, OwnerProfile, RegistrationRequest

User = get_user_model()

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'logo', 'is_active', 'created_at']
        read_only_fields = ['is_active', 'created_at']


class OwnerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = OwnerProfile
        fields = ['id', 'cnic', 'phone_number', 'country', 'address']


class RegistrationRequestSerializer(serializers.ModelSerializer):
    owner_profile = OwnerProfileSerializer(read_only=True)
    organization_name = serializers.CharField(source='owner_profile.organization.name', read_only=True)
    owner_email = serializers.CharField(source='owner_profile.user.email', read_only=True)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = RegistrationRequest
        fields = [
            'id', 'owner_profile', 'organization_name', 'owner_email', 
            'owner_name', 'status', 'rejection_reason', 'submitted_at', 'reviewed_at'
        ]

    def get_owner_name(self, obj):
        full_name = obj.owner_profile.user.get_full_name()
        return full_name if full_name else obj.owner_profile.user.username


class PlatformSignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    company_name = serializers.CharField(max_length=255)
    cnic = serializers.CharField(max_length=20)
    phone_number = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=100)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    plan_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        email = value.strip().lower()
        user_exists = User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists()
        if user_exists:
            try:
                user_obj = User.objects.get(email=email)
            except User.DoesNotExist:
                user_obj = User.objects.get(username=email)
            
            profile = getattr(user_obj, 'ownerprofile', None)
            if profile:
                reg_req = RegistrationRequest.objects.filter(owner_profile=profile).first()
                if reg_req and reg_req.status == 'rejected':
                    return email
            raise serializers.ValidationError("A user with this email address already exists.")
        return email

    def validate_cnic(self, value):
        import re
        val = value.strip()
        pattern = r'^\d{5}-?\d{7}-?\d{1}$'
        if not re.match(pattern, val):
            raise serializers.ValidationError("CNIC must be 13 digits (dashes optional, e.g. 12345-6789012-3).")
        return val

    def validate_phone_number(self, value):
        import re
        # Normalize: strip dashes and spaces
        val = value.replace('-', '').replace(' ', '').strip()
        pattern = r'^\+?\d{11,15}$'
        if not re.match(pattern, val):
            raise serializers.ValidationError("Phone number must be 11-15 digits, optionally starting with +.")
        return val

    def create(self, validated_data):
        email = validated_data['email']
        password = validated_data['password']
        first_name = validated_data['first_name']
        last_name = validated_data['last_name']
        company_name = validated_data['company_name']
        cnic = validated_data['cnic']
        phone_number = validated_data['phone_number']
        country = validated_data['country']
        address = validated_data.get('address', '')
        plan_id = validated_data.get('plan_id')

        plan = None
        if plan_id:
            from catalog.models import PricingPlan
            try:
                plan = PricingPlan.objects.get(pk=plan_id)
            except PricingPlan.DoesNotExist:
                pass

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            try:
                user = User.objects.get(username=email)
            except User.DoesNotExist:
                user = None

        with transaction.atomic():
            if user:
                # Update existing user details
                user.set_password(password)
                user.first_name = first_name
                user.last_name = last_name
                user.is_active = False
                user.save()

                # Get existing profile and organization
                profile = user.ownerprofile
                org = profile.organization

                # Update organization
                org.name = company_name
                org.plan = plan
                org.is_active = False
                org.save()

                # Update owner profile
                profile.cnic = cnic
                profile.phone_number = phone_number
                profile.country = country
                profile.address = address
                profile.save()

                # Update registration request to reset status and clear rejection reason
                reg_req = RegistrationRequest.objects.get(owner_profile=profile)
                reg_req.status = 'pending'
                reg_req.rejection_reason = None
                reg_req.reviewed_at = None
                reg_req.save()
            else:
                # Create new records
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=False
                )
                org = Organization.objects.create(
                    name=company_name,
                    plan=plan,
                    is_active=False
                )
                profile = OwnerProfile.objects.create(
                    user=user,
                    organization=org,
                    cnic=cnic,
                    phone_number=phone_number,
                    country=country,
                    address=address
                )
                RegistrationRequest.objects.create(
                    owner_profile=profile,
                    status='pending'
                )

        return profile
