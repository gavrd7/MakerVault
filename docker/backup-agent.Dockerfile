FROM postgres:18.6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BACKUP_ROOT=/backups \
    SOURCE_MEDIA_ROOT=/source/media \
    SOURCE_KEY_ROOT=/source/keys \
    SOURCE_CONFIG_ROOT=/source/config \
    BACKUP_AGENT_PORT=9784

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY docker/backup_agent.py /opt/makervault/backup_agent.py
RUN chmod 0555 /opt/makervault/backup_agent.py

ENTRYPOINT ["python3", "/opt/makervault/backup_agent.py"]
CMD ["serve"]
