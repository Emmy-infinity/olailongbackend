# revenuecollection/admin.py
from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from .models import (
    Vendor, Property, Occupancy, Invoice, Payment, Notification, IPNLog
)

# -------------------------------
# Custom Admin Site
# -------------------------------
class OlailongAdminSite(admin.AdminSite):
    site_header = "Olailong Market Admin"
    site_title = "Olailong Market Admin Portal"
    index_title = "Market Management"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('dashboard/', self.admin_view(dashboard_view), name='market-dashboard'),
        ]
        return custom_urls + urls

# Instantiate the custom admin site
admin_site = OlailongAdminSite(name='myadmin')

# -------------------------------
# Dashboard View
# -------------------------------
def dashboard_view(request):
    if not request.user.is_staff:
        return redirect('admin:login')

    today = timezone.now().date()
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    last_month_end = month_start - timedelta(days=1)

    total_properties = Property.objects.count()
    occupied = Occupancy.objects.filter(is_active=True).count()
    occupancy_rate = (occupied / total_properties * 100) if total_properties else 0
    total_vendors = Vendor.objects.filter(is_active=True).count()
    total_invoices = Invoice.objects.filter(billing_period_start__gte=month_start).count()
    total_collected_month = Payment.objects.filter(
        status='successful', created_at__date__gte=month_start
    ).aggregate(total=Sum('amount'))['total'] or 0
    total_collected_prev_month = Payment.objects.filter(
        status='successful',
        created_at__date__gte=last_month_start,
        created_at__date__lte=last_month_end
    ).aggregate(total=Sum('amount'))['total'] or 0

    payment_stats = Payment.objects.filter(created_at__date__gte=month_start).aggregate(
        successful=Count('id', filter=Q(status='successful')),
        pending=Count('id', filter=Q(status='pending')),
        failed=Count('id', filter=Q(status='failed')),
        cancelled=Count('id', filter=Q(status='cancelled')),
    )

    overdue_count = Invoice.objects.filter(status='overdue').count()
    overdue_amount = Invoice.objects.filter(status='overdue').aggregate(total=Sum('amount'))['total'] or 0

    recent_payments = Payment.objects.select_related(
        'invoice__occupancy__vendor', 'invoice__occupancy__property'
    ).order_by('-created_at')[:15]

    recent_ipns = IPNLog.objects.order_by('-received_at')[:10]

    context = {
        'title': 'Market Dashboard',
        'total_properties': total_properties,
        'occupied': occupied,
        'occupancy_rate': round(occupancy_rate, 2),
        'total_vendors': total_vendors,
        'total_invoices': total_invoices,
        'total_collected_month': total_collected_month,
        'total_collected_prev_month': total_collected_prev_month,
        'payment_stats': payment_stats,
        'overdue_count': overdue_count,
        'overdue_amount': overdue_amount,
        'recent_payments': recent_payments,
        'recent_ipns': recent_ipns,
        'today': today,
    }
    return render(request, 'admin/dashboard.html', context)

# -------------------------------
# Register models with the custom admin site
# -------------------------------
@admin.register(Vendor, site=admin_site)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone_number', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('full_name', 'phone_number', 'national_id')

@admin.register(Property, site=admin_site)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ('code', 'property_type', 'rent_fee', 'sanitation_fee', 'security_fee', 'is_active')
    list_filter = ('property_type', 'is_active')
    search_fields = ('code', 'location')

@admin.register(Occupancy, site=admin_site)
class OccupancyAdmin(admin.ModelAdmin):
    list_display = ('vendor', 'property', 'start_date', 'end_date', 'is_active')
    list_filter = ('is_active', 'start_date')
    search_fields = ('vendor__full_name', 'property__code')

@admin.register(Invoice, site=admin_site)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'vendor', 'property', 'billing_period_start', 'due_date', 'amount', 'status', 'paid_at')
    list_filter = ('status', 'billing_period_start')
    search_fields = ('occupancy__vendor__full_name', 'occupancy__property__code')
    actions = ['mark_as_paid', 'mark_as_overdue']

    def mark_as_paid(self, request, queryset):
        for invoice in queryset:
            if invoice.status != 'paid':
                invoice.mark_paid()
        self.message_user(request, "Selected invoices marked as paid.")
    mark_as_paid.short_description = "Mark selected as paid"

    def mark_as_overdue(self, request, queryset):
        for invoice in queryset:
            invoice.mark_overdue()
        self.message_user(request, "Selected invoices marked as overdue.")
    mark_as_overdue.short_description = "Mark selected as overdue"

@admin.register(Payment, site=admin_site)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_ref', 'invoice', 'amount', 'phone_number', 'status', 'pesapal_order_tracking_id', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('transaction_ref', 'invoice__occupancy__vendor__full_name', 'pesapal_order_tracking_id')

@admin.register(Notification, site=admin_site)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('vendor', 'sent_at', 'sent_via', 'is_delivered')
    list_filter = ('sent_via', 'is_delivered')

@admin.register(IPNLog, site=admin_site)
class IPNLogAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'order_tracking_id', 'merchant_reference', 'processed')
    list_filter = ('processed',)
    search_fields = ('order_tracking_id', 'merchant_reference')