from django.urls import path, include
from rest_framework.routers import DefaultRouter
from pipeline.views import PipelineViewSet, PipelineModelViewSet, PipelineStageViewSet

app_name = 'pipeline'

router = DefaultRouter()
router.register(r'pipeline', PipelineViewSet, basename='pipeline')
router.register(r'pipelines', PipelineModelViewSet, basename='pipelines')
router.register(r'pipeline/stages', PipelineStageViewSet, basename='pipeline-stage')

urlpatterns = [
    path('', include(router.urls)),
]
