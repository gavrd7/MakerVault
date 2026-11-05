# Build only with a reviewed, SHA-256 digest-pinned engine image that
# contains Python 3 and a verified PrusaSlicer CLI binary.
# No binary is installed by the MakerVault application or this Dockerfile.
ARG SLICER_ENGINE_IMAGE
FROM ${SLICER_ENGINE_IMAGE}
WORKDIR /opt/makervault-slicer
COPY slicer_worker /opt/makervault-slicer/slicer_worker
USER 10001:10001
ENV PYTHONPATH=/opt/makervault-slicer PYTHONDONTWRITEBYTECODE=1
CMD ["python3", "-m", "slicer_worker.service"]
