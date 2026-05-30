# k8-glerp-monitoring

Kubernetes-native uptime monitoring for GLerp (ERPNext v16) sites and ISP connectivity.
Designed for RKE2 clusters running Rancher Monitoring (kube-prometheus-stack).

## What This Does

- **Monitors all GLerp sites automatically** — add one Service with one label and one annotation per site; Prometheus discovers it within 60 seconds, no per-site config files needed.
- **Three-tier health checks** — detects complete outages (Nginx down) AND partial outages (ERPNext workers degraded, login page malformed).
- **ISP vs. application differentiation** — distinguishes your site being down from your ISP being down; suppresses site alerts during ISP outages.
- **90-day SLA retention** — VictoriaMetrics stores probe metrics long-term so 30-day SLA reports are accurate (Prometheus alone only retains ~8-10 days).
- **Grafana dashboards** — real-time status grid, 30-day SLA compliance table (CSV export), internet connectivity history, and a customer-facing SLA report.
- **Email alerts** — after 2 minutes down (critical) or 5 minutes degraded (warning); clears automatically when the site recovers. Only GLerp-specific alerts are routed to your email; Kubernetes/Rancher platform alerts are suppressed.
- **Maintenance windows** — optional browser-based admin tool to schedule windows, exclude them from SLA calculations, mark them on dashboards, and suppress alerts.

---

## Prerequisites

- Rancher Monitoring (kube-prometheus-stack) installed in `cattle-monitoring-system`
- Helm v3+ with the Green Llama chart repo added:
  ```bash
  helm repo add green-llama https://green-llama.github.io/helm-charts/
  helm repo update
  ```
- A Kubernetes Secret containing your SMTP password — create this **before** installing the chart:
  ```bash
  kubectl create secret generic alertmanager-smtp-secret \
    --namespace cattle-monitoring-system \
    --from-literal=smtp_auth_password='YOUR_APP_PASSWORD'
  ```
  > If using Gmail with 2-Step Verification, use a Google App Password (Google Account → Security → App Passwords), not your login password. The `from:` address must match `authUsername:` exactly, or be a verified "Send mail as" alias.

---

## Installation

### Step 1 — Install the chart

Create a values override file (`glerp-monitoring-values.yaml`) — do not pass secrets via `--set`:

```yaml
cluster:
  name: gl-prod               # shown in alert email subjects
  domain: greenllama.tech     # base domain for GLerp sites

alertmanager:
  email:
    smarthost: "smtp.gmail.com:587"
    from: "rjbloesser@greenllama.tech"      # must match authUsername for Gmail
    to: "ops@greenllama.tech"
    authUsername: "rjbloesser@greenllama.tech"
    requireTLS: true
    passwordSecret:
      name: alertmanager-smtp-secret        # Secret created in Prerequisites
      key: smtp_auth_password
```

Then install:

```bash
helm install glerp-monitoring green-llama/glerp-monitoring \
  --namespace cattle-monitoring-system \
  --values glerp-monitoring-values.yaml
```

### Step 2 — Wire up Prometheus scrape jobs and remote write

The chart creates a Secret (`glerp-monitoring-scrape-configs`) containing the Prometheus scrape
configuration for all GLerp sites and ISP probes. Prometheus needs to be pointed at it. Add the
following to the **rancher-monitoring** Helm values (Rancher UI → Apps → rancher-monitoring →
Edit/Upgrade → Edit YAML):

```yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigsSecret:
      enabled: true
      name: glerp-monitoring-scrape-configs
      key: scrape-configs.yaml
    remoteWrite:
      - url: http://glerp-monitoring-victoriametrics.cattle-monitoring-system.svc.cluster.local:8428/api/v1/write
        writeRelabelConfigs:
          - sourceLabels: [job]
            regex: "glerp-sites-basic|glerp-sites-login|internet-connectivity"
            action: keep
```

The `remoteWrite` block forwards probe metrics to VictoriaMetrics for 90-day retention.
Without it, SLA dashboards only show data for the last 8-10 days (Prometheus default retention).

