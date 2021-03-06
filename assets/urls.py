from django.urls import re_path

from rest_framework import routers

from assets.views import AssetViewSet, AssetTypeViewSet, CategoryViewSet, LocationViewSet

# register DRF Views and ViewSets
router = routers.DefaultRouter()
router.register(r'assets', AssetViewSet)
router.register(r'asset-types', AssetTypeViewSet)
router.register(r'categories', CategoryViewSet)
router.register(r'locations', LocationViewSet)

urlpatterns = [ ]

# appends registered API urls to `urlpatterns`
urlpatterns += router.urls
