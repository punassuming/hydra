FROM golang:1.24-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/hydra-go-worker ./main.go

FROM alpine:3.20

RUN apk add --no-cache ca-certificates bash git python3 openssh-client rsync

# Compose runs the worker as this dedicated non-root identity — mirrors
# worker/Dockerfile's Python worker for the same treatment on both. Override
# at build time (--build-arg) if these need to change; docker-compose.yml's
# HYDRA_WORKER_UID/GID (see .env.example) pass the same values through so
# the build and the compose `user:` field stay in sync from one source.
ARG HYDRA_WORKER_UID=10001
ARG HYDRA_WORKER_GID=10001
RUN addgroup -g "${HYDRA_WORKER_GID}" hydra \
    && adduser -D -H -u "${HYDRA_WORKER_UID}" -G hydra -s /sbin/nologin hydra

WORKDIR /app
COPY --from=build /out/hydra-go-worker /usr/local/bin/hydra-go-worker

# Liveness check: the heartbeat loop touches WORKER_HEARTBEAT_FILE every
# ~2s regardless of Redis reachability, so a stale/missing file means the
# worker process is hung — mirrors worker/Dockerfile's HEALTHCHECK for the
# Python worker (python3 is already installed here for the python executor).
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import os,sys,time; p=os.getenv('WORKER_HEARTBEAT_FILE','/tmp/hydra_worker_heartbeat'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p)<30 else 1)"

ENTRYPOINT ["hydra-go-worker"]
