from unittest import mock

import pytest
from django.utils import timezone

from apps.accounts.directory import DirectoryUnavailable
from apps.notifications.models import NotificationOutbox
from apps.notifications.services import enqueue_event, process_pending
from apps.tickets.models import Category, Ticket, TicketEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def ad(settings):
    settings.LDAP_ENABLED, settings.LDAP_ROLE_SOURCE = True, "portal"
    settings.NOTIFICATIONS_TI_RECIPIENTS = ["ti.chamados@example.test"]
    settings.PORTAL_BASE_URL = "https://chamados.example.test"


@pytest.fixture
def evento(django_user_model):
    user = django_user_model.objects.create_user("maria.souza", email="antigo@pessoal.test")
    ticket = Ticket.objects.create(number="C+2026-000070", requester=user, title="Teste", description="x",
                                   category=Category.objects.create(name="TI"))
    return TicketEvent.objects.create(ticket=ticket, event_type="CREATED", summary="", detected_at=timezone.now())


def conta(mail=b"maria.souza@empresa.test", uac=b"512"):
    return [("CN=Maria,OU=Usuarios,DC=x", {"mail": [mail], "userAccountControl": [uac], "sAMAccountName": [b"maria.souza"]})]


def enfileirar(evento, retorno=None, erro=None):
    with mock.patch("apps.accounts.directory.lookup_login", return_value=retorno, side_effect=erro) as busca:
        enqueue_event(evento)
    return busca


def test_email_vem_do_ad_pelo_login_de_quem_abriu(ad, evento):
    busca = enfileirar(evento, conta())
    busca.assert_called_once_with("maria.souza")
    aviso = NotificationOutbox.objects.get()
    assert aviso.recipient == "maria.souza@empresa.test" and aviso.template_key == "ticket-event-v1"
    provider = mock.Mock()
    process_pending(provider=provider)  # e-mail do AD diferente do cadastro não é "destinatário alterado"
    provider.assert_called_once()


@pytest.mark.parametrize("retorno, motivo", [
    ([], "não foi encontrado no AD"),
    (conta(uac=b"514"), "está desativada no AD"),
    (conta(mail=b""), "não tem e-mail preenchido no AD"),
])
def test_sem_destinatario_avisa_a_ti_com_o_motivo(ad, evento, retorno, motivo):
    enfileirar(evento, retorno)
    alerta = NotificationOutbox.objects.get()
    assert alerta.recipient == "ti.chamados@example.test" and alerta.template_key == "alerta-destinatario-v1"
    assert motivo in alerta.body_text and "maria.souza" in alerta.body_text
    assert "e-mail do solicitante não encontrado" in alerta.subject
    provider = mock.Mock()
    process_pending(provider=provider)
    provider.assert_called_once()


def test_ad_fora_do_ar_usa_o_email_do_cadastro(ad, evento):
    enfileirar(evento, erro=DirectoryUnavailable("fora"))
    assert NotificationOutbox.objects.get().recipient == "antigo@pessoal.test"


def test_sem_login_pelo_ad_continua_o_cadastro(evento, settings):
    settings.LDAP_ENABLED = False
    busca = enfileirar(evento, conta())
    busca.assert_not_called()
    assert NotificationOutbox.objects.get().recipient == "antigo@pessoal.test"


class _Conexao:
    def __init__(self, achados):
        self.achados, self.filtros = achados, []

    def search_s(self, base, escopo, filtro, atributos):
        self.filtros.append(filtro)
        return self.achados


def _marca(settings, achados):
    from contextlib import contextmanager

    from apps.notifications.recipients import marca

    conexao = _Conexao(achados)

    @contextmanager
    def falsa():
        yield conexao

    with mock.patch("apps.accounts.directory.directory_connection", falsa):
        return marca(type("U", (), {"username": "maria.souza"})()), conexao


GRUPO = "CN=GRP_Empresa_Solucoes,OU=Grupos,OU=CMAIS,DC=cmais,DC=local"


def test_marca_solucoes_pelo_grupo_do_ad_inclusive_subgrupos(ad, settings):
    settings.EMAIL_SOLUCOES_GROUP_DN = GRUPO
    settings.AUTH_LDAP_USER_SEARCH_BASE = "OU=CMAIS,DC=cmais,DC=local"
    resultado, conexao = _marca(settings, [("CN=Maria", {})])
    assert resultado == "solucoes"
    assert "memberOf:1.2.840.113556.1.4.1941:=" + GRUPO in conexao.filtros[0] and "sAMAccountName=maria.souza" in conexao.filtros[0]
    assert _marca(settings, [])[0] == "cmais"
    assert _marca(settings, [(None, ["ldap://referral"])])[0] == "cmais"


def test_sem_grupo_configurado_ou_sem_ad_fica_a_marca_da_cmais(settings, ad):
    settings.EMAIL_SOLUCOES_GROUP_DN = ""
    assert _marca(settings, [("CN=Maria", {})])[0] == "cmais"
    settings.EMAIL_SOLUCOES_GROUP_DN, settings.LDAP_ENABLED = GRUPO, False
    assert _marca(settings, [("CN=Maria", {})])[0] == "cmais"


def test_layout_da_solucoes_usa_a_logo_e_o_azul_dela(evento, settings):
    from apps.notifications.email_layout import montar
    from apps.notifications.services import _inline_attachments

    _, _, html = montar(evento.ticket, "ABERTO", timezone.now(), marca="solucoes")
    assert 'src="cid:logo-solucoes"' in html and "cid:logo-cmais" not in html and "#007fc1" in html and "#94c11f" not in html
    anexo, = _inline_attachments(html)
    assert anexo["contentId"] == "logo-solucoes" and anexo["name"] == "logo-solucoes.png"
    _, _, html = montar(evento.ticket, "ABERTO", timezone.now())
    assert 'src="cid:logo-cmais"' in html and "#94c11f" in html
