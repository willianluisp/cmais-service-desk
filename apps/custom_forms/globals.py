import re
import unicodedata


def global_kind(field):
    label = field.get("label", "")
    if not isinstance(label, str):
        return None
    label = unicodedata.normalize("NFKD", label)
    label = "".join(c for c in label if not unicodedata.combining(c))
    label = re.sub(r"[^a-z0-9 ]", "", label.casefold()).strip()
    if label in {"em qual setor voce trabalha", "setor do colaborador", "setor", "departamento", "setor do solicitante"}:
        return "sector"
    if label in {"onde o atendimento devera ser realizado", "localizacao do atendimento", "local de atendimento", "localizacao", "local do atendimento"}:
        return "service_location"
    return None
