# GLerp Monitoring — Deployment Guide

Deploy the full monitoring stack via the **Rancher GUI** — no `kubectl` or `helm` CLI required after initial setup.
Everything installs as a single Helm release visible in Rancher → Apps → Installed Apps.

---

## How It Works (Overview)

One Helm chart (`glerp-monitoring`) installs:
- **Blackbox Exporter** — runs HTTP probes against your GLerp sites and internet targets
- **Prometheus scrape config** — auto-discovers GLerp sites by Service labels (no per-site config files)
- **Alert rules** — site down (2 min), degraded login page (5 min), ISP lost (2 min)
- **AlertManager config** — email routing with ISP-aware alert suppression
- **4 Grafana dashboards** — imported automatically (Uptime Overview, SLA Compliance, Internet Connectivity, Customer SLA Report)
- **VictoriaMetrics** — single-node long-term storage for probe metrics (90-day retention for accurate SLA reporting)

**To add a new GLerp site after deployment:** add 1 label + 1 annotation to its Kubernetes Service. Done.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| RKE2 cluster | With Rancher UI access |
| Rancher Monitoring | Already installed (`cattle-monitoring-system` namespace) |
| Rancher cluster-owner or project-owner role | To install apps and edit monitoring config |
| SMTP credentials | For email alerts (you'll create a Kubernetes Secret in Step 1) |

---

## Step 1 — Create the SMTP Secret

This Secret must exist **before** installing the chart. Create it once per cluster via Rancher:

**Rancher UI:** Cluster → Storage → Secrets → Create

| Field | Value |
|---|---|
| Namespace | `cattle-monitoring-system` |
| Name | `alertmanager-smtp-secret` |
| Key | `smtp_auth_password` |
| Value | Your SMTP password |

Or via kubectl if you have CLI access:
```bash
kubectl create secret generic alertmanager-smtp-secret \
  --namespace cattle-monitoring-system \
  --from-literal=smtp_auth_password='YOUR_PASSWORD'
```

---

## Step 2 — Add the Chart Repository to Rancher

This tells Rancher where to find the `glerp-monitoring` Helm chart.

1. In Rancher, go to **Apps → Repositories → Create**
2. Fill in:

| Field | Value |
|---|---|
| Name | `glerp-monitoring` |
| Index URL / Target | Select **Git repository** |
| Git Repo URL | `https://github.com/green-llama/k8-glerp-monitoring` |
| Git Branch | `main` |
| Path | `charts` |
| Authentication | GitHub Personal Access Token (since repo is private) |

3. Click **Create**. Rancher scans the `charts/` directory and finds the `glerp-monitoring` chart.

> **GitHub PAT:** Generate at GitHub → Settings → Developer Settings → Personal Access Tokens.
> Needs `read:packages` and `repo` (read) scope on the private repo.

---

## Step 3 — Install the `glerp-monitoring` Chart

1. Go to **Apps → Charts** and search for `glerp-monitoring`
2. Click **Install**
3. Set:
   - **Namespace:** `cattle-monitoring-system`
   - **Name:** `glerp-monitoring` (or your preferred release name)
4. On the **Values** screen, edit the following (everything else can stay as default):

```yaml
cluster:
  name: gl-dev2                          # Your cluster's human-readable name
  domain: greenllama.tech                # Base domain for GLerp sites

alertmanager:
  email:
    smarthost: "smtp.yourprovider.com:587"
    from: "alerts@greenllama.tech"
    to: "ops@greenllama.tech"
    authUsername: "alerts@greenllama.tech"
    # passwordSecret.name/key must match the Secret you created in Step 1
    passwordSecret:
      name: alertmanager-smtp-secret
      key: smtp_auth_password
```

5. Click **Install**

Rancher installs the chart and it appears in **Apps → Installed Apps** as `glerp-monitoring`.

---

## Step 4 — Wire the Scrape Configs and Long-term Storage into Prometheus

This is the one step that requires editing the Rancher Monitoring chart values.
Prometheus needs to know about the scrape config Secret and where to forward probe metrics for long-term storage.

1. Go to **Apps → Installed Apps → rancher-monitoring → Edit Config**
2. Click **Edit YAML** (or navigate the form to `prometheus → prometheusSpec`)
3. Add/merge these values:

```yaml
prometheus:
  prometheusSpec:
    # Tell Prometheus where the GLerp site scrape configs live
    additionalScrapeConfigsSecret:
      enabled: true
      name: glerp-monitoring-scrape-configs   # matches what the chart created
      key: scrape-configs.yaml

    # Allow Prometheus to discover Services in all namespaces (for site auto-discovery)
    serviceMonitorNamespaceSelector: {}

    # Allow Prometheus to discover Probe CRDs in all namespaces
    probeNamespaceSelector: {}

    # Forward probe metrics to VictoriaMetrics for 90-day SLA retention.
    # Only the four GLerp probe jobs are forwarded — not all cluster metrics.
    # This keeps VictoriaMetrics storage small (2Gi) regardless of cluster size.
    remoteWrite:
      - url: http://glerp-monitoring-victoriametrics.cattle-monitoring-system.svc.cluster.local:8428/api/v1/write
        writeRelabelConfigs:
          - sourceLabels: [job]
            regex: "glerp-sites-basic|glerp-sites-login|glerp-sites-internal|internet-connectivity"
            action: keep
```

> **Note on release name:** The Secret name and VictoriaMetrics URL both use your chart release name.
> If you installed with the default name `glerp-monitoring` these values are correct as-is.
> If you used a different name, replace `glerp-monitoring` in both the Secret name and the URL.

4. Click **Save / Upgrade**. Prometheus reloads its config automatically within ~30 seconds.

**Verify:** Rancher → Monitoring → Prometheus → Status → Targets
Search for `glerp-sites-basic`, `glerp-sites-login`, `glerp-sites-internal` — they appear
with 0 targets initially (no sites labeled yet). That is correct.

Also verify `internet-connectivity` shows 3 targets (Google, Cloudflare, Microsoft) all UP.

**Verify VictoriaMetrics is receiving data:**
After 1-2 minutes, open Rancher → Monitoring → Grafana → Explore, select
`VictoriaMetrics (GLerp Long-term)` as the datasource, and run:
```
probe_success{job="internet-connectivity"}
```
You should see 3 time series (one per ISP probe). This confirms remoteWrite is working.

---

## Step 5 — Verify Dashboards and Alerts

**Grafana dashboards:**
- Rancher → Monitoring → Grafana
- Look for folder **GLerp Monitoring**
- Three dashboards should appear within ~60 seconds of chart install

**Alert rules:**
- Rancher → Monitoring → Prometheus → Alerts
- You should see: `GLerpSiteDown`, `GLerpSiteDegraded`, `ISPConnectivityLost`, `GLerpSiteCertExpiringSoon`, etc.
- All should be in `Inactive` state (no sites monitored yet)

---

## Step 6 — Adding a GLerp Site to Monitoring

When deploying a new GLerp site via its Helm chart, add these fields to the **Service** that fronts the Frappe/ERPNext workers:

```yaml
# In your GLerp site's Helm chart values, under the service section:
service:
  labels:
    glerp-monitoring: "enabled"
  annotations:
    glerp-monitoring/public-url: "https://mcdonalds.greenllama.tech"
```

Replace `mcdonalds.greenllama.tech` with the actual public URL for that site.

**For an already-deployed site** (add monitoring without redeploying the Helm chart):

In Rancher UI:
1. Go to the site's namespace (e.g., `mcdonalds`)
2. Service Discovery → Services → find the Frappe service → Edit
3. Add to **Labels:** `glerp-monitoring = enabled`
4. Add to **Annotations:** `glerp-monitoring/public-url = https://mcdonalds.greenllama.tech`
5. Save

**What happens automatically within ~60 seconds:**
- Prometheus discovers the labeled Service
- Three probe targets appear: `glerp-sites-basic`, `glerp-sites-login`, `glerp-sites-internal`
- The site appears in all three Grafana dashboards
- Alert rules begin evaluating for this site

**Removing a site from monitoring:**
Remove the `glerp-monitoring: "enabled"` label from the Service (via Rancher UI → Edit Service → delete the label). Prometheus stops scraping within one interval.

---

## How the Three-Tier Health Check Works

| Tier | Job name | Probe target | Module | Alert | SLA signal |
|---|---|---|---|---|---|
| 1 — Basic | `glerp-sites-basic` | `https://<site>/login` | `http_2xx` | `GLerpSiteDown` (2 min) | No |
| 2 — Content | `glerp-sites-login` | `https://<site>/login` | `http_glerp_login` | `GLerpSiteDegraded` (5 min) | **Yes** |
| 3 — Internal | `glerp-sites-internal` | Internal ClusterIP service | `http_2xx_internal` | None (diagnostic) | No |

**Why Tier 2 matters for ERPNext v16:**
When Frappe/gunicorn workers crash or are overloaded, Nginx still answers HTTP requests but returns a small stub page. A simple HTTP 200 check misses this. The `http_glerp_login` module validates that the response body contains `frappe`, `form-signin`, and `btn-login` — markers that are only present when the login page fully renders. If they're missing, the site is `DEGRADED` (yellow in dashboard) even though HTTP 200 is returned.

**Dashboard states:**

| Grafana color | Meaning | Alert fired |
|---|---|---|
| Green | Tier 1 + Tier 2 both passing | None |
| Yellow | Tier 1 passing, Tier 2 failing | `GLerpSiteDegraded` (warning) |
| Red | Tier 1 failing | `GLerpSiteDown` (critical) |

---

## ISP vs Application Alert Logic

```
All internet probes fail (Google + Cloudflare + Quad9)
  → ISPConnectivityLost fires (critical)
  → GLerpSiteDown and GLerpSiteDegraded are SUPPRESSED (inhibition rule)
  → You get 1 alert instead of N site alerts

Site probe fails, internet probes succeed
  → GLerpSiteDown or GLerpSiteDegraded fires (application failure)

Site probe fails, AND internet probes fail
  → GLerpSiteDownISPSuspected fires (warning — ISP likely the cause)
```

---

## SLA Compliance Reporting

1. Open Grafana → **GLerp Monitoring → SLA Compliance**
2. Set time range to the reporting period (e.g., `Last 30 days` or a specific date range)
3. The table shows per-site: **Uptime %**, **Downtime (minutes)**, **SLA Status (PASS/FAIL)**
4. Export: click the table panel title → **Inspect → Data → Download CSV**

SLA target: **99.5%** monthly (≤ 3.6 hours downtime/month).
The SLA signal is the Tier 2 login probe — both complete outages and degraded states count.

**Why the SLA dashboard uses VictoriaMetrics:**
Prometheus retains all cluster metrics for only 8-10 days to keep storage manageable.
A 30-day lookback in Prometheus would silently return incorrect results (data only
goes back 8-10 days). VictoriaMetrics receives only the probe metrics via remoteWrite
and retains them for 90 days, so `avg_over_time(...[$__range])` with "Last 30 days"
selected gives an accurate result. The datasource dropdown in the dashboard defaults to
`VictoriaMetrics (GLerp Long-term)` — do not change it to Prometheus for SLA queries.

---

## Optional — Maintenance Window Admin

The Maintenance Admin is a lightweight browser form that lets you define, view, and delete maintenance windows without any Grafana or kubectl knowledge. Enable it when you want to delegate maintenance scheduling to site administrators.

### Step A — Create a Grafana service account token

The tool needs an Editor-role token to create and update Grafana annotations.

1. In Grafana, go to **Administration → Service accounts → Add service account**
2. Name it `maintenance-admin`, set role **Editor**
3. Click **Add service account token** → copy the token value — you only see it once

### Step B — Enable in Helm values

Add to your `glerp-monitoring` values when installing or upgrading:

```yaml
maintenanceAdmin:
  enabled: true
  hostname: "maintenance.monitoring.greenllama.tech"   # DNS name reachable from admin's browser
  externalDnsTarget: "pec.greenllama.tech"             # cluster ingress point for external-dns (Cloudflare)
                                                        # leave empty to create the DNS record manually
  grafanaToken: "<token from Step A>"
  auth:
    username: "admin"
    password: "<strong password>"                       # protects the admin form
  tlsSecretName: "letsencrypt-greenllama-tech-tls"     # TLS Secret in traefik-system
  googleMfaMiddleware:
    name: "google-mfa"
    namespace: "traefik-system"
```

The tool deploys as a single pod in `cattle-monitoring-system` and is exposed via a Traefik `IngressRoute` in `traefik-system`. The `tlsSecretName` and `googleMfaMiddleware` must already exist in `traefik-system`.

### Step C — Verify

Browse to `https://<hostname>`. You should see the Maintenance Window Admin form with a site dropdown populated from your monitored sites. If the dropdown is empty, confirm VictoriaMetrics has received probe data (see the remoteWrite verification in Step 4).

### Step D — Add the maintenance admin link to Grafana dashboards

The maintenance admin URL is deployment-specific, so it is not baked into the chart's dashboard JSON. Add it manually in Grafana after deployment — it persists in Grafana's database independently of Helm upgrades.

For each dashboard where you want the link (recommended: all three GLerp Monitoring dashboards):

1. Open the dashboard in Grafana
2. Click the **Settings** gear icon (top-right) → **Links**
3. Click **Add link**
4. Fill in:

| Field | Value |
|---|---|
| Type | Link |
| Title | Maintenance Admin |
| URL | `https://<your maintenance hostname>` |
| Open in new tab | ✓ (recommended) |

5. Click **Apply** → **Save dashboard**

The link appears in the dashboard header next to any existing links (e.g., "Internal: Uptime Overview"). Clicking it opens the Maintenance Admin in a new tab.

> **Note:** Dashboard links added through the Grafana UI are stored in Grafana's database. They survive `helm upgrade` but will be lost if Grafana is fully reinstalled. Consider bookmarking the maintenance admin URL directly as well.

---

## Upgrading the Chart

When a new version of this chart is published:
1. Rancher → Apps → Repositories → `glerp-monitoring` → Refresh
2. Apps → Installed Apps → `glerp-monitoring` → Upgrade
3. Review the values (your customizations are preserved) → Upgrade

---

## Deploying on a New Cluster (Checklist)

- [ ] Create `alertmanager-smtp-secret` in `cattle-monitoring-system` (Step 1)
- [ ] Add `glerp-monitoring` repo to Rancher Apps (Step 2) — reuse same GitHub PAT
- [ ] Install `glerp-monitoring` chart with cluster-specific values (Step 3)
- [ ] Edit `rancher-monitoring` values to reference the scrape config Secret (Step 4)
- [ ] Verify internet probes are UP in Prometheus Targets (Step 5)
- [ ] Label each existing GLerp site's Service (Step 6)

---

## File Reference

```
charts/glerp-monitoring/
├── Chart.yaml                         ← chart metadata + blackbox-exporter subchart dep
├── values.yaml                        ← all configurable settings
├── files/
│   ├── dashboards/                    ← Grafana dashboard JSON embedded into ConfigMap at install
│   │   ├── uptime-overview.json
│   │   ├── sla-compliance.json
│   │   ├── internet-connectivity.json
│   │   └── customer-sla-report.json
│   └── maintenance-admin-server.py    ← maintenance admin HTTP server (mounted via ConfigMap)
└── templates/
    ├── _helpers.tpl                   ← shared template helpers
    ├── additional-scrape-configs-secret.yaml   ← Prometheus site auto-discovery + ISP scrape jobs
    ├── prometheusrule-recording.yaml  ← real-time 3-state health recording rule
    ├── prometheusrule-alerts-glerp.yaml        ← site down/degraded alerts
    ├── prometheusrule-alerts-internet.yaml     ← ISP alerts
    ├── alertmanager-config.yaml       ← email/Telegram/Slack routing + inhibition rules
    ├── grafana-dashboards-configmap.yaml       ← auto-imported Grafana dashboards
    ├── grafana-datasource-configmap.yaml       ← auto-provisions VictoriaMetrics datasource
    ├── victoriametrics.yaml           ← long-term probe metric storage (PVC+Deploy+Svc)
    └── maintenance-admin.yaml         ← optional maintenance window admin (Deployment+Service+IngressRoute)
```
