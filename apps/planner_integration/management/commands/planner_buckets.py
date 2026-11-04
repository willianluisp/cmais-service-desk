from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.planner_integration.client import (
    GraphClient,
    PlannerError,
    configured_planner_token_provider,
)


class Command(BaseCommand):
    help = "Consulta somente leitura dos buckets do plano configurado; sem --execute não acessa rede."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        if not options["execute"]:
            self.stdout.write("Consulta preparada. Requer autorização Microsoft e --execute; nenhuma chamada realizada.")
            return
        if not settings.PLANNER_PLAN_ID:
            raise CommandError("GRAPH_PLAN_ID ausente.")
        try:
            buckets = GraphClient(token_provider=configured_planner_token_provider()).list_plan_buckets(settings.PLANNER_PLAN_ID)
        except PlannerError as exc:
            raise CommandError(f"Consulta não concluída: {exc.code}") from None
        for name, variable in (
            ("Tarefas pendentes", "PLANNER_BUCKET_ENTRADA_ID"),
            ("Desenvolvendo", "PLANNER_BUCKET_EM_ANDAMENTO_ID"),
            ("Finalizada", "PLANNER_BUCKET_CONCLUIDO_ID"),
        ):
            matches = [bucket for bucket in buckets if bucket["name"].strip().casefold() == name.casefold()]
            if len(matches) == 1:
                self.stdout.write(f"{variable}={matches[0]['id']}")
            else:
                self.stdout.write(f"{variable}: revisão necessária ({len(matches)} buckets com o nome {name}).")
