from unittest import mock

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(django_user_model):
    return django_user_model.objects.create_user("annie.loren", email="annie@example.test", password="x")


def entrar(client, usuario, retorno=None, erro=None):
    with mock.patch("apps.notifications.recipients.marca", return_value=retorno, side_effect=erro):
        client.force_login(usuario)
    return client.get(reverse("home")).content.decode()


def test_quem_esta_no_grupo_da_solucoes_ve_a_logo_da_solucoes(client, usuario):
    html = entrar(client, usuario, "solucoes")
    assert "brand/csolucoes-logo" in html and 'alt="C+ Soluções Contábeis"' in html and "marca-solucoes" in html
    assert "brand/cmais-logo" not in html


def test_os_demais_veem_a_logo_da_cmais(client, usuario):
    html = entrar(client, usuario, "cmais")
    assert "brand/cmais-logo" in html and "csolucoes-logo" not in html


def test_falha_ao_consultar_o_ad_nao_impede_o_login_e_fica_a_cmais(client, usuario):
    html = entrar(client, usuario, erro=RuntimeError("AD"))
    assert "brand/cmais-logo" in html
    assert client.session["portal_marca"] == "cmais"


def test_antes_do_login_a_logo_e_a_da_cmais(client):
    html = client.get(reverse("login")).content.decode()
    assert "brand/cmais-logo" in html and "csolucoes-logo" not in html
