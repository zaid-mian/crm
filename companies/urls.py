from django.urls import path, include
from rest_framework.routers import DefaultRouter
from companies.views import CompanyViewSet

app_name = 'companies'

router = DefaultRouter()
router.register('companies', CompanyViewSet, basename='company')

urlpatterns = [
    path('', include(router.urls)),
]
