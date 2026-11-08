from django.conf import settings

from .models import PlannerConfiguration, PlannerRuntime

BUCKET_FIELDS = {
    "PLANNER_INTAKE_BUCKET_ID": "Tarefas pendentes → Aberto",
    "PLANNER_IN_PROGRESS_BUCKET_ID": "Desenvolvendo → Em atendimento",
    "PLANNER_COMPLETED_BUCKET_ID": "Finalizada → Resolvido",
}


def bucket_id(field):
    config = PlannerConfiguration.objects.filter(plan_id=selected_plan_id()).first()
    return config.bucket_mapping.get(field, "") if config else getattr(settings, field, "")


def selected_plan_id():
    configured = PlannerRuntime.objects.filter(pk=1).values_list('configuration_id', flat=True).first()
    return configured or settings.PLANNER_PLAN_ID


def automation_enabled(*, synchronize=False):
    if not settings.MICROSOFT_GRAPH_APPROVED:
        return False
    choice = PlannerRuntime.objects.filter(pk=1).values_list('automation_enabled', flat=True).first()
    if choice is not None:
        return choice
    return settings.PLANNER_SYNC_ENABLED if synchronize else settings.PLANNER_ENABLED
