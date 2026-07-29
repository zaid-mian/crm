from django.contrib.auth import authenticate, login, logout
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from leads.utils.responses import api_success, api_error
from leads.models import UserProfile

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        if not username or not password:
            return api_error("Both username and password are required.", status_code=status.HTTP_400_BAD_REQUEST)
            
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            profile, _ = UserProfile.objects.get_or_create(
                user=user,
                defaults={'user_type': 'ADMIN' if user.is_superuser or user.is_staff else 'USER'}
            )
            return api_success(data={
                "id": user.id,
                "username": user.username,
                "user_type": profile.user_type
            }, message="Login successful")
            
        return api_error("Invalid credentials.", status_code=status.HTTP_401_UNAUTHORIZED)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={'user_type': 'ADMIN' if user.is_superuser or user.is_staff else 'USER'}
        )
        return api_success(data={
            "id": user.id,
            "username": user.username,
            "user_type": profile.user_type
        }, message="User details retrieved successfully")


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return api_success(message="Logout successful")
