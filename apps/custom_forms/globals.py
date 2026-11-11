import re
import unicodedata


def is_priority_question(field):
    if field.get('type') == 'priority':
        return True
    label = unicodedata.normalize('NFKD', field.get('label', ''))
    label = ''.join(c for c in label if not unicodedata.combining(c))
    label = re.sub(r'[^a-z0-9 ]', '', label.casefold()).strip()
    return bool(re.fullmatch(r'(?:qual (?:e )?(?:a |o )?)?(?:nivel de |grau de )?(?:prioridade|urgencia)(?: do chamado| da solicitacao| deste chamado| deste pedido)?', label))


def is_subject(field):
    """Explicit subject type, plus the equivalent manually configured legacy text field."""
    return field.get('type') == 'subject' or (
        field.get('type') == 'short_text' and field.get('label', '').strip().casefold() == 'assunto')


def subject_fields(fields):
    """An explicit subject wins over a legacy text question without rewriting schemas."""
    return [field for field in fields if field.get('type') == 'subject'] or [field for field in fields if is_subject(field)]


def global_kind(field):
    label = field.get("label", "")
    if not isinstance(label, str):
        return None
    label = unicodedata.normalize("NFKD", label)
    label = "".join(c for c in label if not unicodedata.combining(c))
    label = re.sub(r"[^a-z0-9 ]", "", label.casefold()).strip()
    if label in {"em qual setor voce trabalha", "setor do colaborador", "setor", "departamento", "setor do solicitante"}:
        return "sector"
    return None