The chart also creates a `grafana_datasource: "1"` ConfigMap in `cattle-dashboards`. Rancher
Monitoring's Grafana runs a `grafana-init-sc-datasources` init container at pod startup that
discovers this ConfigMap and provisions the VictoriaMetrics datasource automatically — no manual
datasource configuration required. Ensure `grafana.sidecar.datasources.enabled: true` is set in
your rancher-monitoring values (it is enabled by default).

### Step 3 — Verify the base install

Within ~60 seconds of saving the rancher-monitoring values:

- **Prometheus UI → Status → Targets** — you should see `internet-connectivity` with 3 UP targets (Google, Cloudflare, Microsoft). The `glerp-sites-*` jobs will appear empty until a site Service is created (Step 4).
- **Grafana → Dashboards → GLerp Monitoring** — the Internet Connectivity dashboard should show data immediately. Site dashboards populate after Step 4.
- **Prometheus UI → Alerts** — the `glerp.uptime` rule group should be visible (inactive until a site is added).

---

## Adding a GLerp Site to Monitoring

Each GLerp site needs a dedicated Kubernetes Service in its namespace. The Service acts purely as
a Prometheus discovery target — Prometheus reads the public URL from the annotation and passes it
to the Blackbox Exporter for probing. No selector is needed.

Add the following to the site's GLerp Helm chart values under `extraObjects`:

```yaml
extraObjects:
  - apiVersion: v1
    kind: Service
    metadata:
      annotations:
        glerp-monitoring/public-url: https://sitename.greenllama.tech
      labels:
        glerp-monitoring: enabled
      name: glerp-monitoring-probe
      namespace: sitename          # must match the site's Kubernetes namespace
    spec:
      ports:
        - name: http
          port: 8080
          targetPort: 8080
      type: ClusterIP
```

Replace `sitename` with the site's Kubernetes namespace (e.g., `backuptest`, `acmecorp`).
The `site` label shown in all dashboards and alert emails is derived from this namespace.

After the Helm upgrade, Prometheus discovers the new site within ~60 seconds. It will appear in:
- Uptime Overview status grid
- SLA Compliance table
- Customer SLA Report (selectable from the Site dropdown)

**Multiple sites** — repeat the `extraObjects` block in each site's own chart. Each site manages
its own probe Service; there is no central list to maintain.

---

## Maintenance Windows

The **Maintenance Admin** tool is an optional browser-based form included in the chart.
On submit it simultaneously:

- Writes the `glerp_maintenance_window` metric to VictoriaMetrics (adjusted SLA panels automatically exclude this period)
- Creates a blue shaded annotation band on all monitoring dashboards
- Creates an AlertManager silence so no alert emails fire during the window

Deletion from the same UI expires the silence, removes the metric, and removes the annotation band
from all dashboards immediately.

### Enabling the Maintenance Admin

Add to your values override:

```yaml
maintenanceAdmin:
  enabled: true
  hostname: "maintenance.greenllama.tech"   # DNS name reachable from admin's browser
  externalDnsTarget: "pec.greenllama.tech"  # cluster ingress IP/hostname for external-dns (Cloudflare)
                                             # leave empty to manage the DNS record manually
  port: ""                                   # set if using a non-standard HTTPS port (e.g. "10443")
  grafanaToken: ""                           # Grafana service account token (Editor role)
  auth:
    username: "admin"
    password: ""                             # set a strong password
```

See [docs/deployment-guide.md](docs/deployment-guide.md) for the full setup procedure, including
creating the Grafana service account token and enabling the dashboard link.

---

## Optional: Telegram and Slack Alerts

In addition to email, the chart can send critical alerts to **Telegram** and/or **Slack** — useful
for phone push notifications. Both are opt-in and can be enabled independently.

### Telegram

**One-time setup:**

1. Message `@BotFather` on Telegram → `/newbot` → copy the bot token
2. Add the bot to a group/channel, or start a personal chat with it
3. Get your chat ID: add `@userinfobot` to the group, or message it directly for a personal chat ID
   - Group/channel IDs are negative integers (e.g. `-1234567890`)
   - Personal chat IDs are positive (e.g. `987654321`)
4. Create the Kubernetes Secret:
   ```bash
   kubectl create secret generic telegram-alertmanager-secret \
     --namespace cattle-monitoring-system \
     --from-literal=bot_token='YOUR_BOT_TOKEN'
   ```
