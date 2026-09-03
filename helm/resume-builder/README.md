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
| `values.yaml` | Every configurable knob — see [Key values](#key-values) below. |
| `templates/` | This app's own resources (deployments, services, ingress, PVC, SealedSecrets, the Grafana dashboard ConfigMap) plus `_helpers.tpl` (name templating). |
| `dashboards/resume-builder.json` | The app's Grafana dashboard — loaded into a ConfigMap by `templates/grafana-dashboard-configmap.yaml` via `.Files.Get`, picked up by Grafana's sidecar (label `grafana_dashboard: "1"`). |

## Key `values.yaml` sections

- **`backend.image` / `frontend.image`** — `ghcr.io/tomkoren1/*`, tag bumped
  automatically by CI (`.github/workflows/build-and-deploy.yml`). Never
  edited by hand outside of that workflow.
- **`backend.persistence`** — size of the PVC backing the SQLite DB
  (`/data/resume_builder.db`). See [`../../backend/README.md`](../../backend/README.md#persistence).
- **`ingress.host`** — `resume.local`; the Ingress routes `/generate`,
  `/history`, `/master-resume` to the backend and everything else to the
  frontend, all under this one host.
- **`grafana.*`** — admin credentials via `existingSecret` (a SealedSecret,
  never a plaintext password), Prometheus/Loki datasources with **pinned
  UIDs** (`Prometheus`/`Loki` — without this, the dashboard's panels
  reference UIDs that don't match what Grafana auto-generates, and silently
  show no data), and two auto-imported community dashboards (Node Exporter
  Full, Kubernetes cluster monitoring) alongside the app's own.
- **`prometheus.serverFiles.alerting_rules.yml`** — all alert rules, in two
  groups: `resume-builder` (BackendDown, HighResumeGenerationErrorRate,
  HighLLMLatency, FrontendDown) and `infrastructure` (ArgoCDComponentDown,
  ArgoAppOutOfSync, ArgoAppDegraded, NodeDiskSpaceLow).
- **`prometheus.alertmanager.config`** — routes everything to Slack via a
  webhook mounted from the `resume-builder-secrets` SealedSecret
  (`extraSecretMounts` + `slack_api_url_file` — Alertmanager's `slack_configs`
  needs a bot-token-based receiver by default, so this uses the raw
  webhook-URL-file form instead).
- **`loki-stack.loki.persistence`** — **must** stay `enabled: true`. It
  defaults to `false` upstream (an `emptyDir`), which silently loses all
  log history on every pod restart — this was a real bug found and fixed;
  see the git history for `values.yaml` if this ever needs re-deriving.

## Secrets

Nothing sensitive lives in `values.yaml`. Two `SealedSecret` resources are
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
helm template resume-builder . -n resume-builder   # fully offline, vendored charts/
```
