FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
# The unprivileged base image's own "nginx" user is fixed at 101:101 by that
# image's own convention (not something we create) — declared once here so
# every reference below stays in sync if that ever needs to change, instead
# of five separate literal 101s. Plain COPY (not --chown=$ARG) deliberately:
# ARG/ENV substitution inside --chown has a history of being unreliable
# across Docker/BuildKit versions, whereas RUN always expands shell
# variables reliably — one chown at the end covers everything copied above.
ARG NGINX_UID=101
ARG NGINX_GID=101
USER root
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
# /usr/share/nginx/html itself (not just the files just copied into it)
# needs to be writable too: docker-entrypoint.sh writes a new file
# (runtime-config.js) directly into this directory at container start, which
# needs write permission on the directory itself. Without this, the
# unprivileged user can't create that file and the container never starts.
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh \
    && chown -R "${NGINX_UID}:${NGINX_GID}" /usr/share/nginx/html /etc/nginx/conf.d/default.conf /docker-entrypoint.sh
USER ${NGINX_UID}
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --spider -q http://localhost:8080/ || exit 1

# Regenerates runtime-config.js from HYDRA_API_BASE_URL at container start
# (see docker-entrypoint.sh), then execs nginx.
ENTRYPOINT ["/docker-entrypoint.sh"]
