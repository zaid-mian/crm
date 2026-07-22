from django.urls import path, include
from rest_framework.routers import DefaultRouter
from leads.views import LeadViewSet

app_name = 'leads'

router = DefaultRouter()
router.register(r'leads', LeadViewSet, basename='lead')

urlpatterns = [
    path('', include(router.urls)),
]
