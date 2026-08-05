from django.urls import path
from .views import (
    ProductListView, ProductDetailView, ServiceListView, ServiceDetailView,
    ProductFeedbackAPIView, ServiceFeedbackAPIView, GlobalFeedbackAPIView
)

app_name = 'catalog'

urlpatterns = [
    path('products/', ProductListView.as_view(), name='api_product_list'),
    path('products/<slug:slug>/', ProductDetailView.as_view(), name='api_product_detail'),
    path('products/<slug:slug>/feedback/', ProductFeedbackAPIView.as_view(), name='api_product_feedback'),
    path('services/', ServiceListView.as_view(), name='api_service_list'),
    path('services/<slug:slug>/', ServiceDetailView.as_view(), name='api_service_detail'),
    path('services/<slug:slug>/feedback/', ServiceFeedbackAPIView.as_view(), name='api_services_feedback'),
    path('admin/feedback/', GlobalFeedbackAPIView.as_view(), name='api_global_feedback'),
]
