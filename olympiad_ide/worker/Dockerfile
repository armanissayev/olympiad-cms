# Build artifact only. Production recommendation: install isolate + this controller in a dedicated Linux VM.
# No Docker socket, host filesystem, or privileged runtime shortcut is supplied.
FROM python:3.12-bookworm
ARG ISOLATE_REVISION
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ openjdk-17-jdk-headless libcap-dev libseccomp-dev libsystemd-dev pkg-config make git ca-certificates && apt-get clean
RUN test -n "$ISOLATE_REVISION" && test "${#ISOLATE_REVISION}" = 40 && git clone https://github.com/ioi/isolate.git /opt/isolate-src && cd /opt/isolate-src && git checkout --detach "$ISOLATE_REVISION" && make install
WORKDIR /opt/olympiad
COPY backend/pyproject.toml /opt/backend-package/pyproject.toml
COPY backend/app /opt/backend-package/app
RUN pip install --no-cache-dir /opt/backend-package && useradd --uid 1000 --create-home olympiad
COPY worker ./worker
ENV PYTHONPATH=/opt/olympiad
USER 1000:1000
CMD ["python", "-m", "worker.app.main"]
