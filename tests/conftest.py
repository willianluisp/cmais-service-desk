import pytest
from django.conf import settings
from django.urls import clear_url_caches, set_urlconf


@pytest.fixture
def intake_data():
    """Explicit official-sector fixture for intake tests; never seeds an application DB."""
    from apps.sectors.models import Company, Sector

    sector = Sector.objects.create(name="Setor fictício para testes de abertura")
    company = Company.objects.create(name="Empresa fictícia exclusiva dos testes")
    return {"company": company.pk, "sector": sector.pk, "service_location": "Sala fictícia de testes"}


@pytest.fixture
def manual_support(django_user_model):
    """Explicitly configured questions; the application never seeds them."""
    import uuid

    from apps.custom_forms.models import FormDefinition
    from apps.custom_forms.services import publish_form

    actor = django_user_model.objects.create_superuser("manual-support-admin", password="test")
    fields = [{"id": str(uuid.uuid4()), "type": kind, "label": label, "required": True,
               "help_text": "", "placeholder": "", "options": [], "default": ""}
              for kind, label in [("long_text", "Descrição"), ("attachment", "Evidência")]]
    definition = FormDefinition.objects.create(title="Suporte técnico", provision_key="support", fields=fields)
    return publish_form(actor=actor, form_id=definition.pk, revision=definition.revision)


@pytest.fixture(autouse=True)
def restore_project_urlconf():
    """Keep route-specific tests from leaking their URLConf into later tests."""
    yield
    settings.ROOT_URLCONF = "config.urls"
    set_urlconf(None)
    clear_url_caches()
