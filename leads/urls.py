from django.urls import path, include
from rest_framework.routers import DefaultRouter
from leads.views import LeadViewSet, LoginView, MeView, LogoutView

app_name = 'leads'

router = DefaultRouter()
router.register(r'leads', LeadViewSet, basename='lead')

urlpatterns = [
    path('', include(router.urls)),
    path('login/', LoginView.as_view(), name='login'),
    path('me/', MeView.as_view(), name='me'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
