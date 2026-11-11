"""Bounded, inert schemas: no expressions, HTML, model attributes or executable rules."""
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

FIELD_TYPES = {
    "subject": "Assunto", "priority": "Prioridade",
    "short_text": "Texto curto", "long_text": "Texto longo", "number": "Número",
    "date": "Data", "select": "Seleção única", "multiple": "Múltipla escolha",
    "checkbox": "Checkbox", "attachment": "Anexo", "integer": "Inteiro positivo",
    "sector": "Setor oficial", "datetime": "Data e hora",
}
ICONS = {"support": "◈", "access": "⌘", "people": "♧", "document": "▤", "equipment": "▣", "request": "＋"}


def text(value, name, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValidationError(f"{name}: informe um texto válido de até {limit} caracteres.")
    return value.strip()


def validate_fields(value):
    if not isinstance(value, list) or len(value) > 40:
        raise ValidationError("Use no máximo 40 campos por formulário.")
    result, identifiers = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ValidationError("Estrutura de campo inválida.")
        try:
            identifier = str(uuid.UUID(item.get("id", "")))
        except (ValueError, TypeError, AttributeError):
            raise ValidationError("Identificador de campo inválido.") from None
        if identifier in identifiers:
            raise ValidationError("Cada campo precisa ter um identificador exclusivo.")
        identifiers.add(identifier)
        kind = item.get("type")
        if not isinstance(kind, str) or kind not in FIELD_TYPES or not isinstance(item.get("required"), bool):
            raise ValidationError("Tipo ou obrigatoriedade de campo inválidos.")
        label = text(item.get("label"), "Nome do campo", 160, required=True)
        help_text = text(item.get("help_text", ""), label, 500)
        placeholder = text(item.get("placeholder", ""), label, 160)
        options = item.get("options", [])
        if not isinstance(options, list) or len(options) > 50:
            raise ValidationError(f"{label}: use no máximo 50 opções.")
        options = [text(option, label, 120, required=True) for option in options]
        if len(set(options)) != len(options):
            raise ValidationError(f"{label}: as opções não podem se repetir.")
        if kind in ("select", "multiple"):
            if not options:
                raise ValidationError(f"{label}: adicione pelo menos uma opção.")
        elif options:
            raise ValidationError(f"{label}: este tipo de campo não aceita opções.")
        default = item.get("default", "")
        if kind == "multiple":
            default = [] if default in ("", None) else default
            if not isinstance(default, list) or any(not isinstance(v, str) or v not in options for v in default):
                raise ValidationError(f"{label}: valor padrão fora das opções.")
            if len(default) != len(set(default)):
                raise ValidationError(f"{label}: valor padrão repetido.")
        elif kind == "checkbox":
            default = False if default in ("", None) else default
            if not isinstance(default, bool):
                raise ValidationError(f"{label}: valor padrão deve ser verdadeiro ou falso.")
        else:
            default = text(default if default is not None else "", label, 10000 if kind == "long_text" else 160 if kind == "subject" else 255)
            if kind == 'priority' and default:
                from apps.tickets.models import Ticket

                if default not in Ticket.Priority.values:
                    raise ValidationError(f"{label}: prioridade padrão inválida.")
            if kind == "select" and default and default not in options:
                raise ValidationError(f"{label}: valor padrão fora das opções.")
            if kind == "attachment" and default:
                raise ValidationError("Anexos não aceitam valor padrão.")
            if kind == "sector" and default:
                raise ValidationError("Selecione o setor durante o preenchimento; este campo não aceita padrão fixo.")
            if kind == "integer" and default:
                try:
                    if not 1 <= int(default) <= 2147483647:
                        raise ValueError
                except ValueError:
                    raise ValidationError(f"{label}: informe um inteiro positivo válido.") from None
            if kind == "datetime" and default:
                try:
                    if "T" not in default:
                        raise ValueError
                    datetime.strptime(default, "%Y-%m-%dT%H:%M")
                except ValueError:
                    raise ValidationError(f"{label}: data e hora padrão inválidas.") from None
            if kind == "number" and default:
                try:
                    number = Decimal(default)
                    if not number.is_finite() or abs(number) >= Decimal("100000000000000") or number.as_tuple().exponent < -4:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    raise ValidationError(f"{label}: número padrão inválido (até 14 inteiros e 4 casas decimais).") from None
            if kind == "date" and default:
                try:
                    date.fromisoformat(default)
                except ValueError:
                    raise ValidationError(f"{label}: data padrão inválida.") from None
        result.append({"id": identifier, "type": kind, "label": label, "required": item["required"],
                       "help_text": help_text, "placeholder": placeholder, "options": options, "default": default})
    if sum(field["type"] == "attachment" for field in result) > 5:
        raise ValidationError("Use no máximo cinco campos de anexo por formulário.")
    for kind in ('subject', 'priority'):
        if sum(field['type'] == kind for field in result) > 1:
            raise ValidationError(f"Use apenas um campo {FIELD_TYPES[kind]} por formulário.")
    return result
