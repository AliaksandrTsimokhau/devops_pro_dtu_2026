# Lab 19 — Taints, Tolerations, Topology Spread

**Цель:** управлять размещением Pod-ов через taints/tolerations и topology spread constraints.

**Время:** 25 минут
**Prerequisites:** Lab 01 (multi-node кластер — kind), Lab 06.

> ⚠️ Этой лабе нужен **multi-node** кластер (≥3 worker) — тот, что вы подняли в
> Lab 01. Шаги 2–8 на single-node не сработают.

---

## Шаг 0. Проверьте multi-node топологию

Кластер из **Lab 01** уже multi-node (1 control-plane + 3 worker). Убедитесь:
```bash
kubectl get nodes
# kind-dtu-control-plane   control-plane
# kind-dtu-worker          <none>
# kind-dtu-worker2         <none>
# kind-dtu-worker3         <none>
```
Видите **3 worker-ноды** → переходите к Шагу 1.

<details>
<summary>Если worker-нод нет (single-node кластер) — развернуть fallback</summary>

`kind` **не умеет добавлять ноды в работающий кластер** — его нужно пересоздать.
⚠️ Это удалит ресурсы предыдущих лаб в этом кластере.

`kind-multinode.yaml`:
```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: kind-dtu
nodes:
- role: control-plane
- role: worker
  labels: {topology.kubernetes.io/zone: zone-a}
- role: worker
  labels: {topology.kubernetes.io/zone: zone-b}
- role: worker
  labels: {topology.kubernetes.io/zone: zone-c}
```
```bash
# в этом окружении kind работает через podman:
KIND_EXPERIMENTAL_PROVIDER=podman kind delete cluster --name kind-dtu
KIND_EXPERIMENTAL_PROVIDER=podman kind create cluster --name kind-dtu --config kind-multinode.yaml
kubectl wait --for=condition=Ready nodes --all --timeout=120s
```
</details>

---

## Шаг 1. Inspect nodes

```bash
kubectl get nodes
# control-plane + 3 worker:
# NAME                       ROLES           ...
# kind-dtu-control-plane     control-plane
# kind-dtu-worker            <none>
# kind-dtu-worker2           <none>
# kind-dtu-worker3           <none>

kubectl get nodes --show-labels
```

> Важно: в kind у **control-plane стоит taint** `node-role.kubernetes.io/control-plane:NoSchedule`,
> поэтому обычные Pod-ы едут только на 3 worker-ноды. Это пригодится в Шаге 7.

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
    image: nginx:1.30
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
    image: nginx:1.30
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
    image: nginx:1.30
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
        nodeTaintsPolicy: Honor                # ← см. примечание ниже
        labelSelector:
          matchLabels: {app: spread}
      containers:
      - name: c
        image: nginx:1.30
```

```bash
kubectl apply -f deploy-spread.yaml
kubectl get pods -o wide -l app=spread
# Pod-ы должны быть распределены равномерно по нодам
```

Подсчитаем распределение:
```bash
kubectl get pods -l app=spread -o wide --no-headers | awk '{print $7}' | sort | uniq -c
#   2 kind-dtu-worker
#   2 kind-dtu-worker2
#   2 kind-dtu-worker3   ← ровно 2/2/2 по трём worker-нодам
```

> **Зачем `nodeTaintsPolicy: Honor`?** По умолчанию (`Ignore`) scheduler считает
> доменом распределения **все** ноды по `topologyKey`, включая tainted
> control-plane, куда Pod-ы поехать не могут. Получается домен с 0 подов, и чтобы
> не превысить `maxSkew: 1`, на каждый worker влезает максимум 1 под → 3 пода
> зависают в `Pending`. `Honor` исключает ноды, чьи taint-ы Pod не толерейтит
> (control-plane), и остаются только 3 worker-ноды → честные 2/2/2.
> (GA с Kubernetes 1.27.)

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
        image: nginx:1.30
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
- `nodeTaintsPolicy: Honor` — чтобы tainted control-plane не ломал расчёт skew
- **Pod Anti-Affinity** — старая форма "не размещать рядом с такими же"
- Use cases: GPU/Spot nodes, dedicated tenancy, HA для production app-ов
