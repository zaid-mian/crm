from django.urls import path, include
from rest_framework.routers import DefaultRouter
from opportunities.views import OpportunityViewSet

app_name = 'opportunities'

router = DefaultRouter()
router.register(r'opportunities', OpportunityViewSet, basename='opportunity')

urlpatterns = [
    path('', include(router.urls)),
]
