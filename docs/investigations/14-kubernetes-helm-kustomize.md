# Investigation: Kubernetes Deployment — Helm Chart Audit & Kustomize Evaluation

**Date:** 2026-09-25  
**Investigator:** Claude Haiku 4.5  
**Status:** In Progress

---

## Part 1: Helm Chart Audit

### Section 1.1: Chart Structure & Idiomatic Helm Practices

**Finding**: The chart is well-structured and follows Helm best practices.

- **`_helpers.tpl` usage** (`deploy/helm/hydra/templates/_helpers.tpl`, lines 1-143): Excellent use of helper templates for naming conventions, labels, selectors, and component-specific resources. Includes idiomatic patterns like `hydra.fullname`, `hydra.labels`, `hydra.componentLabels`, and per-component selector helpers.
- **Conditional rendering**: All templates use `{{- if }}` guards correctly (e.g., `scheduler.enabled`, `ingress.enabled`, `demoMode.enabled`, `redis.persistence.enabled`).
- **Values defaults**: `values.yaml` (269 lines) provides clear defaults for all components with well-documented comments explaining trade-offs (e.g., `imagePullPolicy: IfNotPresent` for local loading workflow, `replicas: 1` for home-lab).
- **`NOTES.txt`** (71 lines, `templates/NOTES.txt`): Comprehensive post-install guidance covering credentials retrieval, port-forwarding, ingress setup, UI apiBaseUrl critical note, worker pools summary, and domain seeding.
- **Resource organization**: 10 templates total (scheduler, workers, ui, redis, mongodb, ingress, configmap, secret, domain-seed-job, NOTES.txt) cleanly separated by concern.

**Status**: ✅ Passes idiomatic Helm requirements. No fragile templating or hardcoded values.

### Section 1.2: Multi-Domain & Multi-Worker-Pool Support

**Finding**: Multi-domain/multi-worker-pool is well-implemented via values.yaml-driven arrays.

- **Worker pools**: `values.yaml` lines 171-227 define a `workers:` array of pool configs (each with name, flavor, replicas, domain, tags, resources, autoscaling, nodeSelector, tolerations, affinity).
- **Template consumption** (`templates/workers.yaml`, lines 1-122): Uses `{{- range $pool := .Values.workers }}` to generate one Deployment + optional HPA per pool entry.
- **Domain routing logic** (`workers.yaml`, lines 3-6): For each pool, template checks if `$pool.domain` equals `domainSeed.defaultDomain`. If yes, uses shared secret (`hydra-secrets`). If no, expects a per-domain secret (`hydra-domain-<domain>`). This is idempotent and clean.
- **Extra domains**: `values.yaml` line 247 (`domainSeed.extraDomains: []`) allows listing additional domains. When non-empty, the post-install/post-upgrade domain-seed Job (lines 184-232 of `templates/domain-seed-job.yaml`) provisions each domain via the admin API and creates per-domain Secrets.
- **CI test coverage** (`.github/workflows/python-ci.yml`, lines 86-129): Specific `helm template` test validates multi-domain config with two pools (python-default on `prod`, ml-pool on `ml`) targeting different domains.

**Status**: ✅ Multi-domain/pool is production-ready. CI validates it. No hardcoded domain assumptions.

### Section 1.3: Demo Mode Integration

**Finding**: Demo mode is correctly threaded through to scheduler env vars.

- **values.yaml** (lines 18-28): `demoMode.enabled: false` with documentation explaining it's a UI-declutter switch only (not an authz boundary).
- **Scheduler template** (`templates/scheduler.yaml`, lines 61-80): When `demoMode.enabled` is true, the scheduler Deployment's env list includes `HYDRA_DEMO_MODE=true` (lines 74-75). Uses conditional `{{- if or (eq .Values.scheduler.mode "separated") .Values.demoMode.enabled .Values.scheduler.extraEnv }}` to guard the entire env section.
- **CI regression test** (`.github/workflows/python-ci.yml`, lines 131-158): Validates that when `demoMode.enabled=true` and `scheduler.extraEnv` are both set, the rendered YAML correctly places both in the `env` list (never merged into `envFrom`). Python verification script confirms `HYDRA_DEMO_MODE` is in env names.

**Status**: ✅ Demo mode correctly wired. No missed coupling or env vars. CI regression-tests the merge logic.

### Section 1.4: Image Registry & Tag Handling

**Finding**: Chart correctly assumes local image loading; no registry push required for dev/home-lab deployments.

