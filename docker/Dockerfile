# BrickProof with Renode and m33mu, ready to run:
#
#   docker build -f docker/Dockerfile -t brickproof .
#   docker run --rm brickproof                         # the bundled demo
#   docker run --rm brickproof demo h563               # the same demo on m33mu
#   docker run --rm -v "$PWD:/work" brickproof run adapter.yaml --html report.html
#
# (podman takes the same commands.)

# m33mu emulates the chips Renode does not have (STM32H5). It is built from source,
# with libelf (it loads ELF images with it) and without its optional integrations,
# which BrickProof does not need.
FROM python:3.12-slim AS m33mu

ARG M33MU_REPO=https://github.com/danielinux/m33mu.git
ARG M33MU_REF=23960ed50ea186c52dd7799ab1435752c257f4fc

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git build-essential cmake libelf-dev \
    && git clone --filter=blob:none "$M33MU_REPO" /m33mu \
    && git -C /m33mu checkout --quiet "$M33MU_REF" \
    && cmake -S /m33mu -B /m33mu/build -DM33MU_BUILD_TESTS=OFF \
       -DM33MU_ENABLE_CAPSTONE=OFF -DM33MU_ENABLE_TPM_LIBTPMS=OFF -DM33MU_ENABLE_WOLFSSL=OFF \
       -DM33MU_ENABLE_LIBDW=OFF -DM33MU_ENABLE_RUST_PLUGINS=OFF \
    && cmake --build /m33mu/build -j"$(nproc)" --target m33mu

FROM python:3.12-slim

ARG RENODE_VERSION=1.17.0

# the portable Renode build brings its own runtime; it still wants ICU and zlib from the
# system. m33mu wants libelf.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libicu-dev zlib1g libelf1 \
    && mkdir -p /opt/renode \
    && curl -sL "https://github.com/renode/renode/releases/download/v${RENODE_VERSION}/renode-${RENODE_VERSION}.linux-portable.tar.gz" \
       | tar xz -C /opt/renode --strip-components=1 \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=m33mu /m33mu/build/m33mu /usr/local/bin/m33mu

ENV RENODE_PATH=/opt/renode/renode
ENV M33MU_PATH=/usr/local/bin/m33mu

COPY . /src
RUN pip install --no-cache-dir /src && rm -rf /src

WORKDIR /work
ENTRYPOINT ["brickproof"]
CMD ["demo"]
