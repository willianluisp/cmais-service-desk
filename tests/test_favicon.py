from html.parser import HTMLParser

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import RequestFactory
from whitenoise.middleware import WhiteNoiseMiddleware

from apps.accounts.models import LocalAccount
from apps.tickets.models import Category, Ticket


class HeadLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'link':
            self.links.append(dict(attrs))


def assert_official_favicon(response):
    assert response.status_code == 200
    links = HeadLinks(response.content.decode()).links
    icons = [link for link in links if link.get('rel') in ('icon', 'apple-touch-icon')]
    assert len(icons) == 4
    assert {(link['rel'], link.get('type'), link.get('sizes'), link['href']) for link in icons} == {
        ('icon', 'image/x-icon', None, '/static/brand/cmais-favicon.ico'),
        ('icon', 'image/png', '32x32', '/static/brand/cmais-favicon-32.png'),
        ('icon', 'image/svg+xml', 'any', '/static/brand/cmais-icone.svg'),
        ('apple-touch-icon', None, '180x180', '/static/brand/cmais-touch-180.png'),
    }


@pytest.mark.parametrize('url', ['/', '/login/', '/conta/recuperar/', '/conta/recuperar/enviado/'])
def test_public_pages_use_official_favicon(client, url):
    assert_official_favicon(client.get(url))


@pytest.mark.django_db
def test_admin_and_portal_templates_inherit_official_favicon(client, django_user_model):
    manager = django_user_model.objects.create_user('willian.pedroso')
    manager.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    user = django_user_model.objects.create_user('favicon.synthetic')
    ticket = Ticket.objects.create(number='FAVICON-SYNTHETIC', requester=user,
                                   title='Teste fictício', description='Teste',
                                   category=Category.objects.create(name='Favicon'))
    client.force_login(manager)
    for url in ('/', '/admin/', '/admin/auth/', '/admin/auth/user/', '/admin/auth/user/add/',
                f'/admin/auth/user/{user.pk}/change/', f'/admin/auth/user/{user.pk}/history/',
                f'/admin/auth/user/{user.pk}/password/', f'/admin/auth/user/{user.pk}/delete/',
                '/chamados/', '/chamados/novo/', f'/chamados/{ticket.pk}/', '/integracoes/',
                '/chamados/arquivados/'):
        assert_official_favicon(client.get(url))
    LocalAccount.objects.create(user=user, must_change_password=True)
    client.force_login(user)
    assert_official_favicon(client.get('/conta/senha/'))
    user.local_account.must_change_password = False
    user.local_account.save()
    assert_official_favicon(client.get('/conta/senha/'))


@pytest.mark.django_db
def test_collected_favicons_are_served_by_whitenoise(settings, tmp_path):
    settings.STATIC_ROOT = tmp_path / 'collected-static'
    settings.STORAGES = {
        **settings.STORAGES,
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    }
    settings.DEBUG = False
    call_command('collectstatic', interactive=False, verbosity=0)
    middleware = WhiteNoiseMiddleware(lambda request: pytest.fail('Static file was not served'))
    from django.contrib.staticfiles.storage import staticfiles_storage

    for filename, content_type, signature in [
        ('cmais-icone.svg', 'image/svg+xml', b'<svg'),
        ('cmais-favicon.ico', 'image/x-icon', b'\x00\x00\x01\x00'),
        ('cmais-favicon-32.png', 'image/png', b'\x89PNG\r\n\x1a\n'),
        ('cmais-touch-180.png', 'image/png', b'\x89PNG\r\n\x1a\n'),
    ]:
        url = staticfiles_storage.url(f'brand/{filename}')
        assert url != f'/static/brand/{filename}'  # Production uses the content hash.
        response = middleware(RequestFactory().get(url))
        assert response.status_code == 200
        assert response['Content-Type'].split(';')[0] in (
            {content_type, 'image/vnd.microsoft.icon'} if filename.endswith('.ico') else {content_type}
        )
        try:
            assert b''.join(response.streaming_content).startswith(signature)
        finally:
            response.close()
