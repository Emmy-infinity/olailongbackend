# models.py

from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User          # <-- Added for vendor-user link (customer self-service)
from cloudinary.models import CloudinaryField
import uuid

# Shared phone number validator (Uganda format)
phone_regex = RegexValidator(
    regex=r'^\+?256\d{9}$',
    message="Phone number must be in format: '+256XXXXXXXXX' (Uganda)"
)

class Vendor(models.Model):
    full_name = models.CharField(max_length=100)
    phone_number = models.CharField(validators=[phone_regex], max_length=13, unique=True)
    national_id = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    photo = CloudinaryField('photo', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # NEW: Link vendor to a Django user account for customer self-service.
    # Nullable so existing vendor records remain unaffected.
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendor_profile',
        help_text="Linked user account for customer self-service"
    )

    class Meta:
        ordering = ['full_name']
        indexes = [models.Index(fields=['is_active'])]

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"


class Property(models.Model):
    PROPERTY_TYPES = (
        ('stall', 'Stall'),
        ('lockup', 'Lockup Shop'),
    )
    code = models.CharField(max_length=20, unique=True)
    property_type = models.CharField(max_length=10, choices=PROPERTY_TYPES)
    location = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    # Monthly fees (all amounts in UGX)
    rent_fee = models.DecimalField(max_digits=10, decimal_places=2)
    sanitation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    security_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['property_type']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.code} ({self.get_property_type_display()})"

    @property
    def total_monthly_fee(self):
        """Total monthly charge for this property."""
        return self.rent_fee + self.sanitation_fee + self.security_fee + self.other_fee


class Occupancy(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name='occupancies')
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name='occupancies')
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Occupancies"
        constraints = [
            models.UniqueConstraint(
                fields=['property'],
                condition=models.Q(is_active=True),
                name='unique_active_occupancy_per_property'
            )
        ]
        indexes = [models.Index(fields=['is_active'])]

    def __str__(self):
        return f"{self.vendor.full_name} → {self.property.code} ({self.start_date} - {self.end_date or 'Present'})"

    def clean(self):
        """Validate that end_date is after start_date (if provided)."""
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")
        if not self.start_date:
            raise ValidationError("Start date is required.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Invoice(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    )
    occupancy = models.ForeignKey(Occupancy, on_delete=models.PROTECT, related_name='invoices')
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    due_date = models.DateField()

    rent_amount = models.DecimalField(max_digits=10, decimal_places=2)
    sanitation_amount = models.DecimalField(max_digits=10, decimal_places=2)
    security_amount = models.DecimalField(max_digits=10, decimal_places=2)
    other_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-billing_period_start']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['due_date']),
            models.Index(fields=['status', 'due_date']),
        ]

    def __str__(self):
        return f"Invoice #{self.id} - {self.occupancy.vendor.full_name}"

    @property
    def vendor(self):
        """Convenience accessor for vendor."""
        return self.occupancy.vendor

    @property
    def property(self):
        """Convenience accessor for property."""
        return self.occupancy.property

    def clean(self):
        if self.billing_period_end < self.billing_period_start:
            raise ValidationError("Billing period end cannot be before start.")

    def save(self, *args, **kwargs):
        # Recalculate total amount from components
        self.amount = (
            self.rent_amount + self.sanitation_amount +
            self.security_amount + self.other_amount
        )
        self.full_clean()
        super().save(*args, **kwargs)

    def mark_paid(self):
        self.status = 'paid'
        self.paid_at = timezone.now()
        self.save(update_fields=['status', 'paid_at', 'amount'])

    def mark_overdue(self):
        if self.status == 'pending' and timezone.now().date() > self.due_date:
            self.status = 'overdue'
            self.save(update_fields=['status', 'amount'])

    def mark_cancelled(self):
        self.status = 'cancelled'
        self.save(update_fields=['status', 'amount'])

    @classmethod
    def mark_all_overdue(cls):
        """Bulk-mark all pending invoices past their due date as overdue."""
        return cls.objects.filter(
            status='pending',
            due_date__lt=timezone.now().date()
        ).update(status='overdue')


class Payment(models.Model):
    PAYMENT_STATUS = (
        ('initiated', 'Initiated'),
        ('pending', 'Pending'),
        ('successful', 'Successful'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    # transaction_ref is shared across batch payments, so not unique.
    transaction_ref = models.CharField(max_length=100, default=uuid.uuid4)
    pesapal_order_tracking_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(validators=[phone_regex], max_length=13)
    status = models.CharField(max_length=10, choices=PAYMENT_STATUS, default='initiated')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status'])]

    def __str__(self):
        return f"Payment {self.transaction_ref} - {self.amount} UGX ({self.status})"

    def mark_successful(self):
        """Mark payment successful and, if it covers the invoice, mark invoice paid."""
        from django.db import transaction
        with transaction.atomic():
            self.status = 'successful'
            self.save(update_fields=['status', 'updated_at'])
            if self.amount >= self.invoice.amount:
                self.invoice.mark_paid()


class Notification(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    sent_via = models.CharField(max_length=20, default='sms', choices=(('sms', 'SMS'), ('email', 'Email')))
    sent_at = models.DateTimeField(auto_now_add=True)
    is_delivered = models.BooleanField(default=False)

    class Meta:
        ordering = ['-sent_at']
        indexes = [models.Index(fields=['vendor', 'sent_at'])]

    def __str__(self):
        return f"Notification to {self.vendor.full_name} at {self.sent_at}"


class IPNLog(models.Model):
    received_at = models.DateTimeField(auto_now_add=True)
    payload = models.TextField()
    order_tracking_id = models.CharField(max_length=100, blank=True, null=True)
    merchant_reference = models.CharField(max_length=100, blank=True, null=True)
    processed = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"IPN {self.received_at} - {self.order_tracking_id}"