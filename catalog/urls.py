from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProductListView, ProductDetailView, ServiceListView, ServiceDetailView,
    ProductFeedbackAPIView, ServiceFeedbackAPIView, GlobalFeedbackAPIView,
    ProductAdminViewSet, ModuleAdminViewSet, PricingPlanAdminViewSet,
    PlanModuleAdminViewSet, DiscountAdminViewSet
)

app_name = 'catalog'

router = DefaultRouter()
router.register(r'admin/products', ProductAdminViewSet, basename='admin-product')
router.register(r'admin/modules', ModuleAdminViewSet, basename='admin-module')
router.register(r'admin/pricing-plans', PricingPlanAdminViewSet, basename='admin-pricingplan')
router.register(r'admin/plan-modules', PlanModuleAdminViewSet, basename='admin-planmodule')
router.register(r'admin/discounts', DiscountAdminViewSet, basename='admin-discount')

urlpatterns = [
    path('products/', ProductListView.as_view(), name='api_product_list'),
    path('products/<slug:slug>/', ProductDetailView.as_view(), name='api_product_detail'),
    path('products/<slug:slug>/feedback/', ProductFeedbackAPIView.as_view(), name='api_product_feedback'),
    path('services/', ServiceListView.as_view(), name='api_service_list'),
    path('services/<slug:slug>/', ServiceDetailView.as_view(), name='api_service_detail'),
    path('services/<slug:slug>/feedback/', ServiceFeedbackAPIView.as_view(), name='api_services_feedback'),
    path('admin/feedback/', GlobalFeedbackAPIView.as_view(), name='api_global_feedback'),
    path('', include(router.urls)),
]
