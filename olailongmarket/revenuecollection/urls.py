# revenuecollection/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    VendorViewSet,
    PropertyViewSet,
    OccupancyViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    NotificationViewSet,
    UserRegisterView,
    InitiatePaymentView,
    VerifyPaymentView,
    BatchInitiatePaymentView,
    CustomerDashboardView,
    CustomerProfileUpdateView,
    CustomerRegisterView,
    
    pesapal_callback,
    download_receipt_pdf,
)

router = DefaultRouter()
router.register(r'vendors', VendorViewSet)
router.register(r'properties', PropertyViewSet)
router.register(r'occupancies', OccupancyViewSet)
router.register(r'invoices', InvoiceViewSet)
router.register(r'payments', PaymentViewSet)
router.register(r'notifications', NotificationViewSet)

urlpatterns = [
    # Custom endpoint for user registration (not part of a ViewSet).
    # POST /api/user/register/
    path('user/register/', UserRegisterView.as_view(), name='user-register'),

    # --- Custom "payments/*" routes MUST come before the router include,
    # otherwise DRF's PaymentViewSet detail route (payments/<pk>/) will
    # shadow these single-segment paths. ---
     # in urls.py
     path('customer/register/', CustomerRegisterView.as_view(), name='customer-register'),
     path('customer/dashboard/', CustomerDashboardView.as_view(), name='customer-dashboard'),
     path('customer/profile/', CustomerProfileUpdateView.as_view(), name='customer-profile'),
    # Batch-initiate payments across multiple invoices.
    # POST /api/payments/batch-initiate/
    path('payments/batch-initiate/',
         BatchInitiatePaymentView.as_view(),
         name='batch-initiate-payment'),

    # Initiate Pesapal payment for a specific invoice.
    # POST /api/payments/initiate/<invoice_id>/
    path('payments/initiate/<int:invoice_id>/',
         InitiatePaymentView.as_view(),
         name='initiate-payment'),
    path('payments/receipt-pdf/', download_receipt_pdf, name='receipt-pdf'),

    # Verify payment status (called by frontend after redirect from Pesapal).
    # GET /api/payments/verify/?orderTrackingId=...&merchantReference=...
    path('payments/verify/',
         VerifyPaymentView.as_view(),
         name='verify-payment'),

    # Pesapal IPN callback (called by Pesapal server; no authentication required).
    # GET or POST /api/payments/pesapal-callback/
    path('payments/pesapal-callback/',
         pesapal_callback,
         name='pesapal-callback'),

    # Include all router-generated URLs at the root of this app's URLconf.
    # In the project, this whole file is included under /api/, so final URLs
    # become /api/vendors/, /api/properties/, etc.
    path('', include(router.urls)),
]