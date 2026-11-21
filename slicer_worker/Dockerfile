# Experimental shared OrcaSlicer / Creality Print worker wrapper.
# Build only FROM a reviewed image pinned to an exact SHA-256 digest,
# containing Python 3 and individually verified engine executables.
# A verified Creality-only image is valid; Orca is not a dependency.
# This Dockerfile does not fetch or install any slicer binaries.
# Identity checking alone is not proof that a real CLI slice works.
ARG SLICER_ENGINE_IMAGE
FROM ${SLICER_ENGINE_IMAGE}
WORKDIR /opt/makervault-slicer
COPY slicer_worker /opt/makervault-slicer/slicer_worker
USER 10001:10001
ENV PYTHONPATH=/opt/makervault-slicer PYTHONDONTWRITEBYTECODE=1
CMD ["python3", "-m", "slicer_worker.service"]