5. Enable in your values override:
   ```yaml
   alertmanager:
     telegram:
       enabled: true
       chatId: -1234567890   # your chat/group ID
       botTokenSecret:
         name: telegram-alertmanager-secret
         key: bot_token
   ```
6. `helm upgrade` — critical alerts will now also be sent to Telegram

### Slack

**One-time setup:**

1. Slack → **Administration → Manage apps → Incoming Webhooks → Add New Webhook**
   (or create a Slack App with Incoming Webhooks enabled)
2. Select the target channel and copy the webhook URL
3. Create the Kubernetes Secret:
   ```bash
   kubectl create secret generic slack-alertmanager-secret \
     --namespace cattle-monitoring-system \
     --from-literal=webhook_url='https://hooks.slack.com/services/...'
   ```
4. Enable in your values override:
   ```yaml
   alertmanager:
     slack:
       enabled: true
       channel: "#alerts"    # must match the webhook's workspace
       webhookSecret:
         name: slack-alertmanager-secret
         key: webhook_url
   ```
5. `helm upgrade` — critical alerts will now also be sent to Slack

> **Both can be enabled simultaneously.** When enabled, critical alerts are sent to email AND to
> the messaging channel(s) at the same time. Warning and info severity alerts go to email only.

---

## Customer Reporting

The **Customer SLA Report** dashboard (`GLerp Monitoring → GLerp — Customer SLA Report`) is
designed for customer-facing use:

- Select the customer's site from the **Site** dropdown
- Set the time range to the reporting period (default: last 30 days)
- Shows both raw uptime % and maintenance-adjusted uptime %
- Data sourced from VictoriaMetrics for accurate long-range calculations

### Sharing a live link

1. Open the Customer SLA Report with the correct site selected
2. **Share → Public Dashboard → Enable**
3. Copy the public URL — customers view it without a Grafana login
4. Append `?var-site=<namespace>` to pre-select a specific customer's site

### PDF export

Enable the Grafana image renderer in rancher-monitoring values:

```yaml
grafana:
  imageRenderer:
    enabled: true
```

After enabling, **Share → Export as PDF** is available on any dashboard.

---

## Alert Reference

| Alert | Condition | Severity |
|---|---|---|
| `GLerpSiteDown` | Site HTTP probe fails ≥ 2 min, ISP healthy | Critical |
| `GLerpSiteDegraded` | Site reachable but login page malformed ≥ 5 min | Warning |
| `GLerpSiteDownISPSuspected` | Site down AND ISP probes also failing | Warning |
| `GLerpSiteCertExpiringSoon` | TLS certificate expires in < 30 days | Warning |
| `ISPConnectivityLost` | Majority of external probes fail ≥ 2 min | Critical |
| `ExternalProbePartialFailure` | One external probe failing ≥ 10 min | Info |

**ISP suppression**: during an `ISPConnectivityLost` event, all `GLerpSiteDown` and
`GLerpSiteDegraded` alerts are automatically suppressed — one ISP alert fires instead of one
per site.

Only alerts with a GLerp `alert_type` label are routed to your email receiver. Kubernetes and
Rancher platform alerts are unaffected.

---

## SLA Target

**99.5% monthly uptime** (≤ 3.6 hours downtime per 30-day month per site).

The SLA signal uses the login-tier probe — both complete outages and degraded states (site
responds but ERPNext is broken) count against SLA. Maintenance-adjusted uptime excludes any
downtime that occurred within a defined maintenance window.

---

## Repository Structure

```
charts/
└── glerp-monitoring/
    ├── Chart.yaml
    ├── values.yaml                          ← all configurable settings with defaults
    ├── files/
    │   ├── dashboards/                      ← Grafana dashboard JSON files
    │   └── maintenance-admin-server.py      ← maintenance admin HTTP server
    └── templates/
        ├── additional-scrape-configs-secret.yaml   ← site + ISP probe scrape jobs
        ├── alertmanager-config.yaml                ← email routing + ISP inhibition
        ├── grafana-dashboards-configmap.yaml        ← dashboard provisioning
        ├── grafana-datasource-configmap.yaml        ← VictoriaMetrics datasource
        ├── maintenance-admin.yaml                   ← optional admin Deployment + IngressRoute
        ├── prometheusrule-alerts-glerp.yaml         ← site alert rules
        ├── prometheusrule-alerts-internet.yaml      ← ISP alert rules
        ├── prometheusrule-recording.yaml            ← site health state recording rule
        └── victoriametrics.yaml                     ← VM Deployment + PVC + Service
```

