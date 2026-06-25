# Lab 01 — Install `kube-prometheus-stack`

**Goal:** deploy the standard Prometheus stack into Kubernetes and verify that the main components are healthy.

**Time:** 30 minutes  
**Prerequisites:** working Kubernetes cluster, `kubectl`, `helm`, and ingress or port-forward access.

> No cluster yet? Create one with kind:
> - Docker: `kind create cluster --name dtu`
> - podman: `KIND_EXPERIMENTAL_PROVIDER=podman kind create cluster --name dtu`

**Maps to the deck:** Acts 1 (the monitoring stack appears) and 5 (Operator-managed stack shape).

---

## Step 1. Add the Helm repository

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

## Step 2. Install the chart

```bash
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --version 87.2.0
```

> The chart version is **pinned for reproducibility** — a lab should not drift when a new chart ships. Drop `--version` to pull the latest. `--create-namespace` replaces the manual `kubectl create namespace`.

## Step 3. Wait for the stack to become ready

> ⏳ On a fresh cluster nothing is cached, so first-time image pulls can take **several minutes** (especially kind on podman). Wait for the rollout before port-forwarding.

```bash
kubectl rollout status deploy/monitoring-grafana -n monitoring --timeout=5m
kubectl rollout status statefulset/prometheus-monitoring-kube-prometheus-prometheus -n monitoring --timeout=5m
```

## Step 4. Verify the pods

```bash
kubectl get pods -n monitoring
kubectl get svc -n monitoring
```

You should see pods for:
- Prometheus
- Alertmanager
- Grafana
- `kube-state-metrics`
- Node Exporter

---

## Step 5. Access Grafana

```bash
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
```

Open `http://localhost:3000`.

Get the admin password:

```bash
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 --decode && echo
```

---

## Step 6. Access Prometheus

```bash
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n monitoring 9090:9090
```

Open `http://localhost:9090` and check:
- **Status -> Targets**
- **Status -> Rules**

---

## Step 7. Verify key metrics

Run these queries in Prometheus:

```promql
up
```

> Expected: most targets return `1`. On kind, the four control-plane jobs may return `0` — see the note at the end of this step.

```promql
node_memory_MemAvailable_bytes
```

```promql
kube_node_status_condition{condition="Ready",status="true"}
```

Discuss:
- Which jobs are already scraped out of the box?
- Which components come from node-level exporters vs Kubernetes object metrics?

> ℹ️ **Expected on kind:** the `kube-controller-manager`, `kube-scheduler`, `kube-etcd`, and `kube-proxy` targets will show **DOWN** (`connection refused`). On kind these components listen on `127.0.0.1` *inside* the node containers, so Prometheus cannot reach them. This is normal on kind — and a live preview of the Lab 03 troubleshooting flow, so treat it as an exercise: "why are exactly these four down?"

To hide them instead, append these flags to the Step 2 install:

```bash
  --set kubeControllerManager.enabled=false \
  --set kubeScheduler.enabled=false \
  --set kubeEtcd.enabled=false \
  --set kubeProxy.enabled=false
```

---

## Cleanup

```bash
helm uninstall monitoring -n monitoring
kubectl delete namespace monitoring
```

---

## Done when

- ☐ All stack pods are Running — `kubectl get pods -n monitoring`
- ☐ Grafana opens at `localhost:3000` and you logged in
- ☐ Prometheus **Status → Targets** lists healthy targets (the four kind control-plane jobs may be DOWN — expected)
- ☐ The three queries in Step 7 return data

---

## What you learned

- `kube-prometheus-stack` provides a ready-made monitoring baseline
- Grafana and Prometheus are installed together with exporters and rules
- The operator-managed stack exposes targets and rules immediately after install
