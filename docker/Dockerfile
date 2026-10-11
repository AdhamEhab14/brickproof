# BrickProof with Renode, ready to run:
#
#   docker build -f docker/Dockerfile -t brickproof .
#   docker run --rm brickproof                         # the bundled demo
#   docker run --rm -v "$PWD:/work" brickproof run adapter.yaml --html report.html
#
FROM python:3.12-slim

ARG RENODE_VERSION=1.17.0

# the portable Renode build brings its own runtime; it still wants ICU and zlib from the system
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libicu-dev zlib1g \
    && mkdir -p /opt/renode \
    && curl -sL "https://github.com/renode/renode/releases/download/v${RENODE_VERSION}/renode-${RENODE_VERSION}.linux-portable.tar.gz" \
       | tar xz -C /opt/renode --strip-components=1 \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

ENV RENODE_PATH=/opt/renode/renode

COPY . /src
RUN pip install --no-cache-dir /src && rm -rf /src

WORKDIR /work
ENTRYPOINT ["brickproof"]
CMD ["demo"]