- **imagePullPolicy default** (`values.yaml` line 11): `IfNotPresent` — matches the design assumption that images are built locally and loaded onto cluster nodes (k3s ctr, kind load, minikube image load, etc).
- **Chart README** (lines 8-14, 41-89): Explicitly documents that the chart does NOT assume a registry push. Default workflow: build four images locally (script in README lines 47-52), load them onto cluster nodes per platform (k3s/kind/minikube/SSH steps in lines 58-83), then `helm install` with default `imagePullPolicy: IfNotPresent`.
- **Image tags** (`values.yaml`): Each component (scheduler, worker, go-worker, ui) references bare image names (e.g., `repository: hydra-scheduler`) with tag `"0.1.0"` matching the version in `pyproject.toml` (per README line 48). No registry URL prefix.
- **Chart.yaml** (line 10): `appVersion: "1.0.0"` tracks the project version — all images should be tagged to this version.
- **Private registry fallback** (`values.yaml` lines 12-13, 88-89): `imagePullSecrets: []` for private registries, and README notes: if pushing to a registry, set `imagePullPolicy: Always` and update `image.repository`/`tag` per component.
- **CI image builds** (`.github/workflows/container-images.yml`, per AGENTS.md): Validates builds only (`push: false`), never publishes to registry. Confirms CI does not push — matches chart's non-registry-dependent design.

**Status**: ✅ Chart correctly designed for local-load workflow. Registry is optional, not assumed. CI behavior verified.

### Section 1.5: Values Validation & Schema

**Finding**: No `values.schema.json` present; validation relies on `helm lint --strict` and README documentation.

- **Schema file**: No `values.schema.json` found in `deploy/helm/hydra/`. (Verified via `find` for `*.schema.json`.)
- **Helm lint coverage** (`.github/workflows/python-ci.yml`, line 74): CI runs `helm lint deploy/helm/hydra --strict`, which catches:
  - YAML syntax errors
  - Missing required fields in `Chart.yaml`
  - Duplicate keys
  - Invalid template syntax
  - But does NOT validate `.Values` types, ranges, or semantic constraints (e.g., `scheduler.replicas` must be ≥ 1; `maxConcurrency` must be > 0).
- **README documentation** (lines 128-172): Worker pool config, multi-domain setup, persistence, and control-plane separation sections provide guidance but no formal schema.
- **Risk**: No structured validation that `workers[].maxConcurrency > 0`, `redis.persistence.size` is valid, or `domainSeed.defaultDomain` matches naming rules (`2-63` chars, lowercase, alphanumeric + `_`/`-`, must start/end alphanumeric per AGENTS.md). Misconfigurations caught only at runtime.

**Recommendation**: Consider adding a `values.schema.json` (Helm 3.11+) or a pre-install validation hook to catch common config errors early. Low-effort fix with high value for production deployments.

### Section 1.6: Secrets Handling

**Finding**: Secrets are well-managed using a combination of Helm `lookup` preservation and external-secrets pattern.

- **Default-domain seed secret** (`templates/secret.yaml`, lines 1-57):
  - Uses `lookup "v1" "Secret" .Release.Namespace $secretName` (line 12) to fetch any existing Secret on install/upgrade. If found, re-uses stored `ADMIN_TOKEN`, `CREDENTIAL_ENCRYPTION_KEY`, and domain seed token/password.
  - If Secret does not exist, Helm generates random values: `ADMIN_TOKEN` (48 alphanumeric), `CREDENTIAL_ENCRYPTION_KEY` (32 base64url bytes), `SEED_DOMAIN_TOKEN` and `SEED_DOMAIN_REDIS_PASSWORD` (each 48/32 alphanumeric).
  - This preserves credentials across `helm upgrade` — critical for avoiding token invalidation mid-deployment.
  - Values are stored in `stringData` (Helm encodes to base64 automatically on creation).
- **Extra-domain secrets** (`templates/domain-seed-job.yaml`, lines 142-161): The domain-seed Job's Python script creates per-domain Secrets (`<release>-domain-<domain>`) via the Kubernetes API with `API_TOKEN` and `REDIS_PASSWORD` keys.
- **No plaintext in values.yaml**: AI provider keys, credentials are expected to be injected via `scheduler.extraEnv[].valueFrom.secretKeyRef` or external Secrets Operator, not inline values.
- **Worker credential injection** (`templates/workers.yaml`, lines 50-59): Workers pull `API_TOKEN` and `REDIS_PASSWORD` from the appropriate Secret (default or per-domain) via `secretKeyRef`.

**Status**: ✅ Production-grade secret handling with upgrade-safe preservation. No plaintext credential leakage risk in values.yaml. External-secrets pattern documented but not required.

