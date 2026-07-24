from django.urls import path, include
from rest_framework.routers import DefaultRouter
from pipeline.views import PipelineViewSet

app_name = 'pipeline'

router = DefaultRouter()
router.register(r'pipeline', PipelineViewSet, basename='pipeline')

urlpatterns = [
    path('', include(router.urls)),
]