---

## Post-Install: Enable DirectPV Physical Drive Capacity Metrics (Recommended)

DirectPV's Prometheus metrics only cover per-volume written bytes. Physical drive capacity
(e.g. 25 GiB per node) lives in the `DirectPVDrive` CRD and must be exposed via
kube-state-metrics Custom Resource State. Without this step, the Cluster Overview dashboard
cannot show physical **Drive Capacity** or true physical **Free** space per node.

> **Metric name note**: kube-state-metrics automatically prepends `kube_customresource_` to all
> custom resource metrics. The resulting Prometheus metric names are:
> - `kube_customresource_directpv_drive_total_capacity_bytes`
> - `kube_customresource_directpv_drive_allocated_capacity_bytes`
> - `kube_customresource_directpv_drive_free_capacity_bytes`

### Step 4a — Identify the kube-state-metrics ServiceAccount

```bash
kubectl get sa -n cattle-monitoring-system --request-timeout=5s | grep kube-state
# Typical output: rancher-monitoring-kube-state-metrics
```

### Step 4b — RBAC for kube-state-metrics

```bash
kubectl apply -f - <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kube-state-metrics-directpv
rules:
  - apiGroups: ["directpv.min.io"]
    resources: ["directpvdrives"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kube-state-metrics-directpv
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: kube-state-metrics-directpv
subjects:
  - kind: ServiceAccount
    name: rancher-monitoring-kube-state-metrics   # update if SA name differs
    namespace: cattle-monitoring-system
EOF
```

### Step 4c — Add Custom Resource State to rancher-monitoring

In **Rancher UI → Apps → rancher-monitoring → Edit/Upgrade → Edit YAML**, add:

```yaml
kube-state-metrics:
  customResourceState:
    enabled: true
    config:
      spec:
        resources:
          - groupVersionKind:
              group: directpv.min.io
              version: v1beta1
              kind: DirectPVDrive
            metrics:
              - name: directpv_drive_total_capacity_bytes
                help: "Total physical capacity of DirectPV drive"
                each:
                  type: Gauge
                  gauge:
                    path: [status, totalCapacity]
                labelsFromPath:
                  node: [metadata, labels, "directpv.min.io/node"]
                  drive: [metadata, labels, "directpv.min.io/drive-name"]
              - name: directpv_drive_allocated_capacity_bytes
                help: "Allocated capacity of DirectPV drive (sum of provisioned PVC sizes)"
                each:
                  type: Gauge
                  gauge:
                    path: [status, allocatedCapacity]
                labelsFromPath:
                  node: [metadata, labels, "directpv.min.io/node"]
                  drive: [metadata, labels, "directpv.min.io/drive-name"]
              - name: directpv_drive_free_capacity_bytes
                help: "Free physical capacity of DirectPV drive"
                each:
                  type: Gauge
                  gauge:
                    path: [status, freeCapacity]
                labelsFromPath:
                  node: [metadata, labels, "directpv.min.io/node"]
                  drive: [metadata, labels, "directpv.min.io/drive-name"]
```

### Step 4d — Force restart kube-state-metrics

The Helm upgrade does **not** reliably restart the kube-state-metrics pod. Force it:

```bash
kubectl rollout restart deployment/rancher-monitoring-kube-state-metrics \
  -n cattle-monitoring-system --request-timeout=30s

kubectl rollout status deployment/rancher-monitoring-kube-state-metrics \
  -n cattle-monitoring-system --request-timeout=60s
```

### Step 4e — Verify metrics are flowing

Allow ~60s after the pod restart, then query in Prometheus UI → Explore:

```
kube_customresource_directpv_drive_total_capacity_bytes
```

Expected: one series per worker node, value `26843545600` (25 GiB).

If no results, check the kube-state-metrics logs for config load confirmation:

```bash
kubectl logs -n cattle-monitoring-system \
  -l app.kubernetes.io/name=kube-state-metrics --tail=20 --request-timeout=10s \
  | grep -i "directpv\|customresource"
# Should show: "Adding metrics for ... directpv.min.io/v1beta1, Kind=DirectPVDrive"
```

