# Lab 08 — Service types: ClusterIP, NodePort, LoadBalancer

**Цель:** разобраться с тремя основными типами Service, увидеть как они построены друг на друге.

**Время:** 25 минут
**Prerequisites:** Lab 06.

---

## Шаг 1. Bootstrap — поднимем Deployment

`deploy.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: svc-test
spec:
  replicas: 5
  selector:
    matchLabels:
      chapter: services
  template:
    metadata:
      labels:
        chapter: services
    spec:
      containers:
      - name: web
        image: nigelpoulton/k8sbook:1.0
        ports:
        - containerPort: 8080
```

```bash
kubectl apply -f deploy.yaml
kubectl get pods -l chapter=services -o wide
```

Запомните Pod IPs.

---

## Шаг 2. ClusterIP — внутренний

`clusterip.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: cip
spec:
  type: ClusterIP                # default; можно опустить
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    chapter: services
```

```bash
kubectl apply -f clusterip.yaml
kubectl get svc cip
kubectl describe svc cip
```

Обратите внимание на `Endpoints:` — там IP всех Pod-ов с label `chapter=services`.

```bash
kubectl get endpointslices -l kubernetes.io/service-name=cip
```

### Проверка из кластера

```bash
kubectl run debug --rm -it --image=alpine -- sh
# внутри:
apk add curl bind-tools
nslookup cip                              # → ClusterIP
curl http://cip:8080                      # должно работать
exit
```

> ClusterIP **не достижим** снаружи кластера.

---

## Шаг 3. NodePort — внешний доступ через порт нод

`nodeport.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: np
spec:
  type: NodePort
  ports:
  - port: 8080
    targetPort: 8080
    nodePort: 30080
  selector:
    chapter: services
```

```bash
kubectl apply -f nodeport.yaml
kubectl get svc np
```

Колонка PORT: `8080:30080/TCP`.

### Проверка

Найдите IP ноды:
```bash
kubectl get nodes -o wide
```

И обратитесь снаружи:
```bash
curl http://<NODE-IP>:30080
# или для Docker Desktop:
curl http://localhost:30080
```

> NodePort всегда в диапазоне 30000–32767.

---

## Шаг 4. LoadBalancer — облачный LB

`loadbalancer.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: lb
spec:
  type: LoadBalancer
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    chapter: services
```

```bash
kubectl apply -f loadbalancer.yaml
kubectl get svc lb
```

- **Docker Desktop**: `EXTERNAL-IP` = `localhost`
- **kind**: `<pending>` (без MetalLB)
- **Cloud**: реальный публичный IP через 30–60 сек

```bash
curl http://localhost:8080                # Docker Desktop
```

---

## Шаг 5. Сравнение

```bash
kubectl get svc
# NAME   TYPE           CLUSTER-IP       EXTERNAL-IP   PORT(S)
# cip    ClusterIP      10.96.x.x        <none>        8080/TCP
# np     NodePort       10.96.x.x        <none>        8080:30080/TCP
# lb     LoadBalancer   10.96.x.x        localhost     8080:31755/TCP
```

LoadBalancer **построен поверх** NodePort, который **построен поверх** ClusterIP. Поэтому у LB есть и ClusterIP, и NodePort (даже если вы их не указывали).

---

## Шаг 6. EndpointSlice — список здоровых Pod-ов

```bash
kubectl get endpointslices
kubectl describe endpointslice <name>
# Раздел Endpoints — IP всех Pod-ов с матчингом selector
# Conditions:
#   Ready: true              ← только Ready Pod-ы получают трафик
```

Попробуйте удалить один Pod:
```bash
kubectl delete pod <pod-name>
# Через 2 секунды EndpointSlice обновится — там 4 Pod-а вместо 5
```

---

## Cleanup

```bash
kubectl delete -f loadbalancer.yaml -f nodeport.yaml -f clusterip.yaml -f deploy.yaml
```

---

## Что вы узнали

- 3 типа Service: ClusterIP (внутренний) / NodePort (порт ноды) / LoadBalancer (облачный LB)
- Каждый следующий type построен поверх предыдущего
- EndpointSlice — динамический список здоровых Pod-ов
- Только Pod-ы прошедшие readiness попадают в EndpointSlice
- Service ↔ Pod связь — через **label selector**
