SHELL := /bin/bash
KUBECTL := kubectl --request-timeout=5s
HELM    := helm
NS      := $(shell grep monitoringNamespace cluster-values.yaml | awk '{print $$2}')

.PHONY: help deploy blackbox-exporter internet-probes scrape-configs prometheusrules alertmanager-config dashboards

help:
	@echo "GLerp Monitoring — Deployment Targets"
	@echo ""
	@echo "  make deploy              Full initial deploy (all components)"
	@echo "  make blackbox-exporter   Deploy/upgrade the Blackbox Exporter Helm chart"
	@echo "  make scrape-configs      Apply the additionalScrapeConfigs Secret"
	@echo "  make internet-probes     Apply internet connectivity Probe CRDs"
	@echo "  make prometheusrules     Apply PrometheusRule manifests (alerts + recording rules)"
	@echo "  make alertmanager-config Apply AlertmanagerConfig manifest (email routing)"
	@echo "  make dashboards          Deploy Grafana dashboard ConfigMap"
	@echo ""
	@echo "Adding a new GLerp site: see docs/deployment-guide.md"
	@echo ""

deploy: blackbox-exporter scrape-configs internet-probes prometheusrules alertmanager-config dashboards
	@echo ""
	@echo "Deployment complete."
	@echo "See docs/deployment-guide.md for how to add a new GLerp site."
	@echo ""

blackbox-exporter:
	$(HELM) repo add prometheus-community https://prometheus-community.github.io/helm-charts
	$(HELM) repo update
	$(HELM) upgrade --install glerp-blackbox prometheus-community/prometheus-blackbox-exporter \
		--namespace $(NS) \
		--version $(shell grep chartVersion cluster-values.yaml | awk '{print $$2}' | tr -d '"') \
		--values helm/blackbox-exporter/values.yaml \
		--wait

scrape-configs:
	$(KUBECTL) apply -f manifests/prometheus/additional-scrape-configs-secret.yaml
	@echo ""
	@echo "IMPORTANT: After applying this Secret, you must reference it in the"
	@echo "Rancher Monitoring Helm values. See docs/deployment-guide.md Step 3."
	@echo ""

internet-probes:
	$(KUBECTL) apply -f manifests/blackbox/internet-probes.yaml

prometheusrules:
	$(KUBECTL) apply -f manifests/prometheusrules/

alertmanager-config:
	$(KUBECTL) apply -f manifests/alertmanager/alertmanager-config.yaml

dashboards:
	$(KUBECTL) create configmap glerp-monitoring-dashboards \
		--namespace $(NS) \
		--from-file=uptime-overview.json=manifests/grafana/dashboards/uptime-overview.json \
		--from-file=sla-compliance.json=manifests/grafana/dashboards/sla-compliance.json \
		--from-file=internet-connectivity.json=manifests/grafana/dashboards/internet-connectivity.json \
		--dry-run=client -o yaml \
	| $(KUBECTL) annotate --local -f - \
		'grafana_folder=GLerp Monitoring' \
		--dry-run=client -o yaml \
	| sed 's/creationTimestamp: null/labels:\n    grafana_dashboard: "1"\n    app.kubernetes.io\/name: glerp-monitoring\n  creationTimestamp: null/' \
	| $(KUBECTL) apply -f -