> **Troubleshooting**: If metrics still don't appear after pod restart, verify the ServiceAccount
> name matches what is in the ClusterRoleBinding: `kubectl get sa -n cattle-monitoring-system | grep kube-state`.
> Re-apply the ClusterRoleBinding with the correct name and restart the pod again.

### Step 4f — Confirm remoteWrite filter includes DirectPV CRD metrics

The Prometheus → VictoriaMetrics remoteWrite regex (Step 1) must include
`kube_customresource_directpv.*` so these metrics are stored for 90-day trend panels.
The regex in this chart already includes this pattern — verify it is present in your
live rancher-monitoring configuration.

---

## Capacity Planning & Growth dashboard

The `GLerp Storage — Capacity Planning & Growth` dashboard answers one question: **which storage
object needs attention next, and in how many days?** It ranks every object across all storage
planes (Longhorn nodes, MinIO tenants, DirectPV nodes, node root filesystems, and customer
Longhorn soft-cap quotas) by projected days until it reaches 80% of capacity.

**How the projection works.** For each object:
`days = (0.80·capacity − usage) ÷ daily_growth`, where `daily_growth` is the `deriv()` of usage
over the selected **growth window** (`$growth_window`: 7d / 14d / 30d, default 14d). Because the
math needs more history than Prometheus retains (7d), **all projection queries run against the
VictoriaMetrics datasource** (90-day store). Values are capped at 1095 days and shown as `3yr+`.

**Requirement — DirectPV helper rules.** The DirectPV plane uses two recording rules
(`glerp:directpv_node_usage_bytes`, `glerp:directpv_node_capacity_bytes`) that aggregate
per-drive metrics to one series per node. They depend on the DirectPV CRD metrics — make sure the
kube-state-metrics CustomResourceState step above ("Enable DirectPV Physical Drive Capacity
Metrics") is applied, or the DirectPV rows stay empty.

**Note on thresholds.** The 80% warning level is a constant baked into the dashboard JSON
(storage dashboards are delivered as raw JSON via `.Files.Get` and cannot read Helm values). If
you change `alerts.*WarningPct` in `values.yaml`, update the dashboard constants to match.

### Future Enhancement: Predictive Capacity Alerts

Today the projection is **visual only**. A natural follow-on is a predictive *alert* that fires
when any object is projected to hit its threshold within N days — configurable per plane (e.g.
customer database space could alert at `critical` with a 14-day horizon while node filesystems
alert at `warning` with 30 days). A disabled config stub is reserved in `values.yaml` under
`capacityPlanning.predictiveAlerts`.

**Why it is not built yet:** Prometheus retains only 7 days, so the alert cannot reuse the
dashboard's 14-day VictoriaMetrics projection. It needs its own computation path.

**Implementation blueprint:**
1. In `templates/prometheusrule-recording-storage.yaml`, add a group
   `glerp.storage.capacity_forecast` with a `glerp:capacity_days_to_threshold_7d` recording rule
   per plane — the same formula as the dashboard but a hardcoded `[7d]` window (within Prometheus
   retention) and the same `label_replace` to `{object_type, object_name}`. These forward to
   VictoriaMetrics via the existing `glerp:.*` remoteWrite filter.
2. Add `templates/prometheusrule-alerts-capacity.yaml` with one alert per plane, gated on
   `.Values.capacityPlanning.predictiveAlerts.enabled` AND the per-plane `enabled` flag:
   ```yaml
   - alert: CapacityThresholdApproaching
     expr: glerp:capacity_days_to_threshold_7d{object_type="MinIO Tenant"} < <days>
     for: 6h
     labels: { severity: <severity>, alert_type: storage }
     annotations:
       summary: "{{ $labels.object_name }} ({{ $labels.object_type }}) projected to hit 80% in {{ $value | humanize }}d"
   ```
   Uncomment the `values.yaml` stub to drive thresholds/severity. The unified AlertmanagerConfig
   already routes `alert_type: storage`, so no receiver changes are needed.
3. Optionally surface the 7d figure as a second column on the dashboard for comparison with the
   longer-window projection.

---

## License

Internal use — Green Llama Technologies.
