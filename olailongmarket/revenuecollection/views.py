# views.py

# Standard library imports
import json
import uuid
import requests
from datetime import timedelta

# Django imports
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone as django_timezone
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpResponse

# ReportLab for PDF generation
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch

# Django REST Framework imports
from rest_framework import viewsets, permissions, status, filters, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

# For filtering support
from django_filters.rest_framework import DjangoFilterBackend

# Local app imports
from .models import Vendor, Property, Occupancy, Invoice, Payment, Notification, IPNLog
from .serializers import (
    VendorSerializer, PropertySerializer, OccupancySerializer,
    InvoiceSerializer, PaymentSerializer, NotificationSerializer,
    UserRegisterSerializer, IPNLogSerializer, VendorProfileSerializer  # <-- added
)

# -------------------------------------------------------------------
# User Registration View (for agents/admin)
# -------------------------------------------------------------------
class UserRegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [permissions.AllowAny]


# -------------------------------------------------------------------
# Customer Registration View
# -------------------------------------------------------------------
class CustomerRegisterView(APIView):
    """
    Registers a new user and links them to a vendor profile.
    Accepts username (often phone), password, phone_number, full_name.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        phone_number = request.data.get('phone_number')
        full_name = request.data.get('full_name')

        if not username or not password:
            return Response({"error": "Username and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response({"error": "Username already exists."}, status=status.HTTP_400_BAD_REQUEST)

        # Create user account
        user = User.objects.create_user(username=username, password=password)

        # Link to existing vendor by phone, or create new vendor
        vendor = Vendor.objects.filter(phone_number=phone_number).first()
        if vendor:
            vendor.user = user
            if full_name:
                vendor.full_name = full_name
            vendor.save()
        else:
            Vendor.objects.create(
                user=user,
                full_name=full_name or username,
                phone_number=phone_number or username
            )

        return Response({"message": "Registration successful."}, status=status.HTTP_201_CREATED)


# -------------------------------------------------------------------
# Customer Dashboard View
# -------------------------------------------------------------------
class CustomerDashboardView(APIView):
    """
    Returns the logged-in customer's vendor profile, invoices, and payments.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        vendor = getattr(request.user, 'vendor_profile', None)
        if not vendor:
            return Response({"error": "No vendor profile linked to this account."}, status=status.HTTP_404_NOT_FOUND)

        occupancies = Occupancy.objects.filter(vendor=vendor, is_active=True)
        invoices = Invoice.objects.filter(occupancy__in=occupancies).order_by('-billing_period_start')
        payments = Payment.objects.filter(invoice__in=invoices).order_by('-created_at')

        data = {
            'vendor': VendorProfileSerializer(vendor).data,
            'invoices': InvoiceSerializer(invoices, many=True).data,
            'payments': PaymentSerializer(payments, many=True).data,
        }
        return Response(data)


