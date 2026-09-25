# SVRF container: python, git and the GitHub CLI. The gate's own toolchain (compilers,
# test runners) goes in through EXTRA_APT_PACKAGES, or by building FROM this image.
#
#   docker build -t svrf .
#   docker build -t svrf --build-arg EXTRA_APT_PACKAGES="build-essential nodejs npm" .
FROM python:3.12-slim

ARG EXTRA_APT_PACKAGES=""
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates gnupg ${EXTRA_APT_PACKAGES} \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE NOTICE /opt/svrf/
COPY src /opt/svrf/src
RUN pip install --no-cache-dir /opt/svrf && useradd --create-home --uid 1000 svrf \
 && mkdir -p /var/lib/svrf /config && chown svrf /var/lib/svrf /config
COPY docker/entrypoint.sh /usr/local/bin/svrf-entrypoint
USER svrf
VOLUME ["/var/lib/svrf"]
ENV SVRF_CONFIG=/config/svrf.toml
ENTRYPOINT ["svrf-entrypoint"]
CMD ["watch"]
