# Lab 19 — Taints, Tolerations, Topology Spread

**Цель:** управлять размещением Pod-ов через taints/tolerations и topology spread constraints.

**Время:** 25 минут
**Prerequisites:** Lab 01 (multi-node кластер — kind), Lab 06.

---

## Шаг 1. Inspect nodes

```bash
kubectl get nodes
# дожно быть несколько нод (kind с config)

kubectl get nodes --show-labels
```

Если только одна нода — пересоздайте кластер через kind с 3 нодами (см. Lab 01 Вариант 2).

---

## Шаг 2. Taint одну ноду

Выберите worker ноду (не control-plane!):
```bash
WORKER=$(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[0].metadata.name}')
echo "Worker: $WORKER"

# Тейнтим
kubectl taint node $WORKER gpu=true:NoSchedule

# Проверим
kubectl describe node $WORKER | grep Taints
```

---

## Шаг 3. Pod без toleration — не приедет на эту ноду

`pod-normal.yaml`:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: normal-pod
spec:
  containers:
  - name: app
    image: nginx:1.25
```

```bash
kubectl apply -f pod-normal.yaml
kubectl get pod -o wide
# Должен попасть на ДРУГОЙ узел, не на $WORKER
```

---

## Шаг 4. Pod с toleration — может приехать

`pod-toleration.yaml`:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-pod
spec:
  tolerations:
  - key: gpu
    operator: Equal
    value: "true"
    effect: NoSchedule
  containers:
  - name: app
    image: nginx:1.25
```

```bash
kubectl apply -f pod-toleration.yaml
kubectl get pod gpu-pod -o wide
# Может попасть и на $WORKER (но не обязательно)
```

> Toleration ≠ принуждение к ноде. Это только "разрешение".

---

## Шаг 5. Принудительно отправим Pod на GPU-ноду

```bash
# Labelим ноду
kubectl label node $WORKER hardware=gpu
```

`pod-affinity.yaml`:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-only
spec:
  tolerations:
  - key: gpu
    operator: Equal
    value: "true"
    effect: NoSchedule
  nodeSelector:
    hardware: gpu        # ← ХОЧУ на ноду с этим label
  containers:
  - name: app
    image: nginx:1.25
```

```bash
kubectl apply -f pod-affinity.yaml
kubectl get pod gpu-only -o wide
# Гарантированно на $WORKER
```

---

## Шаг 6. NoExecute — выселяем Pod-ы

```bash
kubectl taint node $WORKER critical=true:NoExecute

# Все Pod-ы без соответствующей toleration будут evicted с $WORKER
kubectl get pods -o wide --watch
```

---

## Шаг 7. Topology Spread Constraints

Уберём taint:
```bash
kubectl taint node $WORKER gpu=true:NoSchedule-
kubectl taint node $WORKER critical=true:NoExecute-
```

`deploy-spread.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spread-app
spec:
  replicas: 6
  selector:
    matchLabels: {app: spread}
  template:
    metadata:
      labels: {app: spread}
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname    # spread по нодам
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels: {app: spread}
      containers:
      - name: c
        image: nginx:1.25
```

```bash
kubectl apply -f deploy-spread.yaml
kubectl get pods -o wide -l app=spread
# Pod-ы должны быть распределены равномерно по нодам
```

Подсчитаем распределение:
```bash
kubectl get pods -l app=spread -o wide --no-headers | awk '{print $7}' | sort | uniq -c
# Должно быть примерно равномерно
```

---

## Шаг 8. Pod Anti-Affinity (старая форма)

`anti-affinity.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ha-app
spec:
  replicas: 3
  selector:
    matchLabels: {app: ha-app}
  template:
    metadata:
      labels: {app: ha-app}
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values: [ha-app]
            topologyKey: kubernetes.io/hostname
      containers:
      - name: c
        image: nginx:1.25
```

```bash
kubectl apply -f anti-affinity.yaml
kubectl get pods -l app=ha-app -o wide
# Гарантированно по одной реплике на ноду
```

---

## Cleanup

```bash
kubectl delete -f anti-affinity.yaml -f deploy-spread.yaml -f pod-affinity.yaml -f pod-toleration.yaml -f pod-normal.yaml

# Снять taints (если ещё есть)
kubectl taint node $WORKER gpu=true:NoSchedule- 2>/dev/null
kubectl taint node $WORKER critical=true:NoExecute- 2>/dev/null

# Снять labels
kubectl label node $WORKER hardware-
```

---

## Что вы узнали

- **Taint** на ноде = "не размещай Pod-ы, если они не tolerate"
- **Toleration** в Pod = "я разрешаю себя размещать на ноду с этим taint"
- Toleration ≠ принуждение; для принуждения нужен `nodeSelector` / `nodeAffinity`
- 3 эффекта taint: `NoSchedule` / `PreferNoSchedule` / `NoExecute`
- **Topology Spread Constraints** — распределение Pod-ов по failure-domains (zones, hosts)
- **Pod Anti-Affinity** — старая форма "не размещать рядом с такими же"
- Use cases: GPU/Spot nodes, dedicated tenancy, HA для production app-ов
