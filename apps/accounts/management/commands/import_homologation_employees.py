"""Narrow operator-only import of the explicitly approved isolated roster."""
import csv
import getpass
import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import override_settings

from apps.accounts.imports import import_employees

EXCLUDED = {15, 16, 19, 20, 30, 55, *range(56, 70), 74, 79, 80, 81, 82, 85, 86}
SINGLE_NAMES = {"bruna", "flavio", "gerson", "laine", "moacir", "noeli"}


class Command(BaseCommand):
    help = "Prévia do lote aprovado de 72; criação somente no PostgreSQL isolado 8010 e confirmação explícita."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--sha256", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-isolated-8010", action="store_true")

    def handle(self, *args, **options):
        source = Path(options["csv_path"])
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != options["sha256"]:
            raise CommandError("Lote alterado após validação: hash divergente.")
        with source.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        try:
            numbers = [int(row["number"]) for row in rows]
        except (KeyError, ValueError) as exc:
            raise CommandError("Use o arquivo de conferência com a numeração original.") from exc
        if len(rows) != 72 or set(numbers) != set(range(1, 100)) - EXCLUDED:
            raise CommandError("O lote deve conter exclusivamente os 72 números aprovados.")
        if connection.vendor != "postgresql" or connection.settings_dict["NAME"] != "service_desk":
            raise CommandError("Exige o PostgreSQL de homologação service_desk.")
        # This setting is never persisted or exposed through the web. The guard
        # in the importer also checks origin, DEBUG and disabled integrations.
        if settings.PORTAL_BASE_URL != "http://localhost:8010":
            raise CommandError("Origem de homologação inválida.")
        if options["apply"] and not options["confirm_isolated_8010"]:
            raise CommandError("Confirme --confirm-isolated-8010 antes da criação.")
        with override_settings(ISOLATED_HOMOLOGATION_IMPORT_ENABLED=True):
            preview = import_employees(actor=None, rows=rows, initial_password="", single_name_usernames=SINGLE_NAMES)
            if preview["errors"] or preview["existing"]:
                raise CommandError("Há registros inválidos ou existentes; revalide sem alterar contas.")
            if not options["apply"]:
                self.stdout.write(f"Prévia: {preview['ready']} novas contas, nenhuma alteração.")
                return
            password = getpass.getpass("Senha inicial de homologação (entrada oculta): ")
            with transaction.atomic():
                result = import_employees(actor=None, rows=rows, initial_password=password,
                                          single_name_usernames=SINGLE_NAMES, apply=True)
                if result["errors"] or len(result["created"]) != 72:
                    raise CommandError("Lote não concluído integralmente; transação cancelada.")
            self.stdout.write("Importação concluída: 72 contas comuns, troca obrigatória no primeiro acesso.")
