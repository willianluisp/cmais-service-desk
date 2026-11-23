from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Contas"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .branding import ao_entrar

        user_logged_in.connect(ao_entrar, dispatch_uid="portal-marca-no-login")
