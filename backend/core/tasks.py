from celery import shared_task


@shared_task
def ping_worker():
    return {"status": "ok", "worker": "makervault"}
