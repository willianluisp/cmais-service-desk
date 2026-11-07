import pytest
from django.conf import settings
from django.urls import clear_url_caches, set_urlconf


@pytest.fixture
def intake_data():
    """Explicit official-sector fixture for intake tests; never seeds an application DB."""
    from apps.sectors.models import Sector

    sector = Sector.objects.create(name="Setor fictício para testes de abertura")
    return {"sector": sector.pk, "service_location": "Sala fictícia de testes"}


@pytest.fixture(autouse=True)
def restore_project_urlconf():
    """Keep route-specific tests from leaking their URLConf into later tests."""
    yield
    settings.ROOT_URLCONF = "config.urls"
    set_urlconf(None)
    clear_url_caches()
