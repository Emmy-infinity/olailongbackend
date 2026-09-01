from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from revenuecollection.admin import admin_site  # import custom admin site

urlpatterns = [
    path('admin/', admin_site.urls),  # use custom admin site
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/', include('revenuecollection.urls')),
]