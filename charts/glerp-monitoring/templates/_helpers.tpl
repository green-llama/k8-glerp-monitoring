{{/*
Return the Blackbox Exporter service address (used in Probe CRDs and scrape configs).
The service name is derived from the Helm release name + subchart alias.
*/}}
{{- define "glerp-monitoring.blackboxAddress" -}}
{{- printf "%s-blackbox-exporter.%s.svc.cluster.local:9115" .Release.Name .Values.namespace -}}
{{- end }}

{{/*
Standard labels applied to all resources in this chart.
*/}}
{{- define "glerp-monitoring.labels" -}}
app.kubernetes.io/name: glerp-monitoring
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Labels required by Rancher Monitoring's Prometheus to discover PrometheusRule objects.
*/}}
{{- define "glerp-monitoring.prometheusRuleLabels" -}}
{{- toYaml .Values.prometheusRuleLabels | nindent 0 }}
{{- end }}

{{/*
Fully qualified app name (release-name or release-name-chart-name).
*/}}
{{- define "glerp-monitoring.fullname" -}}
{{- if contains .Chart.Name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Selector labels (subset of standard labels used in Deployments/Services).
*/}}
{{- define "glerp-monitoring.selectorLabels" -}}
app.kubernetes.io/name: glerp-monitoring
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name used by security scan jobs (kube-bench, ZAP).
*/}}
{{- define "glerp-monitoring.serviceAccountName" -}}
{{- printf "%s-scanner" (include "glerp-monitoring.fullname" .) }}
{{- end }}

{{/*
Prometheus Pushgateway URL for scan job metrics push.
*/}}
{{- define "glerp-monitoring.pushgatewayUrl" -}}
{{- printf "http://%s-prometheus-pushgateway.%s.svc.cluster.local:9091" .Release.Name .Release.Namespace }}
{{- end }}

{{/*
VictoriaMetrics internal URL (used by maintenance-admin and reporting).
*/}}
{{- define "glerp-monitoring.vmUrl" -}}
{{- printf "http://%s-victoriametrics.%s.svc:8428" .Release.Name .Values.namespace }}
{{- end }}

{{/*
Report server external URL (used in security dashboard links).
*/}}
{{- define "glerp-monitoring.reportUrl" -}}
{{- if .Values.reportPort }}
{{- printf "https://%s:%s" .Values.reportHostname .Values.reportPort }}
{{- else }}
{{- printf "https://%s" .Values.reportHostname }}
{{- end }}
{{- end }}
