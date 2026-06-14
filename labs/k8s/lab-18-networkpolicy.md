# Lab 18 — NetworkPolicy: micro-segmentation

**Цель:** включить default-deny в namespace и точечно разрешить frontend → backend → db.

**Время:** 25 минут
**Prerequisites:** Lab 05.

> ⚠️ Требуется CNI с поддержкой NetworkPolicy: **Cilium** (предпочтительно), Calico, Weave. Flannel basic — НЕ поддерживает! Проверьте: `kubectl get pods -n kube-system | grep -E 'cilium|calico|weave'`.

---

## Шаг 1. Setup — 3 app в одном namespace

`apps.yaml`:
```yaml
apiVersion: v1
kind: Namespace
metadata: {name: zone}
---
# Frontend
apiVersion: apps/v1
kind: Deployment
metadata: {name: frontend, namespace: zone}
spec:
  replicas: 1
  selector: {matchLabels: {app: frontend}}
  template:
    metadata: {labels: {app: frontend}}
    spec:
      containers:
      - name: c
        image: alpine
        command: ["sleep", "3600"]
---
# Backend
apiVersion: apps/v1
kind: Deployment
metadata: {name: backend, namespace: zone}
spec:
  replicas: 1
  selector: {matchLabels: {app: backend}}
  template:
    metadata: {labels: {app: backend}}
    spec:
      containers:
      - name: c
        image: nginx:1.25
        ports: [{containerPort: 80}]
---
apiVersion: v1
kind: Service
metadata: {name: backend, namespace: zone}
spec:
  selector: {app: backend}
  ports: [{port: 80, targetPort: 80}]
---
# DB
apiVersion: apps/v1
kind: Deployment
metadata: {name: db, namespace: zone}
spec:
  replicas: 1
  selector: {matchLabels: {app: db}}
  template:
    metadata: {labels: {app: db}}
    spec:
      containers:
      - name: c
        image: nginx:1.25
        ports: [{containerPort: 80}]
---
apiVersion: v1
kind: Service
metadata: {name: db, namespace: zone}
spec:
  selector: {app: db}
  ports: [{port: 80, targetPort: 80}]
```

```bash
kubectl apply -f apps.yaml
kubectl get all -n zone
```

---

## Шаг 2. Baseline — все могут всё

```bash
FRONTEND=$(kubectl get pods -n zone -l app=frontend -o jsonpath='{.items[0].metadata.name}')

# Frontend может ходить в backend и db
kubectl exec -n zone $FRONTEND -- wget -qO- --timeout=2 backend:80
# должен вернуть nginx welcome page

kubectl exec -n zone $FRONTEND -- wget -qO- --timeout=2 db:80
# тоже работает

# Резолвится DNS
kubectl exec -n zone $FRONTEND -- nslookup backend
```

---

## Шаг 3. Default-deny all egress

`deny-all.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: zone
spec:
  podSelector: {}            # все Pod-ы в namespace
  policyTypes: [Ingress, Egress]
```

```bash
kubectl apply -f deny-all.yaml

# Проверим — всё должно отвалиться
kubectl exec -n zone $FRONTEND -- wget -qO- --timeout=2 backend:80
# timeout

kubectl exec -n zone $FRONTEND -- nslookup backend
# тоже timeout — даже DNS не работает!
```

---

## Шаг 4. Allow DNS — обязательно

`allow-dns.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: zone
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

```bash
kubectl apply -f allow-dns.yaml

# Теперь DNS работает
kubectl exec -n zone $FRONTEND -- nslookup backend
# но к самому backend всё ещё нет доступа
kubectl exec -n zone $FRONTEND -- wget -qO- --timeout=2 backend:80
# timeout
```

---

## Шаг 5. Allow frontend → backend

`allow-frontend-to-backend.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: zone
spec:
  # На стороне получателя — backend
  podSelector:
    matchLabels:
      app: backend
  policyTypes: [Ingress]
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - port: 80
---
# И симметрично — разрешим frontend ВЫХОДИТЬ
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-egress-backend
  namespace: zone
spec:
  podSelector:
    matchLabels:
      app: frontend
  policyTypes: [Egress]
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - port: 80
```

```bash
kubectl apply -f allow-frontend-to-backend.yaml

# Проверим
kubectl exec -n zone $FRONTEND -- wget -qO- --timeout=2 backend:80
# должно работать!

# А к db всё ещё нет
kubectl exec -n zone $FRONTEND -- wget -qO- --timeout=2 db:80
# timeout
```

---

## Шаг 6. Allow backend → db

```yaml
# allow-backend-to-db.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-backend-to-db, namespace: zone}
spec:
  podSelector: {matchLabels: {app: db}}
  policyTypes: [Ingress]
  ingress:
  - from:
    - podSelector: {matchLabels: {app: backend}}
    ports:
    - port: 80
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: backend-egress-db, namespace: zone}
spec:
  podSelector: {matchLabels: {app: backend}}
  policyTypes: [Egress]
  egress:
  - to:
    - podSelector: {matchLabels: {app: db}}
    ports:
    - port: 80
```

```bash
kubectl apply -f allow-backend-to-db.yaml

BACKEND=$(kubectl get pods -n zone -l app=backend -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n zone $BACKEND -- curl --max-time 2 db:80
# должно работать

# frontend всё ещё НЕ может в db напрямую — это правильно (защита in depth)
kubectl exec -n zone $FRONTEND -- wget -qO- --timeout=2 db:80
# timeout ✅
```

---

## Шаг 7. Cross-namespace policy

```yaml
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        env: production
    podSelector:
      matchLabels:
        app: api
  ports:
  - port: 80
```

> namespace label `env: production` нужно поставить вручную:
> `kubectl label ns prod env=production`

---

## Cleanup

```bash
kubectl delete ns zone
```

---

## Что вы узнали

- **NetworkPolicy** требует CNI с поддержкой (Cilium, Calico)
- Default state: всё разрешено → NetworkPolicy переключают на **deny-by-default**
- **Default-deny-all** + explicit allow rules — это canonical pattern
- **Allow DNS** обязательно — без него все timeout-ы
- Двусторонний контроль: Ingress (получатель) + Egress (отправитель)
- Cross-namespace через `namespaceSelector`
- Production: micro-segmentation per business function (frontend → backend → db)
