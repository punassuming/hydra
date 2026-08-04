{{/*
Base chart name, respecting nameOverride.
*/}}
{{- define "hydra.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully qualified app name: "<release>-hydra", or just the release name if it
already contains "hydra", or fullnameOverride if set.
*/}}
{{- define "hydra.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Chart name + version, for the helm.sh/chart label.
*/}}
{{- define "hydra.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels applied to every resource.
*/}}
{{- define "hydra.labels" -}}
helm.sh/chart: {{ include "hydra.chart" . }}
{{ include "hydra.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Selector labels shared by a resource and its pod template. Must stay stable
across upgrades (no chart version here) — matchLabels is immutable.
*/}}
{{- define "hydra.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hydra.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Per-component labels/selector: pass (dict "root" $ "component" "scheduler").
*/}}
{{- define "hydra.componentSelectorLabels" -}}
{{ include "hydra.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "hydra.componentLabels" -}}
{{ include "hydra.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
Image reference helper: pass a dict with "repository" and "tag".
*/}}
{{- define "hydra.image" -}}
{{- .repository -}}:{{- .tag | default "latest" -}}
{{- end -}}

{{/*
Name of the shared secret holding ADMIN_TOKEN, CREDENTIAL_ENCRYPTION_KEY, and
the default-domain seed token/password.
*/}}
{{- define "hydra.secretName" -}}
{{ include "hydra.fullname" . }}-secrets
{{- end -}}

{{/*
Name of the shared ConfigMap holding non-secret env vars (REDIS_URL, etc).
*/}}
{{- define "hydra.configMapName" -}}
{{ include "hydra.fullname" . }}-config
{{- end -}}

{{/*
Service (and StatefulSet) name for Redis.
*/}}
{{- define "hydra.redis.fullname" -}}
{{ include "hydra.fullname" . }}-redis
{{- end -}}

{{/*
Service (and StatefulSet) name for MongoDB.
*/}}
{{- define "hydra.mongodb.fullname" -}}
{{ include "hydra.fullname" . }}-mongodb
{{- end -}}

{{/*
Service (and Deployment) name for the scheduler.
*/}}
{{- define "hydra.scheduler.fullname" -}}
{{ include "hydra.fullname" . }}-scheduler
{{- end -}}

{{/*
Deployment name for the standalone orchestrator (scheduler.mode: separated).
*/}}
{{- define "hydra.orchestrator.fullname" -}}
{{ include "hydra.fullname" . }}-orchestrator
{{- end -}}

{{/*
Service (and Deployment) name for the UI.
*/}}
{{- define "hydra.ui.fullname" -}}
{{ include "hydra.fullname" . }}-ui
{{- end -}}

{{/*
In-cluster Redis connection URL.
*/}}
{{- define "hydra.redis.url" -}}
redis://{{ include "hydra.redis.fullname" . }}:6379/0
{{- end -}}

{{/*
In-cluster MongoDB connection URL.
*/}}
{{- define "hydra.mongodb.url" -}}
mongodb://{{ include "hydra.mongodb.fullname" . }}:27017
{{- end -}}

{{/*
Deployment/Service name for a worker pool: pass (dict "root" $ "pool" $poolEntry).
*/}}
{{- define "hydra.worker.fullname" -}}
{{ include "hydra.fullname" .root }}-worker-{{ .pool.name }}
{{- end -}}
