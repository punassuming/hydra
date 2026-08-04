FROM golang:1.24-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/hydra-go-worker ./main.go

FROM alpine:3.20

RUN apk add --no-cache ca-certificates bash git python3 openssh-client rsync

WORKDIR /app
COPY --from=build /out/hydra-go-worker /usr/local/bin/hydra-go-worker

# Liveness check: the heartbeat loop touches WORKER_HEARTBEAT_FILE every
# ~2s regardless of Redis reachability, so a stale/missing file means the
# worker process is hung — mirrors worker/Dockerfile's HEALTHCHECK for the
# Python worker (python3 is already installed here for the python executor).
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import os,sys,time; p=os.getenv('WORKER_HEARTBEAT_FILE','/tmp/hydra_worker_heartbeat'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p)<30 else 1)"

ENTRYPOINT ["hydra-go-worker"]
