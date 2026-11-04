FROM python:3.12-slim-bookworm AS builder
ARG INSTALL_LDAP=false
WORKDIR /build
COPY requirements.lock requirements-ldap.lock ./
RUN if [ "$INSTALL_LDAP" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        build-essential libldap2-dev libsasl2-dev libssl-dev \
      && rm -rf /var/lib/apt/lists/*; \
    fi \
    && python -m pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.lock \
    && if [ "$INSTALL_LDAP" = "true" ]; then \
      python -m pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements-ldap.lock; \
    fi

FROM python:3.12-slim-bookworm AS runtime
ARG INSTALL_LDAP=false
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production
WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.lock /tmp/requirements.lock
COPY requirements-ldap.lock /tmp/requirements-ldap.lock
RUN if [ "$INSTALL_LDAP" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        libldap-2.5-0 libsasl2-2 \
      && rm -rf /var/lib/apt/lists/*; \
    fi \
    && python -m pip install --no-cache-dir --no-index --find-links=/wheels -r /tmp/requirements.lock \
    && if [ "$INSTALL_LDAP" = "true" ]; then \
      python -m pip install --no-cache-dir --no-index --find-links=/wheels -r /tmp/requirements-ldap.lock; \
    fi \
    && rm -rf /wheels \
    && groupadd --gid 10001 portal \
    && useradd --uid 10001 --gid portal --create-home portal
COPY --chown=portal:portal . /app
RUN mkdir -p /app/media /app/run /app/staticfiles \
    && chown -R portal:portal /app/media /app/run /app/staticfiles
USER 10001:10001
# collectstatic usa configuração de build sem segredo ou dependências externas.
RUN python manage.py collectstatic --noinput --verbosity 0 --settings=config.settings.build
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", "--error-logfile", "-"]
