from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework import status
from django.core.exceptions import ValidationError
from core.api.responses import api_success, api_error
from .models import Product, Service, Feedback
from .serializers import (
    ProductSerializer, ProductDetailSerializer, 
    ServiceSerializer, ServiceDetailSerializer, FeedbackSerializer
)
from catalog.utils import can_user_review

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
            # Prefetch feedbacks to optimize DB queries
            product = Product.objects.prefetch_related('feedbacks__user').get(slug=slug, is_active=True)
        except Product.DoesNotExist:
            return api_error(message="Product not found", status_code=status.HTTP_404_NOT_FOUND)
        
        # Pass request context for SerializerMethodFields
        serializer = ProductDetailSerializer(product, context={'request': request})
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
            # Prefetch feedbacks to optimize DB queries
            service = Service.objects.prefetch_related('feedbacks__user').get(slug=slug, is_active=True)
        except Service.DoesNotExist:
            return api_error(message="Service not found", status_code=status.HTTP_404_NOT_FOUND)
        
        # Pass request context for SerializerMethodFields
        serializer = ServiceDetailSerializer(service, context={'request': request})
        return api_success(data=serializer.data, message="Service retrieved successfully")


class ProductFeedbackAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        product = Product.objects.filter(slug=slug, is_active=True).first()
        if not product:
            return api_error("Product not found", status_code=status.HTTP_404_NOT_FOUND)

        if not can_user_review(request.user, product):
            return api_error("You must have owned or subscribed to this item to leave feedback.", status_code=status.HTTP_403_FORBIDDEN)

        rating = request.data.get('rating')
        comment = request.data.get('comment', '')

        if rating is None:
            return api_error("Rating is a required field.", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            rating = int(rating)
        except (ValueError, TypeError):
            return api_error("Rating must be an integer.", status_code=status.HTTP_400_BAD_REQUEST)

        if rating < 1 or rating > 5:
            return api_error("Rating must be between 1 and 5.", status_code=status.HTTP_400_BAD_REQUEST)

        feedback, created = Feedback.objects.get_or_create(
            user=request.user,
            product=product,
            defaults={'rating': rating, 'comment': comment}
        )
        
        if not created:
            feedback.rating = rating
            feedback.comment = comment
            try:
                feedback.full_clean()
            except ValidationError as e:
                return api_error(message="Feedback validation failed.", errors=e.message_dict, status_code=status.HTTP_400_BAD_REQUEST)
            feedback.save()

        msg = "Feedback submitted successfully." if created else "Feedback updated successfully."
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        
        return api_success(
            data={
                "rating": feedback.rating,
                "comment": feedback.comment,
                "updated_at": feedback.updated_at.isoformat()
            },
            message=msg,
            status_code=status_code
        )


class ServiceFeedbackAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        service = Service.objects.filter(slug=slug, is_active=True).first()
        if not service:
            return api_error("Service not found", status_code=status.HTTP_404_NOT_FOUND)

        if not can_user_review(request.user, service):
            return api_error("You must have owned or subscribed to this item to leave feedback.", status_code=status.HTTP_403_FORBIDDEN)

        rating = request.data.get('rating')
        comment = request.data.get('comment', '')

        if rating is None:
            return api_error("Rating is a required field.", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            rating = int(rating)
        except (ValueError, TypeError):
            return api_error("Rating must be an integer.", status_code=status.HTTP_400_BAD_REQUEST)

        if rating < 1 or rating > 5:
            return api_error("Rating must be between 1 and 5.", status_code=status.HTTP_400_BAD_REQUEST)

        feedback, created = Feedback.objects.get_or_create(
            user=request.user,
            service=service,
            defaults={'rating': rating, 'comment': comment}
        )
        
        if not created:
            feedback.rating = rating
            feedback.comment = comment
            try:
                feedback.full_clean()
            except ValidationError as e:
                return api_error(message="Feedback validation failed.", errors=e.message_dict, status_code=status.HTTP_400_BAD_REQUEST)
            feedback.save()

        msg = "Feedback submitted successfully." if created else "Feedback updated successfully."
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        
        return api_success(
            data={
                "rating": feedback.rating,
                "comment": feedback.comment,
                "updated_at": feedback.updated_at.isoformat()
            },
            message=msg,
            status_code=status_code
        )


class GlobalFeedbackAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        feedbacks = Feedback.objects.all().select_related('user', 'product', 'service').order_by('-updated_at')

        data = []
        for f in feedbacks:
            user_name = f.user.get_full_name() or f.user.email.split('@')[0]
            if f.product:
                target_type = "product"
                target_name = f.product.name
            else:
                target_type = "service"
                target_name = f.service.name

            data.append({
                "id": f.id,
                "user_name": user_name,
                "target_type": target_type,
                "target_name": target_name,
                "rating": f.rating,
                "comment": f.comment,
                "updated_at": f.updated_at.isoformat()
            })

        return api_success(data=data, message="Global reviews retrieved successfully.")