### Section 1.7: CI Coverage Verification

**Finding**: CI helm job covers four critical configurations; all match actual value overrides.

Verified via `.github/workflows/python-ci.yml` lines 59-186 (helm job):

1. **Default values** (line 77): `helm template hydra deploy/helm/hydra` — baseline, no overrides.
   - Uses all defaults from `values.yaml`: `scheduler.mode=combined`, `ingress.enabled=false`, all components enabled.

2. **Separated scheduler + ingress** (lines 79-84): 
   - Overrides: `--set scheduler.mode=separated --set ingress.enabled=true --set ingress.className=nginx`
   - Validates: Scheduler Deployment `HYDRA_MODE=api`, separate orchestrator Deployment with `HYDRA_MODE=orchestrator`, two Ingress resources (UI + scheduler).

3. **Multi-domain worker pools** (lines 86-129):
   - Overrides: Two pools (python-default on `prod` with autoscaling, ml-pool on `ml` without), `domainSeed.extraDomains: ["ml"]`.
   - Validates: Two worker Deployments with correct domain-specific secret refs, domain-seed Job created for extra domain provisioning.

4. **Demo mode + extraEnv** (lines 131-158):
   - Overrides: `--set demoMode.enabled=true --set scheduler.extraEnv[0].name=EXTRA_ENV_TEST --set scheduler.extraEnv[0].value=ok`
   - Validates via Python script (lines 138-158): Confirms `HYDRA_DEMO_MODE=true` and `EXTRA_ENV_TEST=ok` land in the scheduler pod's env (not envFrom), and envFrom only contains configMapRef/secretRef.

5. **UI container port regression** (lines 160-186):
   - Validates: UI Service targetPort, Deployment containerPort, readinessProbe, and livenessProbe all agree on 8080 (nginx-unprivileged image requirement).

**Status**: ✅ CI coverage is comprehensive and matches documented configurations. All four test scenarios correspond to real production scenarios.

### Section 1.8: Known Helm Pain Points

**Finding**: Chart is well-designed; minimal pain points. No blocker issues identified.

1. **No values.schema.json** (already noted in Section 1.5): Deferred config validation creates risk of late-stage failures. Fixable via adding a schema file or pre-install validation hook.

2. **Resource requests/limits coverage**: 
   - ✅ All components have defined `requests` and `limits` (scheduler, orchestrator, UI, Redis, MongoDB, worker pools).
   - Appropriate for home-lab defaults (e.g., scheduler 100m/128Mi requests, 500m/512Mi limits).

3. **Missing PodDisruptionBudget (PDB)**: Chart has no PDB definitions. Impact: cluster maintenance (node drain, upgrades) or spot instance evictions can force downtime on single-pod components (scheduler in `combined` mode, Redis, MongoDB). Recommendation: Add optional PDB for scheduler/orchestrator/Redis/MongoDB when `replicas >= 1`. Low-complexity addition.

4. **No NetworkPolicy**: Chart allows all ingress/egress. Home-lab acceptable, but production deployments should add NetworkPolicy to restrict traffic between components (e.g., only workers → Redis/Mongo, only UI/workers → scheduler, no scheduler → outside). Not a chart blocker (users can add overlays), but absence noted.

5. **HPA for worker pools only**: Worker pools support `autoscaling` (HPA v2), but not scheduler, orchestrator, or datastore components. Acceptable: workers are the scalable tier; control plane and datastore are single-instance in home-lab design.

6. **No Helm hooks for migrations/pre-startup checks**: Domain-seed Job uses hooks (post-install/post-upgrade), but no pre-install checks for cluster readiness (e.g., PVC provisioning, StorageClass availability). Risk: install can hang if StorageClass is missing. Mitigation: README guidance covers this; not a critical gap.

7. **Template indentation consistency**: All templates use consistent nindent patterns (4-space base, 8 for nested YAML, 12 for containers). ✅ No fragile templating observed.

**Status**: ✅ Production-quality chart. Pain points are enhancement opportunities, not blockers. Recommend adding PDB + values.schema.json for production readiness.

---

## Part 2: Kustomize Evaluation

### Section 2.1: Kustomize Current Status & Capabilities

**Finding**: Kustomize is a mature, kubectl-integrated tool; actively maintained and widely used in 2026.

