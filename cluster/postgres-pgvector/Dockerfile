# The dev PostgreSQL that `kagent install` deploys, plus the pgvector extension that
# kagent's long-term memory needs. Same Alpine base as kagent's default image on purpose:
# the install runs PostgreSQL as uid 70 (Alpine's postgres user), which the Debian-based
# pgvector/pgvector image does not have, so that image cannot read its TLS certificate.
FROM postgres:18-alpine@sha256:9a8afca54e7861fd90fab5fdf4c42477a6b1cb7d293595148e674e0a3181de15
ARG PGVECTOR_VERSION=v0.8.1
RUN apk add --no-cache --virtual .build build-base git \
 && git clone --branch "$PGVECTOR_VERSION" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector OPTFLAGS="" with_llvm=no \
 && make -C /tmp/pgvector install with_llvm=no \
 && rm -rf /tmp/pgvector \
 && apk del .build
COPY init-pgvector.sql /docker-entrypoint-initdb.d/
