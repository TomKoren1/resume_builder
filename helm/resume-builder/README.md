# `helm/resume-builder/`

The Helm chart that deploys the whole app to Kubernetes: the frontend and
backend themselves, plus a full monitoring stack (Prometheus, Grafana,
Loki, Alertmanager) vendored as chart dependencies. In the running cluster
this chart is applied by ArgoCD, not by hand — see
[`../../argocd/README.md`](../../argocd/README.md).

## Layout

| Path | Purpose |
|---|---|
| `Chart.yaml` | Declares this chart plus its three dependencies: `prometheus`, `grafana`, `loki-stack`. |
| `charts/*.tgz` | Those dependencies, **vendored and committed** — `helm template`/`install` works fully offline, no `helm dependency build` needed. |
| `values.yaml` | App config only — backend/frontend/ingress. Small and stable; see [Key `values.yaml` sections](#key-valuesyaml-sections-app-config) below. |
| `values-monitoring.yaml` | Everything Grafana/Prometheus/Loki/Alertmanager — split out from `values.yaml` since it's ~200 lines of a completely different concern (alert rules, datasources, dashboards, retention). Layered on top of `values.yaml` via `argocd/application.yaml`'s `spec.source.helm.valueFiles` — **not** picked up automatically by a plain `helm template .`/`helm install`, see [Local testing](#local-testing). |
| `templates/` | This app's own resources (deployments, services, ingress, PVC, SealedSecrets, the Grafana dashboard ConfigMap) plus `_helpers.tpl` (name templating). |
| `dashboards/resume-builder.json` | The app's Grafana dashboard — loaded into a ConfigMap by `templates/grafana-dashboard-configmap.yaml` via `.Files.Get`, picked up by Grafana's sidecar (label `grafana_dashboard: "1"`). Includes generation-rate/latency panels, backend error/warning logs (filtered by the `severity` label the app's Loki handler attaches, not a text match), a log-volume-by-pod graph, a live log tail, and an active-alerts table + timeline sourced from Prometheus's `ALERTS` metric. |

## Key `values.yaml` sections (app config)

- **`backend.image` / `frontend.image`** — `ghcr.io/tomkoren1/*`, tag bumped
  automatically by CI (`.github/workflows/build-and-deploy.yml`). Never
  edited by hand outside of that workflow.
- **`backend.persistence`** — size of the PVC backing the SQLite DB
  (`/data/resume_builder.db`). See [`../../backend/README.md`](../../backend/README.md#persistence).
- **`ingress.host`** — `resume.local`; the Ingress routes `/generate`,
  `/history`, `/master-resume` to the backend and everything else to the
  frontend, all under this one host.

## Key `values-monitoring.yaml` sections

- **`grafana.datasources`** — Prometheus, Loki, and Alertmanager, each with
  a **pinned UID** (`Prometheus`/`Loki`/`Alertmanager` — without this, the
  dashboard's panels reference UIDs that don't match what Grafana
  auto-generates, and silently show no data). The Alertmanager datasource
  powers Grafana's native Alerting page, showing the same alerts that get
  posted to Slack. Also two auto-imported community dashboards (Node
  Exporter Full, Kubernetes cluster monitoring) alongside the app's own.
- **`prometheus.serverFiles.alerting_rules.yml`** — all alert rules, in two
  groups: `resume-builder` (BackendDown, HighResumeGenerationErrorRate,
  HighLLMLatency, FrontendDown) and `infrastructure` (ArgoCDComponentDown,
  ArgoAppOutOfSync, ArgoAppDegraded, NodeDiskSpaceLow). Kept inline here
  rather than in its own file: Helm doesn't template `values.yaml` at all
  (no `.Files.Get` available there), so — unlike the dashboard JSON — there's
  no way to pull this from a separate file without taking over the whole
  Prometheus config ConfigMap ourselves.
- **`prometheus.alertmanager.config`** — routes everything to Slack via a
  webhook mounted from the `resume-builder-secrets` SealedSecret
  (`extraSecretMounts` + `slack_api_url_file` — Alertmanager's `slack_configs`
  needs a bot-token-based receiver by default, so this uses the raw
  webhook-URL-file form instead).
- **`loki-stack.loki.persistence`** — **must** stay `enabled: true`. It
  defaults to `false` upstream (an `emptyDir`), which silently loses all
  log history on every pod restart — this was a real bug found and fixed;
  see the git history for `values-monitoring.yaml` if this ever needs
  re-deriving.
- **`loki-stack.promtail.config.clients`** — **must** stay pinned to
  `http://resume-builder-loki:3100/...`. The `loki-stack` chart's own
  default is `http://{{ .Release.Name }}:3100/...`, which only resolves
  correctly when `loki-stack` is installed as its own top-level release;
  as a dependency of this umbrella chart, `.Release.Name` is the parent
  release (`resume-builder`), not the Loki service
  (`resume-builder-loki`) — promtail silently failed to push a single log
  line until this was overridden. Same class of bug as the Grafana
  datasource URLs above, just easier to miss since it fails silently in a
  pod's own logs instead of showing up as empty panels.

## Secrets

Nothing sensitive lives in `values.yaml` or `values-monitoring.yaml`. Two
`SealedSecret` resources are
committed instead (`templates/backend-sealedsecret.yaml`,
`templates/grafana-admin-sealedsecret.yaml`) — encrypted with the
cluster's sealed-secrets controller public key, safe to commit, and only
decryptable by that specific controller. To rotate or add a secret:

```bash
kubectl create secret generic resume-builder-secrets -n resume-builder \
  --dry-run=client -o yaml \
  --from-literal=ANTHROPIC_API_KEY=... --from-literal=SLACK_WEBHOOK=... \
  | kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system \
  -o yaml > templates/backend-sealedsecret.yaml
```

## Notable design decisions

- **Backend `Deployment` uses `strategy.type: Recreate`**, not the k8s
  default `RollingUpdate`. The SQLite DB lives on a `ReadWriteOnce` PVC;
  a rolling update would briefly try to mount it from two pods at once
  (and have two processes touch the same SQLite file). `rollingUpdate` is
  explicitly nulled in the same block — Kubernetes rejects a `Deployment`
  that has both fields set, and the field persists on an existing object
  from before this changed unless cleared.
- **`serviceaccount.yaml`'s IRSA annotation is conditional** on
  `backend.irsaRoleArn` being set — meaningful only on EKS. On this k3s
  cluster it's simply omitted; Bedrock calls fail for lack of credentials
  and the backend falls back to the Anthropic API by design (see the root
  README's [Bedrock fallback](../../README.md#bedrock-fallback-anthropic-api)).
- **Readiness/liveness probes** hit `/metrics` (backend) and `/` (frontend)
  — cheap, always-available endpoints, not full functional health checks.

## Local testing

```bash
helm lint .
# -f values-monitoring.yaml matches how ArgoCD actually renders this chart
# (see argocd/application.yaml) - omitting it renders app config only,
# with the whole monitoring stack falling back to unconfigured defaults.
helm template resume-builder . -n resume-builder -f values-monitoring.yaml   # fully offline, vendored charts/
```