- **kubectl built-in**: Since Kubernetes v1.14, Kustomize is built directly into kubectl. Command: `kubectl apply -k <dir>` (no separate binary install required).
- **Version status**: Kustomize has its own release cycle; the embedded kubectl version may lag behind standalone releases. If you need newest features, install Kustomize standalone separately.
- **Maintenance**: Kustomize is a CNCF project (kubernetes-sigs/kustomize on GitHub) with active development as of 2026.
- **Core feature**: Overlays — directories containing `kustomization.yaml` that patch a base directory's YAML files using strategic merge patches (the same merge semantics Kubernetes uses for `kubectl patch`). No templating language (unlike Helm's Go templates).
- **Strategic merge limitations**: Patches fail silently if a target resource is renamed or removed from the base. Patch duplication can occur when two environments need fundamentally different resource sets.

**Status**: ✅ Kustomize is production-ready and integrated into kubectl. No version/maintenance concerns as of 2026.

### Section 2.2: Where Kustomize Would Fit

**Analysis**: Given Hydra's Helm chart already solves multi-environment/multi-domain use cases cleanly, Kustomize would add complexity without solving new problems.

**Hydra's existing customization mechanisms** (from Part 1):
- Multi-domain worker pools via `workers:` array in `values.yaml`
- Control-plane separation (`scheduler.mode: combined|separated`) via a single boolean
- Demo mode, AI provider keys, persistence, resource limits — all configurable via values overrides
- `helm template -f <custom-values>.yaml` or `helm upgrade --set` for each environment/deployment
- Extra-domain provisioning via `domainSeed.extraDomains` array — automated and idempotent

**Hypothetical Kustomize overlays** would provide:
- Dev, staging, prod directories with overlays patching replicas, resource limits, nodeSelector, tolerations
- Environment-specific ingress hosts (already doable via `values.yaml`)
- Environment-specific image tags or registries (already doable via `values.yaml`)

**The gap**: None. Helm values overrides solve these cases. Kustomize overlays would be an alternative, not an improvement.

**Scenario where Kustomize COULD help**: If Hydra were deployed as a stateless application with environments so different that some components don't exist in all environments (e.g., dev has no Redis persistence, prod has Redis Sentinel + MongoDB replicas). In that case, a shared base + environment overlays might be cleaner than a single values.yaml with complex conditionals. But Hydra's architecture (single-instance home-lab focus with optional features) already handles this cleanly via values.

**Concrete risk**: Adding Kustomize alongside Helm creates two competing customization mechanisms for the same chart. Teams would be unclear whether to `helm install -f custom.yaml` or to use `kustomize overlays`. This is the recognized anti-pattern from 2026 sources: "having clear ownership boundaries prevents complexity."

**Verdict**: Kustomize would add maintenance burden without solving a real gap in Hydra's deployment flexibility. ✅ Do NOT adopt.

### Section 2.3: Helm + Kustomize Together — Anti-Pattern or Best Practice?

**Finding** (2026 sources): The pattern is pragmatic but requires clear boundaries; mixing them without a plan is a recognized anti-pattern.

**Best Practice (2026 consensus)**:
- **Helm for third-party, distribution-oriented software**: Prometheus, Grafana, cert-manager, NGINX Ingress, Hydra (a packaged project intended for others to deploy).
- **Kustomize for your own applications**: Internal microservices, custom deployments where you own the YAML.
- **Hybrid ArgoCD workflows**: GitOps pull operators often manage Helm charts for infrastructure and Kustomize overlays for applications — clear separation.

**The key rule**: Have clear ownership boundaries between the two tools. Use one mechanism per component/tier.

**Anti-Pattern to avoid** (2026 consensus):
- Mixing Helm + Kustomize on the same application without a clear contract
- Applying Kustomize overlays on top of a Helm chart output (dynamic patches chasing a moving target)
- Using both to solve the same problem (e.g., some teams use Helm values AND Kustomize overlays to customize a chart, creating confusion)

**Hydra-specific analysis**:
- Hydra IS a Helm chart (third-party, distributable software). It should NOT be patched by Kustomize overlays after rendering.
- **Exception**: A deployment team could Kustomize-patch the rendered Helm output IF they need cluster-specific changes Helm values can't express (e.g., cluster-specific storage class, node affinity, external-secrets integration). Pattern: `helm template | kustomize build -` (render then patch). But this violates the "clear boundaries" rule and should be documented explicitly as a post-render step.

**Verdict for Hydra**: Helm is the right tool. If adopting Kustomize, use it only for Hydra-consuming applications (the user's own job definitions, custom deployments on top of Hydra), NOT for Hydra itself.

### Section 2.4: Concrete Recommendation
*To be filled*

---

## Summary — Top 5 Priorities
*To be filled*

---

## Findings Log

Starting investigation...
