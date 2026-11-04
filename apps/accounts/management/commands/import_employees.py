import csv
import json
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.imports import import_employees


class Command(BaseCommand):
    help = "Pré-valida CSV full_name,email,username; --apply exige saída privada."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--credentials-output")

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"], is_superuser=True, is_active=True)
        except get_user_model().DoesNotExist:
            raise CommandError("Administrador autorizado não encontrado.") from None
        with open(options["csv_path"], encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        preview = import_employees(actor=actor, rows=rows)
        if preview["errors"]:
            raise CommandError(json.dumps(preview["errors"], ensure_ascii=False))
        if not options["apply"]:
            self.stdout.write(f"Prévia: {preview['ready']} linhas válidas; {preview['existing']} existentes.")
            return
        if not options["credentials_output"]:
            raise CommandError("Informe --credentials-output em diretório privado fora do Git.")
        target = Path(options["credentials_output"]).resolve()
        if target.is_relative_to(settings.BASE_DIR):
            raise CommandError("A saída de credenciais deve ficar fora do projeto.")
        descriptor = os.open(options["credentials_output"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            with transaction.atomic():
                result = import_employees(actor=actor, rows=rows, apply=True)
                if result["errors"]:
                    raise CommandError("Conflitos detectados; execute a prévia novamente.")
                json.dump(result["created"], output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
        self.stdout.write(f"Importação concluída: {len(result['created'])} contas novas; senhas somente na saída privada.")
