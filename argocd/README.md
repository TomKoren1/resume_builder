# `argocd/`

ArgoCD's own configuration — separate from [`helm/resume-builder/`](../helm/resume-builder/README.md)
because ArgoCD is a cluster-level tool with its own lifecycle, not part of
the app it deploys.

| File | Purpose | Applied |
|---|---|---|
| `application.yaml` | The `Application` resource: watches `helm/resume-builder` on `main`, auto-syncs with `prune: true` + `selfHeal: true`, into the `resume-builder` namespace. `spec.source.helm.valueFiles` also points it at `values-monitoring.yaml` (Helm/ArgoCD always load the chart's own `values.yaml` as the base regardless, so only the extra file needs listing) — see [`../helm/resume-builder/README.md`](../helm/resume-builder/README.md) for why that's split out. | `kubectl apply -f argocd/application.yaml` |
| `values.yaml` | Helm values for the ArgoCD **installation itself** (plain HTTP server, metrics enabled on controller/server/repo-server, notifications wiring). | `helm upgrade argocd argo/argo-cd -n argocd -f argocd/values.yaml` |
| `notifications-sealedsecret.yaml` | The Slack webhook URL, sealed, for ArgoCD's own notifications controller. | `kubectl apply -f argocd/notifications-sealedsecret.yaml` |

**None of this is itself GitOps-synced** — ArgoCD can't bootstrap its own
installation from git (chicken-and-egg), so these are applied manually with
the commands above whenever they change, same as installing ArgoCD in the
first place was. They're committed for reproducibility, not automation.

## What ArgoCD actually owns

Once `application.yaml` is applied, **ArgoCD is the only thing that should
apply changes to the `resume-builder` release** — no more manual
`helm upgrade`/`kubectl apply` against that namespace. The deploy flow is:

```
push to main → CI builds + pushes images, bumps helm/resume-builder/values.yaml,
commits → ArgoCD polls the repo (~3 min default) → detects the change → syncs
```

See the root README's [Deployment architecture](../README.md#deployment-architecture)
for the full picture and [`.github/workflows/README.md`](../.github/workflows/README.md)
for the CI side.

`selfHeal: true` also means ArgoCD will revert any *manual* `kubectl`/`helm`
change against the `resume-builder` namespace back to match git — by
design, but worth knowing before reaching for an ad-hoc `kubectl edit` to
test something against that namespace.

## Monitoring ArgoCD itself

Enabled via `values.yaml`'s `metrics.enabled` per-component (not on by
default upstream), scraped by the same annotation-based Prometheus job as
everything else in this cluster. Alert rules for it
(`ArgoCDComponentDown`, `ArgoAppOutOfSync`, `ArgoAppDegraded`) live in
`helm/resume-builder/values-monitoring.yaml` — see that folder's README.

One thing worth knowing if you're ever testing an alert that depends on
this `Application`'s own live state (e.g. scaling a Deployment to 0 to
fire `BackendDown`): `selfHeal: true` reacts within **seconds**, not the
~3 minute poll interval — it reverted a manual `kubectl scale` back to
the git-declared replica count in about 5 seconds during testing, well
under any alert's `for:` duration. To test something like that reliably,
temporarily clear the sync policy (`kubectl patch application
resume-builder -n argocd --type merge -p '{"spec":{"syncPolicy":null}}'`),
run the test, then restore it (same command with the automated block from
`application.yaml` put back).

## Slack notifications

Two independent paths push to the same Slack channel:

1. **Alertmanager** (via Prometheus alert rules) — app-level and
   infrastructure-level alerts.
2. **ArgoCD's own notifications-controller** (configured here) — fires
   directly on `on-sync-failed` / `on-health-degraded` for the
   `resume-builder` `Application`, independent of whether Prometheus
   itself is working. Uses a generic `webhook` notifier
   (`notifiers: service.webhook.slack` in `values.yaml`), not ArgoCD's
   built-in `slack` notifier — that one needs a Slack bot token via the
   Slack API, and this project only has an incoming webhook.

`notifications.secret.create: false` in `values.yaml` is what lets
`notifications-sealedsecret.yaml` own the `argocd-notifications-secret`
object instead of Helm — without it, a future `helm upgrade` of ArgoCD
would reset that secret back to empty and silently kill the Slack
notifications.

## Access

`http://argocd.local` (add to `/etc/hosts`, same as `resume.local`/
`grafana.local`). Initial admin password:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 --decode
```

Change it (`argocd account update-password`) and delete that secret once
you have — it's a one-time bootstrap credential.
