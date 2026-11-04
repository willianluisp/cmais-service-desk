from django.conf import settings

from .models import PlannerConfiguration

BUCKET_FIELDS = {
    "PLANNER_INTAKE_BUCKET_ID": "Tarefas pendentes → Aberto",
    "PLANNER_IN_PROGRESS_BUCKET_ID": "Desenvolvendo → Em atendimento",
    "PLANNER_COMPLETED_BUCKET_ID": "Finalizada → Resolvido",
}


def bucket_id(field):
    config = PlannerConfiguration.objects.filter(plan_id=settings.PLANNER_PLAN_ID).first()
    return config.bucket_mapping.get(field, "") if config else getattr(settings, field, "")
