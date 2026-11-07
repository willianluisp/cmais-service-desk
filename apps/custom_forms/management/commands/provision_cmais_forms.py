"""Explicitly provision missing templates, preserving all existing definitions."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AccountAudit
from apps.accounts.permissions import is_portal_admin
from apps.custom_forms.models import FormDefinition
from apps.custom_forms.presets import get_cmais_presets
from apps.custom_forms.schema import validate_fields


class Command(BaseCommand):
    help = "Cria somente os rascunhos C+ ausentes; use --dry-run para revisar antes de executar."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True, help="Login do administrador responsável pela auditoria.")
        parser.add_argument("--dry-run", action="store_true", help="Exibe os rascunhos ausentes sem gravar dados.")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
        except get_user_model().DoesNotExist:
            raise CommandError("O administrador informado não existe.") from None
        if not is_portal_admin(actor):
            raise CommandError("O ator deve ser um administrador ativo (ADMIN_PORTAL ou superusuário).")

        created_count = 0
        missing_count = 0
        for index, preset in enumerate(get_cmais_presets(), start=1):
            key = preset["provision_key"]
            if FormDefinition.objects.filter(provision_key=key).exists():
                self.stdout.write(f"Preservado: {key}")
                continue
            fields = validate_fields(preset["fields"])
            missing_count += 1
            if options["dry_run"]:
                self.stdout.write(f"Criaria rascunho: {preset['title']} ({key})")
                continue
            defaults = {
                **preset, "fields": fields, "display_order": index * 10,
                "status": FormDefinition.Status.DRAFT, "published_version": 0,
                "published_snapshot": {}, "draft_audience": [], "draft_approver_groups": [],
                "audience_restricted": preset["is_sensitive"],
            }
            defaults.pop("provision_key")
            definition, created = FormDefinition.objects.get_or_create(provision_key=key, defaults=defaults)
            if created:
                AccountAudit.objects.create(actor=actor, action="FORM_PROVISIONED", changes={
                    "form_id": str(definition.pk), "provision_key": key,
                    "revision": definition.revision, "version": definition.published_version,
                })
                created_count += 1
                self.stdout.write(f"Criado rascunho: {definition.title} ({key})")
        if options["dry_run"]:
            self.stdout.write(f"Simulação: {missing_count} rascunho(s) ausente(s). Nenhuma gravação realizada.")
        else:
            self.stdout.write(self.style.SUCCESS(f"{created_count} rascunho(s) criado(s). Nenhum formulário publicado."))
