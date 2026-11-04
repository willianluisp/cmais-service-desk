from celery import shared_task

from .services import process_pending


@shared_task(ignore_result=True)
def process_outbox(limit=50):
    return process_pending(limit=limit)
