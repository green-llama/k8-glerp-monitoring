# Migration: glerp-monitoring v1 → v2

This guide covers the hard-cutover migration from three separate charts to the consolidated
`glerp-monitoring v2.0.0`.

**Charts being replaced:**
- `glerp-monitoring` v1.x (in `cattle-monitoring-system`)
- `glerp-storage-monitor` v0.x (in `glerp-storage-monitor`)
- `glerp-sec-audit` v1.x (in `glerp-sec-audit`)

**Data impact:** Historical VictoriaMetrics data (~90 days) is lost. The new VM instance in
`glerp-monitoring` accumulates fresh data from remoteWrite immediately after install.
Dashboards will show gaps in 30-day trend panels until ~1 week of data accumulates.

---

## Pre-Migration Checklist

- [ ] `glerp-monitoring`, `glerp-storage-monitor`, and `glerp-sec-audit` are all healthy
- [ ] You have your current `cluster-values.yaml` for each chart (merge needed)
- [ ] You know your SMTP password and Telegram bot token (if used)
- [ ] Rancher UI access is available (for remoteWrite update)

---

## Step 1 — Prepare v2 values file

Create a single `cluster-values.yaml` for v2, merging settings from all three old charts:

```yaml
cluster:
  name: <your-cluster-name>
  domain: <your-domain>              # e.g. greenllama.tech

namespace: glerp-monitoring

grafana:
  datasourceNamespace: cattle-monitoring-system

victoriaMetrics:
  storage:
    storageClass: "longhorn"

# Uptime (from old glerp-monitoring cluster-values.yaml)
alerts:
  siteDownMinutes: 2
  siteDegradedMinutes: 5

# Storage (from old glerp-storage-monitor cluster-values.yaml)
longhorn:
  namespace: longhorn-system
directpv:
  namespace: directpv
  podSelectorKey: "selector.directpv.min.io"
  podSelectorValue: "<your-value>"
customers:
  - name: "Acme Corp"
    slug: "acme"
    namespace: "acme.greenllama.tech"
    minio:
      enabled: true

# Security (from old glerp-sec-audit cluster-values.yaml)
reportHostname: "security.<your-domain>"
reportPort: ""
scanTargets:
  - name: acme
    url: "https://acme.greenllama.tech"
kubeBench:
  enabled: true
zapScan:
  enabled: true
trivy-operator:
  enabled: true
prometheus-pushgateway:
  enabled: true

# Unified alerting (was split across two charts)
alertmanager:
  email:
    smarthost: "smtp.example.com:587"
    from: "alerts@greenllama.tech"
    to: "alerts@greenllama.tech"   # was ops@ in glerp-monitoring, alerts@ in glerp-storage-monitor
    authUsername: "alerts@greenllama.tech"
```

---

## Step 2 — Pre-create secrets in new namespace

```bash
# Create the namespace (the chart does NOT manage it — this protects the
# VictoriaMetrics PVC from deletion on helm uninstall, and avoids ownership conflicts)
kubectl create namespace glerp-monitoring --request-timeout=5s

# SMTP secret (REQUIRED)
kubectl create secret generic alertmanager-smtp-secret \
  --namespace glerp-monitoring \
  --from-literal=smtp_auth_password='YOUR_SMTP_PASSWORD' \
  --request-timeout=5s

# Telegram secret (only if alertmanager.telegram.enabled: true)
kubectl create secret generic telegram-alertmanager-secret \
  --namespace glerp-monitoring \
  --from-literal=bot_token='YOUR_BOT_TOKEN' \
  --request-timeout=5s
```

---

## Step 3 — Uninstall the three old charts

```bash
# Uninstall glerp-monitoring v1
helm uninstall glerp-monitoring --namespace cattle-monitoring-system --wait

# Uninstall glerp-storage-monitor
helm uninstall glerp-storage-monitor --namespace glerp-storage-monitor --wait

# Uninstall glerp-sec-audit
helm uninstall glerp-sec-audit --namespace glerp-sec-audit --wait

# Delete old namespaces (VictoriaMetrics PVC data is intentionally discarded)
kubectl delete namespace glerp-storage-monitor glerp-sec-audit --request-timeout=30s
```

