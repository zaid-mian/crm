from django.urls import path
from .views import ProductListView, ProductDetailView, ServiceListView, ServiceDetailView

app_name = 'catalog'

urlpatterns = [
    path('products/', ProductListView.as_view(), name='api_product_list'),
    path('products/<slug:slug>/', ProductDetailView.as_view(), name='api_product_detail'),
    path('services/', ServiceListView.as_view(), name='api_service_list'),
    path('services/<slug:slug>/', ServiceDetailView.as_view(), name='api_service_detail'),
]
