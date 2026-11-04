import pytest
from django.conf import settings
from django.urls import clear_url_caches, set_urlconf


@pytest.fixture(autouse=True)
def restore_project_urlconf():
    """Keep route-specific tests from leaking their URLConf into later tests."""
    yield
    settings.ROOT_URLCONF = "config.urls"
    set_urlconf(None)
    clear_url_caches()
