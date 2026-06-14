# Lab 20 — HPA: Horizontal Pod Autoscaler

**Цель:** установить metrics-server, создать HPA, нагрузить app, посмотреть autoscaling.

**Время:** 30 минут
**Prerequisites:** Lab 06.

---

## Шаг 1. Установка metrics-server

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Для kind / Docker Desktop нужен флаг --kubelet-insecure-tls
kubectl patch -n kube-system deployment metrics-server --type=json \
  -p '[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'

kubectl wait -n kube-system --for=condition=ready pod -l k8s-app=metrics-server --timeout=120s
```

Проверка:
```bash
kubectl top nodes
kubectl top pods --all-namespaces
```

---

## Шаг 2. Workload с requests/limits

`app.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cpu-burner
spec:
  replicas: 1
  selector:
    matchLabels: {app: cpu-burner}
  template:
    metadata:
      labels: {app: cpu-burner}
    spec:
      containers:
      - name: app
        image: registry.k8s.io/hpa-example
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata: {name: cpu-burner}
spec:
  type: ClusterIP
  selector: {app: cpu-burner}
  ports: [{port: 80, targetPort: 80}]
```

```bash
kubectl apply -f app.yaml
kubectl get pods -l app=cpu-burner
```

---

## Шаг 3. HPA

`hpa.yaml`:
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: cpu-burner
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: cpu-burner
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50
```

```bash
kubectl apply -f hpa.yaml
kubectl get hpa
# TARGETS: <unknown>/50% → через минуту: 0%/50%
```

---

## Шаг 4. Генерируем нагрузку

В отдельном терминале:
```bash
kubectl run -it --rm load-generator --image=busybox -- /bin/sh -c \
  "while true; do wget -q -O- http://cpu-burner.default.svc.cluster.local; done"
```

В исходном терминале наблюдаем:
```bash
watch kubectl get hpa,pods -l app=cpu-burner
```

Через 1–2 минуты HPA увеличит количество реплик. Через 5–10 минут (после остановки нагрузки) — уменьшит обратно.

---

## Шаг 5. HPA на memory

```yaml
metrics:
- type: Resource
  resource:
    name: memory
    target:
      type: AverageValue
      averageValue: 100Mi
```

---

## Шаг 6. Multiple metrics

```yaml
metrics:
- type: Resource
  resource:
    name: cpu
    target:
      type: Utilization
      averageUtilization: 70
- type: Resource
  resource:
    name: memory
    target:
      type: AverageValue
      averageValue: 500Mi
```

HPA масштабирует до максимума ИЗ двух подсчитанных значений.

---

## Шаг 7. Поведение scale up/down

```yaml
spec:
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300       # ждать 5 мин перед scale down
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0         # моментально вверх
      policies:
      - type: Percent
        value: 100
        periodSeconds: 30
      - type: Pods
        value: 4
        periodSeconds: 30
      selectPolicy: Max
```

Это даёт точный контроль над агрессивностью HPA.

---

## Cleanup

```bash
kubectl delete hpa cpu-burner
kubectl delete -f app.yaml
# (load-generator уже завершился с --rm)
```

---

## Что вы узнали

- HPA требует **metrics-server** (или Prometheus Adapter для custom metrics)
- `metrics` — utilization (%) или averageValue (абсолют)
- Multiple metrics → берётся максимум
- `behavior` — контроль агрессивности scale up/down
- Production: stabilization window предотвращает flapping
- HPA + Cluster Autoscaler = multi-dimensional autoscaling (Pod-ы + nodes)
