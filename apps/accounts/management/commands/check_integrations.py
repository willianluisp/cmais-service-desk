from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Verifica presença de configuração; não abre conexão corporativa."

    def handle(self, *args, **options):
        groups = {
            "Graph": ["GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET"],
            "Planner": ["PLANNER_PLAN_ID", "PLANNER_INTAKE_BUCKET_ID", "PORTAL_BASE_URL"],
            "Outlook": ["GRAPH_MAILBOX_ID"],
        }
        for name, keys in groups.items():
            missing = [key for key in keys if not getattr(settings, key, "")]
            self.stdout.write(f"{name}: " + ("faltam " + ", ".join(missing) if missing else "campos presentes; requer homologação real"))
        for key in ["LOCAL_AUTH_ENABLED", "LDAP_ENABLED", "MICROSOFT_GRAPH_APPROVED", "PLANNER_ENABLED", "EMAIL_ENABLED"]:
            self.stdout.write(f"{key}: {bool(getattr(settings, key, False))}")