---

## Step 4 — Install glerp-monitoring v2

```bash
helm upgrade --install glerp-monitoring ./charts/glerp-monitoring \
  --namespace glerp-monitoring \
  --create-namespace \
  --values cluster-values.yaml \
  --wait \
  --timeout 5m
```

---

## Step 5 — Update Rancher Monitoring (Rancher UI, one-time)

In **Rancher UI → Apps → rancher-monitoring → Edit → Edit YAML**, update the remoteWrite and
additionalScrapeConfigs sections:

```yaml
prometheus:
  prometheusSpec:
    remoteWrite:
      - url: http://glerp-monitoring-victoriametrics.glerp-monitoring.svc:8428/api/v1/write
        writeRelabelConfigs:
          - sourceLabels: [__name__]
            regex: "node_filesystem.*|node_uname_info|longhorn.*|minio.*|directpv.*|kube_customresource_directpv.*|kube_persistentvolume.*|kube_persistentvolumeclaim.*|kubelet_volume_stats.*|glerp:.*|probe_.*|glerp_maintenance.*|trivy_.*|kube_bench_.*|zap_.*"
            action: keep
    additionalScrapeConfigsSecret:
      enabled: true
      name: glerp-monitoring-scrape-configs
      key: additional-scrape-configs.yaml
```

> **Note**: The Prometheus Operator `additionalScrapeConfigsSecret` field has no `namespace`
> override — the secret must be in the same namespace as the Prometheus object
> (`cattle-monitoring-system`). The chart creates the secret there automatically.

---

## Step 6 — Verify

```bash
# Chart resources created
kubectl get all -n glerp-monitoring --request-timeout=5s

# PrometheusRules loaded
kubectl get prometheusrule -n glerp-monitoring --request-timeout=5s

# ServiceMonitors/PodMonitors
kubectl get servicemonitor,podmonitor -n glerp-monitoring --request-timeout=5s

# VictoriaMetrics running
kubectl get pods -n glerp-monitoring -l app.kubernetes.io/component=victoriametrics --request-timeout=5s

# Dashboards auto-imported (check Grafana → "GLerp Monitoring" folder)
# All 9 dashboards should appear within ~60 seconds

# Prometheus UI → Status → Targets — confirm longhorn, directpv, blackbox targets are UP
```

---

## Post-Migration Cleanup

After confirming everything is healthy for 24 hours:

1. **Archive old GitHub repos** (Settings → Archive repository):
   - `green-llama/k8-glerp-storage-monitor`
   - `green-llama/k8-glerp-security`

2. **Delete old Telegram secrets** (if they existed under old names):
   ```bash
   # These no longer exist after namespace deletion, but confirm:
   kubectl get secret telegram-storage-secret -n glerp-storage-monitor --request-timeout=5s 2>/dev/null || echo "already gone"
   ```

3. **Grafana cleanup**: The "GLerp Storage" folder may appear empty in Grafana. Delete it
   manually via Grafana UI → Dashboards → folder menu → Delete folder.

---

## Rollback

If v2 install fails before Step 5 (Rancher UI update):

```bash
# v2 rollback
helm uninstall glerp-monitoring --namespace glerp-monitoring

# Reinstall old charts from their repos
helm upgrade --install glerp-monitoring ./k8-glerp-monitoring/charts/glerp-monitoring \
  --namespace cattle-monitoring-system --create-namespace \
  --values k8-glerp-monitoring/cluster-values.yaml --wait

helm upgrade --install glerp-storage-monitor ./k8-glerp-storage-monitor/charts/glerp-storage-monitor \
  --namespace glerp-storage-monitor --create-namespace \
  --values k8-glerp-storage-monitor/cluster-values.yaml --wait

helm upgrade --install glerp-sec-audit ./k8-glerp-security/helm/glerp-sec-audit \
  --namespace glerp-sec-audit --create-namespace \
  --values k8-glerp-security/cluster-values.yaml --wait
```

Note: Old Rancher Monitoring remoteWrite URL pointed to `glerp-storage-monitor` namespace —
re-apply that in Rancher UI if needed.
