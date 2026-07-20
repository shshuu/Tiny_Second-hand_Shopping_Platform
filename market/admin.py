from django.contrib import admin
from .models import AuditLog, Block, Category, LedgerEntry, Notification, Product, Profile, SecurityEvent, User, Wallet, WalletTransaction

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display=("username","display_name","role","status")
    readonly_fields=("password",)
    def has_add_permission(self, request): return False

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display=("user","balance","public_id")
    readonly_fields=("user","balance","public_id")
    def has_change_permission(self, request, obj=None): return False

@admin.register(WalletTransaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display=("public_id","transaction_type","amount","created_at")
    readonly_fields=("public_id","transaction_type","source","destination","amount","idempotency_key","grant_key","memo","original_transaction","created_by","created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

@admin.register(LedgerEntry)
class LedgerAdmin(admin.ModelAdmin):
    readonly_fields=("transaction","wallet","entry_type","amount","balance_before","balance_after","created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

for model in (Profile, Block, Category, Product, Notification, SecurityEvent): admin.site.register(model)

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display=("created_at","actor","action","target")
    readonly_fields=("actor","action","target","reason","created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