# -------------------------------------------------------------------
# Customer Profile Update View
# -------------------------------------------------------------------
class CustomerProfileUpdateView(APIView):
    """
    Allows a customer to retrieve and update their vendor profile, including photo.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        vendor = getattr(request.user, 'vendor_profile', None)
        if not vendor:
            return Response({"error": "No vendor profile linked."}, status=status.HTTP_404_NOT_FOUND)
        return Response(VendorProfileSerializer(vendor).data)

    def patch(self, request):
        vendor = getattr(request.user, 'vendor_profile', None)
        if not vendor:
            return Response({"error": "No vendor profile linked."}, status=status.HTTP_404_NOT_FOUND)

        serializer = VendorProfileSerializer(vendor, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# -------------------------------------------------------------------
# Vendor ViewSet (admin/agent)
# -------------------------------------------------------------------
class VendorViewSet(viewsets.ModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['full_name', 'phone_number', 'national_id', 'email']
    ordering_fields = ['full_name', 'created_at']
    ordering = ['full_name']


# -------------------------------------------------------------------
# Property ViewSet
# -------------------------------------------------------------------
class PropertyViewSet(viewsets.ModelViewSet):
    queryset = Property.objects.all()
    serializer_class = PropertySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'location', 'property_type']
    ordering_fields = ['code', 'property_type']
    ordering = ['code']


# -------------------------------------------------------------------
# Occupancy ViewSet
# -------------------------------------------------------------------
class OccupancyViewSet(viewsets.ModelViewSet):
    queryset = Occupancy.objects.all()
    serializer_class = OccupancySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = ['vendor__full_name', 'property__code', 'property__location']
    ordering_fields = ['start_date', 'end_date']
    ordering = ['-start_date']
    filterset_fields = ['is_active', 'property', 'vendor']


# -------------------------------------------------------------------
# Invoice ViewSet
# -------------------------------------------------------------------
class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = ['occupancy__vendor__full_name', 'occupancy__property__code']
    ordering_fields = ['billing_period_start', 'due_date', 'status', 'amount']
    ordering = ['-billing_period_start']
    filterset_fields = ['occupancy', 'status', 'due_date']

    @action(detail=False, methods=['post'], url_path='generate-monthly')
    def generate_monthly(self, request):
        today = django_timezone.now().date()
        period_start = today.replace(day=1)
        next_month = period_start.replace(day=28) + timedelta(days=4)
        period_end = next_month - timedelta(days=next_month.day)
        due_date = period_start + timedelta(days=9)

        active_occupancies = Occupancy.objects.filter(is_active=True, start_date__lte=today)
        created_invoices = []
        for occ in active_occupancies:
            if not Invoice.objects.filter(occupancy=occ, billing_period_start=period_start).exists():
                prop = occ.property
                invoice = Invoice.objects.create(
                    occupancy=occ,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    due_date=due_date,
                    rent_amount=prop.rent_fee,
                    sanitation_amount=prop.sanitation_fee,
                    security_amount=prop.security_fee,
                    other_amount=prop.other_fee,
                )
                created_invoices.append(InvoiceSerializer(invoice).data)

        return Response(
            {
                "message": f"Generated {len(created_invoices)} invoice(s).",
                "invoices": created_invoices,
            },
            status=status.HTTP_201_CREATED
        )


# -------------------------------------------------------------------
# Payment ViewSet
# -------------------------------------------------------------------
class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'transaction_ref', 'phone_number',
        'invoice__occupancy__vendor__full_name',
        'pesapal_order_tracking_id'
    ]
    ordering_fields = ['created_at', 'amount', 'status']
    ordering = ['-created_at']


# -------------------------------------------------------------------
# Notification ViewSet
# -------------------------------------------------------------------
class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['vendor__full_name', 'message']
    ordering_fields = ['sent_at']
    ordering = ['-sent_at']


# -------------------------------------------------------------------
# Pesapal API Helper Class
# -------------------------------------------------------------------
class PesapalAPI:
    """
    Helper class for interacting with the Pesapal API v3.
    """

    def __init__(self):
        self.base_url = settings.PESAPAL_BASE_URL.rstrip('/')
        self.consumer_key = settings.PESAPAL_CONSUMER_KEY
        self.consumer_secret = settings.PESAPAL_CONSUMER_SECRET

    def _get_token(self):
        url = f"{self.base_url}/api/Auth/RequestToken"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "consumer_key": self.consumer_key,
            "consumer_secret": self.consumer_secret,
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json().get("token")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Pesapal token request failed: {str(e)}")
        except ValueError:
            raise Exception(f"Pesapal token returned invalid JSON: {response.text}")

    def submit_order(
        self,
        amount,
        description,
        callback_url,
        merchant_reference,
        currency="UGX",
        return_url=None,
        payer_phone=None
    ):
        """
        Submits a payment order to Pesapal.
        If payer_phone is provided, it will be used as the mobile money account to charge.
        """
        token = self._get_token()
        url = f"{self.base_url}/api/Transactions/SubmitOrderRequest"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        billing_address = {
            "email_address": "",
            "phone_number": payer_phone or "",
            "country_code": "UG",
            "first_name": "",
            "middle_name": "",
            "last_name": "",
            "line_1": "",
            "line_2": "",
            "city": "",
            "state": "",
            "postal_code": "",
            "zip_code": "",
        }

        payload = {
            "id": merchant_reference,
            "currency": currency,
            "amount": float(amount),
            "description": description,
            "callback_url": callback_url,
            "billing_address": billing_address,
        }

        if return_url:
            payload["return_url"] = return_url

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            if response_data.get("status") == "200":
                return response_data.get("order_tracking_id"), response_data.get("redirect_url"), None
            else:
                return None, None, response_data.get("error", {}).get("message", "Unknown error")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Pesapal order submission failed: {str(e)}")
        except ValueError:
            raise Exception(f"Pesapal order returned invalid JSON: {response.text}")

    def get_transaction_status(self, order_tracking_id):
        token = self._get_token()
        url = f"{self.base_url}/api/Transactions/GetTransactionStatus?orderTrackingId={order_tracking_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Pesapal status request failed: {str(e)}")
        except ValueError:
            raise Exception(f"Pesapal status returned invalid JSON: {response.text}")


# -------------------------------------------------------------------
# Payment Initiation (Pesapal) – Single Invoice
# -------------------------------------------------------------------
class InitiatePaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, invoice_id):
        with transaction.atomic():
            invoice = get_object_or_404(
                Invoice.objects.select_for_update(), id=invoice_id
            )

            if invoice.status not in ['pending', 'overdue']:
                return Response({"error": "Invoice is not payable."}, status=status.HTTP_400_BAD_REQUEST)

            active_payment_exists = Payment.objects.filter(
                invoice=invoice,
                status__in=['initiated', 'pending']
            ).exists()
            if active_payment_exists:
                return Response(
                    {"error": "A payment is already in progress for this invoice."},
                    status=status.HTTP_409_CONFLICT
                )

            payer_phone = request.data.get('payer_phone_number') or invoice.occupancy.vendor.phone_number

            merchant_reference = uuid.uuid4().hex
            callback_url = request.build_absolute_uri('/api/payments/pesapal-callback/')
            frontend_callback = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173') + '/payment/callback'

            vendor = invoice.occupancy.vendor
            description = f"Olailong Market: Invoice #{invoice.id} for {vendor.full_name}"

            pesapal = PesapalAPI()
            try:
                order_tracking_id, redirect_url, error = pesapal.submit_order(
                    amount=invoice.amount,
                    description=description,
                    callback_url=callback_url,
                    merchant_reference=merchant_reference,
                    return_url=frontend_callback,
                    payer_phone=payer_phone,
                )
            except Exception as e:
                return Response({"error": f"Pesapal API error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            if error:
                return Response({"error": error}, status=status.HTTP_502_BAD_GATEWAY)

            Payment.objects.create(
                invoice=invoice,
                transaction_ref=merchant_reference,
                pesapal_order_tracking_id=order_tracking_id,
                amount=invoice.amount,
                phone_number=payer_phone,
                status='pending',
            )

        return Response({
            "message": "Payment initiated. Redirect user to Pesapal.",
            "redirect_url": redirect_url,
            "merchant_reference": merchant_reference,
            "order_tracking_id": order_tracking_id,
        }, status=status.HTTP_200_OK)


# -------------------------------------------------------------------
# Batch Payment Initiation (Pesapal) – Multiple Invoices
# -------------------------------------------------------------------
class BatchInitiatePaymentView(APIView):
    """
    Initiates a single Pesapal payment for multiple invoices.
    Requires the agent's mobile money number (payer_phone_number).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        invoice_ids = request.data.get('invoice_ids', [])
        if not invoice_ids or not isinstance(invoice_ids, list):
            return Response({"error": "Provide a list of invoice IDs."}, status=status.HTTP_400_BAD_REQUEST)

        payer_phone = request.data.get('payer_phone_number')
        if not payer_phone:
            return Response({"error": "payer_phone_number is required for batch payment."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            invoices = list(
                Invoice.objects.select_for_update().filter(
                    id__in=invoice_ids,
                    status__in=['pending', 'overdue']
                )
            )

            if len(invoices) != len(set(invoice_ids)):
                return Response({"error": "One or more invoices are not payable."}, status=status.HTTP_400_BAD_REQUEST)

            active_payment_exists = Payment.objects.filter(
                invoice__in=invoices,
                status__in=['initiated', 'pending']
            ).exists()
            if active_payment_exists:
                return Response(
                    {"error": "One or more invoices already have an active payment."},
                    status=status.HTTP_409_CONFLICT
                )

            total_amount = sum(inv.amount for inv in invoices)
            if total_amount <= 0:
                return Response({"error": "Total amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

            merchant_reference = uuid.uuid4().hex
            callback_url = request.build_absolute_uri('/api/payments/pesapal-callback/')
            frontend_callback = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173') + '/payment/callback'

            description = f"Olailong Market batch payment ({len(invoices)} invoices)"

            pesapal = PesapalAPI()
            try:
                order_tracking_id, redirect_url, error = pesapal.submit_order(
                    amount=total_amount,
                    description=description,
                    callback_url=callback_url,
                    merchant_reference=merchant_reference,
                    return_url=frontend_callback,
                    payer_phone=payer_phone,
                )
            except Exception as e:
                return Response({"error": f"Pesapal API error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            if error:
                return Response({"error": error}, status=status.HTTP_502_BAD_GATEWAY)

            for inv in invoices:
                Payment.objects.create(
                    invoice=inv,
                    transaction_ref=merchant_reference,
                    pesapal_order_tracking_id=order_tracking_id,
                    amount=inv.amount,
                    phone_number=payer_phone,
                    status='pending',
                )

        return Response({
            "message": "Batch payment initiated.",
            "redirect_url": redirect_url,
            "merchant_reference": merchant_reference,
            "order_tracking_id": order_tracking_id,
            "total_amount": total_amount,
        }, status=status.HTTP_200_OK)


# -------------------------------------------------------------------
# Payment Verification (supports batch)
# -------------------------------------------------------------------
class VerifyPaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        order_tracking_id = request.query_params.get('orderTrackingId')
        merchant_reference = request.query_params.get('merchantReference')

        if not order_tracking_id or not merchant_reference:
            return Response({"error": "Missing parameters"}, status=status.HTTP_400_BAD_REQUEST)

        payments = Payment.objects.filter(
            transaction_ref=merchant_reference,
            pesapal_order_tracking_id=order_tracking_id
        )
        if not payments.exists():
            return Response({"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

        if payments.filter(status='pending').exists():
            pesapal = PesapalAPI()
            try:
                status_data = pesapal.get_transaction_status(order_tracking_id)
                remote_status = status_data.get("payment_status_description", "").lower()
                if remote_status in ['completed', 'paid']:
                    for payment in payments:
                        payment.mark_successful()
                elif remote_status in ['failed', 'cancelled', 'voided']:
                    new_status = 'failed' if remote_status != 'cancelled' else 'cancelled'
                    for payment in payments:
                        payment.status = new_status
                        payment.save(update_fields=['status', 'updated_at'])
            except Exception as e:
                print(f"Pesapal status check failed: {e}")

        if payments.filter(status='successful').count() == payments.count():
            overall_status = 'successful'
        elif payments.filter(status='failed').exists():
            overall_status = 'failed'
        elif payments.filter(status='cancelled').exists():
            overall_status = 'cancelled'
        else:
            overall_status = 'pending'

        return Response({"payment_status": overall_status})


# -------------------------------------------------------------------
# Pesapal Callback / IPN
# -------------------------------------------------------------------
@api_view(['GET', 'POST'])
@permission_classes([permissions.AllowAny])
def pesapal_callback(request):
    if request.method == 'GET':
        order_tracking_id = request.query_params.get('orderTrackingId')
        merchant_reference = request.query_params.get('orderMerchantReference')
    else:
        data = json.loads(request.body)
        order_tracking_id = data.get('orderTrackingId')
        merchant_reference = data.get('orderMerchantReference')

    if not order_tracking_id or not merchant_reference:
        return Response({"error": "Missing parameters"}, status=status.HTTP_400_BAD_REQUEST)

    IPNLog.objects.create(
        payload=json.dumps(request.data if request.method == 'POST' else request.query_params),
        order_tracking_id=order_tracking_id,
        merchant_reference=merchant_reference,
        processed=False
    )

    payments = Payment.objects.filter(
        transaction_ref=merchant_reference,
        pesapal_order_tracking_id=order_tracking_id
    )
    if not payments.exists():
        return Response({"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

    pesapal = PesapalAPI()
    try:
        status_data = pesapal.get_transaction_status(order_tracking_id)
        payment_status = status_data.get("payment_status_description", "").lower()
    except Exception as e:
        return Response({"error": f"Failed to verify status: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if payment_status in ['completed', 'paid']:
        for payment in payments:
            payment.mark_successful()
        IPNLog.objects.filter(merchant_reference=merchant_reference).update(processed=True)
    elif payment_status in ['failed', 'cancelled', 'voided']:
        new_status = 'failed' if payment_status != 'cancelled' else 'cancelled'
        for payment in payments:
            payment.status = new_status
            payment.save(update_fields=['status', 'updated_at'])
        IPNLog.objects.filter(merchant_reference=merchant_reference).update(processed=True)

    return Response({"message": "IPN processed", "status": payment_status}, status=status.HTTP_200_OK)


# -------------------------------------------------------------------
# PDF Receipt Download
# -------------------------------------------------------------------
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def download_receipt_pdf(request):
    merchant_reference = request.query_params.get('merchant_reference')
    if not merchant_reference:
        return Response({"error": "Merchant reference is required."}, status=400)

    payments = Payment.objects.filter(transaction_ref=merchant_reference).select_related(
        'invoice__occupancy__vendor', 'invoice__occupancy__property'
    )
    if not payments.exists():
        return Response({"error": "No payments found."}, status=404)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt-{merchant_reference}.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    title_style = styles['Title']
    normal_style = styles['Normal']

    elements.append(Paragraph("Olailong Market", title_style))
    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph("Payment Receipt", normal_style))
    elements.append(Spacer(1, 0.2 * inch))

    first_payment = payments.first()
    total_amount = sum(p.amount for p in payments)
    elements.append(Paragraph(f"Receipt No: {merchant_reference}", normal_style))
    elements.append(Paragraph(f"Date: {first_payment.created_at.strftime('%Y-%m-%d %H:%M')}", normal_style))
    elements.append(Paragraph(f"Total Amount: UGX {total_amount:,.0f}", normal_style))
    elements.append(Spacer(1, 0.2 * inch))

    table_data = [['Vendor', 'Property', 'Amount (UGX)', 'Status', 'Pesapal Tracking ID']]
    for payment in payments:
        vendor_name = payment.invoice.occupancy.vendor.full_name
        property_code = payment.invoice.occupancy.property.code
        amount = f"{payment.amount:,.0f}"
        status_str = payment.status.capitalize()
        tracking = payment.pesapal_order_tracking_id or 'N/A'
        table_data.append([vendor_name, property_code, amount, status_str, tracking])

    table = Table(table_data, colWidths=[1.8*inch, 1.2*inch, 1.2*inch, 1.0*inch, 2.0*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ]))
    elements.append(table)

    doc.build(elements)
    return response