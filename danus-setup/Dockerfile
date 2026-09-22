FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git procps xz-utils \
    texlive-latex-base texlive-latex-recommended texlive-latex-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/danus
COPY danus-setup/Danus/ /opt/danus/
COPY danus-setup/codex-danus.env /opt/danus/config/codex.env
COPY danus-setup/danus.env /opt/danus/config/danus.env
COPY webui/ /opt/webui/
COPY danus-setup/start.sh /opt/start.sh

# Windows Git may check out shell files with CRLF line endings.
RUN find /opt/danus/scripts /opt/danus/bin -type f -exec sed -i 's/\r$//' {} + \
    && find /opt/danus/.agents /opt/danus/agents -type f -name '*.sh' -exec sed -i 's/\r$//' {} + \
    && sed -i 's/\r$//' /opt/start.sh /opt/danus/config/codex.env /opt/danus/config/danus.env \
    && chmod +x /opt/start.sh /opt/danus/bin/* \
    && python -m compileall -q /opt/webui /opt/danus/danus

EXPOSE 7860
CMD ["bash", "/opt/start.sh"]
