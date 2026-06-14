# Lab 01 — Install a local Kubernetes cluster

**Цель:** поднять рабочий локальный кластер Kubernetes и проверить связь с ним через `kubectl`.

**Время:** 20–30 минут

---

## Prerequisites

- macOS / Linux / Windows
- ≥ 4 ГБ свободной RAM
- Docker Desktop (или другой Docker engine)

---

## Вариант 1 — Docker Desktop (самый простой)

1. Установите **Docker Desktop**: https://www.docker.com/products/docker-desktop
2. Откройте **Settings → Kubernetes** → ☑ **Enable Kubernetes** → **Apply & restart**.
3. Подождите 1–3 минуты, пока кластер запустится.
4. Убедитесь:
   ```bash
   kubectl version
   kubectl cluster-info
   kubectl get nodes
   ```

**Ожидаемый вывод:** одна нода в состоянии `Ready`.

---

## Вариант 2 — kind (Kubernetes in Docker)

[kind](https://kind.sigs.k8s.io/) — самый быстрый способ поднять кластер с несколькими нодами.

### Установка

macOS:
```bash
brew install kind kubectl
```

Linux:
```bash
[ $(uname -m) = x86_64 ] && curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.22.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/
```

### Создаём multi-node кластер

`kind-config.yaml`:
```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: dtu
nodes:
  - role: control-plane
  - role: worker
  - role: worker
```

```bash
kind create cluster --config kind-config.yaml
kubectl get nodes
```

Должны увидеть 3 ноды (1 control plane + 2 workers).

---

## Вариант 3 — minikube

```bash
brew install minikube              # macOS
minikube start --nodes=2 --driver=docker
kubectl get nodes
```

---

## Проверка кластера

```bash
# Все компоненты кластера
kubectl get pods -n kube-system

# Какой контекст активен
kubectl config current-context

# Все доступные ресурсы
kubectl api-resources | head -30
```

---

## Cleanup (после следующих лабораторных)

```bash
# Docker Desktop: Settings → Kubernetes → Disable / Reset
# kind:
kind delete cluster --name dtu
# minikube:
minikube delete
```

---

## Что вы узнали

- 3 способа получить локальный K8s
- Команды `kubectl version`, `cluster-info`, `get nodes`
- Multi-node кластер через kind (приближено к production-сетапу)
- Что control-plane компоненты живут в `kube-system` namespace
