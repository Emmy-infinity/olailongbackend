# serializers.py

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Vendor, Property, Occupancy, Invoice, Payment, Notification, IPNLog


# -------------------------------------------------------------------
# Vendor Serializer (Admin / Full CRUD)
# -------------------------------------------------------------------
class VendorSerializer(serializers.ModelSerializer):
    """
    Serializes all fields of the Vendor model.
    Used for admin/agent operations.
    `photo` is a CloudinaryField, automatically serialized to its URL.
    """
    class Meta:
        model = Vendor
        fields = '__all__'


# -------------------------------------------------------------------
# Vendor Profile Serializer (Customer Self-Service)
# -------------------------------------------------------------------
class VendorProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for the customer's own vendor profile.
    Exposes only fields that the customer should be able to view/update:
    - full_name
    - phone_number (read-only, used for identification)
    - national_id
    - email
    - address
    - photo
    """
    phone_number = serializers.CharField(read_only=True)

    class Meta:
        model = Vendor
        fields = ['id', 'full_name', 'phone_number', 'national_id', 'email', 'address', 'photo']
        read_only_fields = ['phone_number']


# -------------------------------------------------------------------
# Property Serializer
# -------------------------------------------------------------------
class PropertySerializer(serializers.ModelSerializer):
    # Include a read-only computed field for total monthly fee
    total_monthly_fee = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
        help_text="Sum of rent, sanitation, security, and other fees"
    )

    class Meta:
        model = Property
        fields = '__all__'


# -------------------------------------------------------------------
# Occupancy Serializer
# -------------------------------------------------------------------
class OccupancySerializer(serializers.ModelSerializer):
    """
    Serializes Occupancy with additional convenience fields:
    - vendor_name: full name of the vendor
    - vendor_photo: URL of the vendor's photo (safe if missing)
    - vendor_phone_number: phone number of the vendor (for payer prefill)
    - property_code: unique code of the property
    - property_type: human-readable type (Stall/Lockup Shop)
    - property_location: location description of the property
    """
    vendor_name = serializers.CharField(source='vendor.full_name', read_only=True)
    vendor_photo = serializers.SerializerMethodField()
    vendor_phone_number = serializers.CharField(source='vendor.phone_number', read_only=True)
    property_code = serializers.CharField(source='property.code', read_only=True)
    property_type = serializers.CharField(source='property.get_property_type_display', read_only=True)
    property_location = serializers.CharField(source='property.location', read_only=True)

    class Meta:
        model = Occupancy
        fields = [
            'id', 'vendor', 'vendor_name', 'vendor_photo', 'vendor_phone_number',
            'property', 'property_code', 'property_type', 'property_location',
            'start_date', 'end_date', 'is_active'
        ]

    def get_vendor_photo(self, obj):
        """
        Returns the URL of the vendor's photo, or None if no photo exists.
        """
        if obj.vendor.photo:
            return obj.vendor.photo.url
        return None


# -------------------------------------------------------------------
# Invoice Serializer
# -------------------------------------------------------------------
class InvoiceSerializer(serializers.ModelSerializer):
    """
    Serializes Invoice with added vendor_name and property_code.
    """
    vendor_name = serializers.CharField(source='vendor.full_name', read_only=True)
    property_code = serializers.CharField(source='property.code', read_only=True)

    class Meta:
        model = Invoice
        fields = '__all__'


# -------------------------------------------------------------------
# Payment Serializer
# -------------------------------------------------------------------
class PaymentSerializer(serializers.ModelSerializer):
    """
    Serializes all fields of the Payment model.
    """
    class Meta:
        model = Payment
        fields = '__all__'


# -------------------------------------------------------------------
# Notification Serializer
# -------------------------------------------------------------------
class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializes all fields of the Notification model.
    """
    class Meta:
        model = Notification
        fields = '__all__'


# -------------------------------------------------------------------
# IPN Log Serializer
# -------------------------------------------------------------------
class IPNLogSerializer(serializers.ModelSerializer):
    """
    Serializes all fields of the IPNLog model.
    """
    class Meta:
        model = IPNLog
        fields = '__all__'


# -------------------------------------------------------------------
# User Registration Serializer
# -------------------------------------------------------------------
class UserRegisterSerializer(serializers.ModelSerializer):
    """
    Serializer for creating new users (registration).
    - Password is write-only and must be at least 8 characters.
    - Uses `create_user` to hash the password properly.
    """
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = ('username', 'password', 'email', 'first_name', 'last_name')

    def create(self, validated_data):
        """
        Create a new user with hashed password.
        """
        return User.objects.create_user(**validated_data)