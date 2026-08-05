from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import status
from leads.utils.responses import api_success, api_error
from .models import Product, Service
from .serializers import (
    ProductSerializer, ProductDetailSerializer, 
    ServiceSerializer, ServiceDetailSerializer
)

class ProductListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        products = Product.objects.filter(is_active=True)
        serializer = ProductSerializer(products, many=True)
        return api_success(data=serializer.data, message="Products retrieved successfully")


class ProductDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        try:
            product = Product.objects.get(slug=slug, is_active=True)
        except Product.DoesNotExist:
            return api_error(message="Product not found", status_code=status.HTTP_404_NOT_FOUND)
        
        serializer = ProductDetailSerializer(product)
        return api_success(data=serializer.data, message="Product retrieved successfully")


class ServiceListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        services = Service.objects.filter(is_active=True)
        serializer = ServiceSerializer(services, many=True)
        return api_success(data=serializer.data, message="Services retrieved successfully")


class ServiceDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        try:
            service = Service.objects.get(slug=slug, is_active=True)
        except Service.DoesNotExist:
            return api_error(message="Service not found", status_code=status.HTTP_404_NOT_FOUND)
        
        serializer = ServiceDetailSerializer(service)
        return api_success(data=serializer.data, message="Service retrieved successfully")
