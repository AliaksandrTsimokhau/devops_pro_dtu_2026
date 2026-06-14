# Lab 16 — Explore K8s API + define a CRD

**Цель:** прямой доступ к Kubernetes REST API через kubectl proxy и создание собственного CRD.

**Время:** 25 минут
**Prerequisites:** Lab 02.

---

## Часть A — explore API через kubectl proxy

### Шаг 1. Запустить proxy

```bash
kubectl proxy --port 9000 &
# Forwarding from 127.0.0.1:9000

# Если позже захотите остановить:
# ps | grep "kubectl proxy"
# kill <pid>
```

### Шаг 2. List API groups

```bash
# Core group
curl http://localhost:9000/api
# {"versions":["v1"]}

# Named groups
curl http://localhost:9000/apis | python3 -m json.tool | head -30
```

### Шаг 3. List resources

```bash
# Namespaces
curl http://localhost:9000/api/v1/namespaces | python3 -m json.tool | head

# Pods in default namespace
curl http://localhost:9000/api/v1/namespaces/default/pods | python3 -m json.tool | head

# Deployments
curl http://localhost:9000/apis/apps/v1/namespaces/default/deployments
```

### Шаг 4. Create через POST

`ns.json`:
```json
{
  "kind": "Namespace",
  "apiVersion": "v1",
  "metadata": {
    "name": "api-test"
  }
}
```

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  --data-binary @ns.json \
  http://localhost:9000/api/v1/namespaces

# Verify
kubectl get ns api-test
```

### Шаг 5. Delete через DELETE

```bash
curl -X DELETE http://localhost:9000/api/v1/namespaces/api-test
```

---

## Часть B — Custom Resource Definition (CRD)

### Шаг 6. Создаём CRD

`crd-book.yaml`:
```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: books.dtu.local
spec:
  group: dtu.local
  scope: Namespaced
  names:
    plural: books
    singular: book
    kind: Book
    shortNames: [bk]
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              title: {type: string}
              author: {type: string}
              edition: {type: integer}
              topic: {type: string}
            required: [title, author]
    additionalPrinterColumns:
    - name: Title
      type: string
      jsonPath: .spec.title
    - name: Author
      type: string
      jsonPath: .spec.author
```

```bash
kubectl apply -f crd-book.yaml
kubectl get crd books.dtu.local
kubectl api-resources | grep books
# books   bk   dtu.local/v1   true   Book
```

### Шаг 7. Создаём Custom Object

`book1.yaml`:
```yaml
apiVersion: dtu.local/v1
kind: Book
metadata:
  name: k8s-book
spec:
  title: "The Kubernetes Book"
  author: "Nigel Poulton"
  edition: 2024
  topic: "Kubernetes"
```

```bash
kubectl apply -f book1.yaml

# Используем shortname
kubectl get bk
# NAME       TITLE                 AUTHOR
# k8s-book   The Kubernetes Book   Nigel Poulton

# Полные данные
kubectl get book k8s-book -o yaml
```

### Шаг 8. Query через proxy

```bash
curl http://localhost:9000/apis/dtu.local/v1/namespaces/default/books | python3 -m json.tool
```

### Шаг 9. Validation работает

```yaml
# Bad book (нет required field 'author'):
cat <<EOF | kubectl apply -f -
apiVersion: dtu.local/v1
kind: Book
metadata:
  name: incomplete
spec:
  title: "Only Title"
EOF
# Error from server: spec.author is required
```

---

## Шаг 10. Понятие Operator

CRD сам по себе ничего не делает. Чтобы Book "что-то делал" — нужен Controller (Operator), который смотрит на эти объекты.

Примеры real-world Operators:
- **cert-manager** — Certificate, Issuer CRDs → выпускает сертификаты
- **Prometheus Operator** — ServiceMonitor, PrometheusRule CRDs
- **CloudNativePG** — Cluster CRD → создаёт Postgres cluster
- **ArgoCD** — Application CRD → синкает Git в кластер

Operator framework: **Kubebuilder** (Go) или **Operator SDK** (Go / Ansible / Helm).

---

## Cleanup

```bash
# Остановить proxy
kill $(ps | grep "kubectl proxy" | grep -v grep | awk '{print $1}')

kubectl delete -f book1.yaml
kubectl delete -f crd-book.yaml
```

---

## Что вы узнали

- Kubernetes API — RESTful, доступен через `kubectl proxy`
- Все ресурсы лежат под `/api/v1/...` (core) или `/apis/<group>/<version>/...`
- CRUD через стандартные HTTP методы: POST / GET / PUT / PATCH / DELETE
- CRD = добавляем свой тип ресурса в API
- CRD + Controller = Operator pattern
- OpenAPI schema в CRD валидирует данные
- `additionalPrinterColumns` — кастомные колонки в `kubectl get`
