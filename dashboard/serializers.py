from rest_framework import serializers

class DashboardSummarySerializer(serializers.Serializer):
    total_leads = serializers.IntegerField()
    new_leads = serializers.IntegerField()
    qualified_leads = serializers.IntegerField()
    converted_leads = serializers.IntegerField()
    active_opportunities = serializers.IntegerField()
    won_deals = serializers.IntegerField()
    lost_deals = serializers.IntegerField()
    total_pipeline_value = serializers.DecimalField(max_digits=18, decimal_places=2)
    won_revenue = serializers.DecimalField(max_digits=18, decimal_places=2)
    pending_payments = serializers.DecimalField(max_digits=18, decimal_places=2)
    paid_payments = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_companies = serializers.IntegerField()
    total_contacts = serializers.IntegerField()
    conversion_rate = serializers.FloatField()
    average_deal_size = serializers.DecimalField(max_digits=18, decimal_places=2)


class PipelineFunnelSerializer(serializers.Serializer):
    stage_id = serializers.IntegerField()
    stage_name = serializers.CharField()
    entity_type = serializers.CharField()
    stage_type = serializers.CharField()
    color = serializers.CharField()
    order = serializers.IntegerField()
    lead_count = serializers.IntegerField()
    opportunity_count = serializers.IntegerField()
    total_value = serializers.DecimalField(max_digits=18, decimal_places=2)


class DashboardActivitySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    type = serializers.CharField()
    timestamp = serializers.CharField()
    description = serializers.CharField()
    actor_name = serializers.CharField()
    reference_id = serializers.IntegerField()
    reference_name = serializers.CharField()


class FollowUpSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    entity_type = serializers.CharField()
    entity_id = serializers.IntegerField()
    title = serializers.CharField()
    date = serializers.CharField()
    status = serializers.CharField()
    assigned_salesperson = serializers.CharField()
    priority = serializers.CharField()


class PaymentDetailSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class PaymentSummarySerializer(serializers.Serializer):
    paid = PaymentDetailSerializer()
    pending = PaymentDetailSerializer()
    overdue = PaymentDetailSerializer()


class ChartDataSerializer(serializers.Serializer):
    lead_sources = serializers.DictField(child=serializers.IntegerField())
    payment_summary = PaymentSummarySerializer()
