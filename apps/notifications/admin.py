from django.contrib import admin
from django.utils import timezone

from .models import NotificationOutbox


@admin.register(NotificationOutbox)
class NotificationOutboxAdmin(admin.ModelAdmin):
    list_display = ["id", "ticket", "state", "attempts", "available_at", "last_error_code"]
    list_filter = ["state"]
    readonly_fields = [field.name for field in NotificationOutbox._meta.fields]
    actions = ["requeue_failed"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Reprocessar notificações com falha", permissions=["change"])
    def requeue_failed(self, request, queryset):
        count = queryset.filter(state=NotificationOutbox.State.FAILED).update(
            state=NotificationOutbox.State.PENDING,
            attempts=0,
            available_at=timezone.now(),
            last_error_code="",
        )
        self.message_user(request, f"{count} notificações reenfileiradas.")
