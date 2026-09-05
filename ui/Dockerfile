FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
USER root
COPY --chown=101:101 --from=build /app/dist /usr/share/nginx/html
COPY --chown=101:101 nginx.conf /etc/nginx/conf.d/default.conf
COPY --chown=101:101 docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh
USER 101
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --spider -q http://localhost:8080/ || exit 1

# Regenerates runtime-config.js from HYDRA_API_BASE_URL at container start
# (see docker-entrypoint.sh), then execs nginx.
ENTRYPOINT ["/docker-entrypoint.sh"]
