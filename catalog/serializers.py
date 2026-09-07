from rest_framework import serializers
from django.db.models import Avg
from .models import Product, Module, Service, ServiceFeature, PricingPlan, PlanModule, Discount, Feedback
from catalog.utils import can_user_review

from django.core.exceptions import ValidationError

class ModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['id', 'product', 'name', 'code', 'description', 'is_active', 'display_order', 'created_at']

    def validate(self, attrs):
        instance = self.instance or Module()
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.full_clean()
        except ValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class ServiceFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceFeature
        fields = ['id', 'name', 'display_order']


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = ['id', 'pricing_plan', 'name', 'discount_type', 'value', 'is_active', 'start_date', 'end_date']

    def validate(self, attrs):
        instance = self.instance or Discount()
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.full_clean()
        except ValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class PricingPlanSerializer(serializers.ModelSerializer):
    final_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    active_discount = serializers.SerializerMethodField()

    class Meta:
        model = PricingPlan
        fields = [
            'id', 'product', 'service', 'name', 'price', 'final_price', 'currency', 
            'billing_cycle', 'is_active', 'display_order', 'active_discount', 'created_at'
        ]

    def get_active_discount(self, obj):
        discount = obj.get_active_discount()
        if discount:
            return DiscountSerializer(discount).data
        return None

    def validate(self, attrs):
        instance = self.instance or PricingPlan()
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.full_clean()
        except ValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class PlanModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanModule
        fields = ['id', 'plan', 'module', 'is_enabled', 'limit_value']

    def validate(self, attrs):
        instance = self.instance or PlanModule()
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.full_clean()
        except ValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['id', 'name', 'slug', 'description', 'image', 'is_active', 'display_order', 'created_at']

    def validate(self, attrs):
        instance = self.instance or Product()
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.full_clean()
        except ValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class FeedbackSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Feedback
        fields = ['id', 'user_id', 'user_name', 'rating', 'comment', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def get_user_name(self, obj):
        full_name = obj.user.get_full_name()
        return full_name if full_name else obj.user.email.split('@')[0]


class ProductDetailSerializer(serializers.ModelSerializer):
    modules = ModuleSerializer(many=True, read_only=True)
    pricing_plans = PricingPlanSerializer(source='plans', many=True, read_only=True)
    can_review = serializers.SerializerMethodField()
    has_reviewed = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'description', 'image', 
            'is_active', 'display_order', 'modules', 'pricing_plans',
            'can_review', 'has_reviewed', 'average_rating', 'review_count', 'reviews'
        ]

    def get_can_review(self, obj):
        request = self.context.get('request')
        user = request.user if request else None
        return can_user_review(user, obj)

    def get_has_reviewed(self, obj):
        request = self.context.get('request')
        user = request.user if request else None
        if user and user.is_authenticated:
            return obj.feedbacks.filter(user=user).exists()
        return False

    def get_average_rating(self, obj):
        avg_rating = obj.feedbacks.aggregate(Avg('rating'))['rating__avg']
        return float(avg_rating) if avg_rating is not None else 0.0

    def get_review_count(self, obj):
        return obj.feedbacks.count()

    def get_reviews(self, obj):
        return FeedbackSerializer(obj.feedbacks.all(), many=True).data


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id', 'name', 'slug', 'short_description', 'full_description', 'image', 'is_active', 'display_order']


class ServiceDetailSerializer(serializers.ModelSerializer):
    features = ServiceFeatureSerializer(many=True, read_only=True)
    pricing_plans = PricingPlanSerializer(source='plans', many=True, read_only=True)
    can_review = serializers.SerializerMethodField()
    has_reviewed = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'slug', 'short_description', 'full_description', 
            'image', 'is_active', 'display_order', 'features', 'pricing_plans',
            'can_review', 'has_reviewed', 'average_rating', 'review_count', 'reviews'
        ]

    def get_can_review(self, obj):
        request = self.context.get('request')
        user = request.user if request else None
        return can_user_review(user, obj)

    def get_has_reviewed(self, obj):
        request = self.context.get('request')
        user = request.user if request else None
        if user and user.is_authenticated:
            return obj.feedbacks.filter(user=user).exists()
        return False

    def get_average_rating(self, obj):
        avg_rating = obj.feedbacks.aggregate(Avg('rating'))['rating__avg']
        return float(avg_rating) if avg_rating is not None else 0.0

    def get_review_count(self, obj):
        return obj.feedbacks.count()

    def get_reviews(self, obj):
        return FeedbackSerializer(obj.feedbacks.all(), many=True).data
