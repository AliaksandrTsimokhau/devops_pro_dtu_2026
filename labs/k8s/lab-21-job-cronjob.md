# Lab 21 — Job and CronJob

**Цель:** запустить одноразовый Job (с параллелизмом), потом расписание через CronJob.

**Время:** 20 минут
**Prerequisites:** Lab 03.

---

## Шаг 1. Simple Job

`job.yaml`:
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: hello-job
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: hello
        image: busybox
        command: ["sh", "-c", "echo Hello from Job; date; sleep 5; echo Done"]
  backoffLimit: 3
  ttlSecondsAfterFinished: 300            # автоудаление через 5 мин
```

```bash
kubectl apply -f job.yaml
kubectl get jobs --watch
# Через 5-10 секунд: COMPLETIONS 1/1
```

Логи:
```bash
kubectl logs job/hello-job
```

---

## Шаг 2. Parallel Job

`parallel-job.yaml`:
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: parallel-job
spec:
  completions: 10            # всего 10 успешных запусков
  parallelism: 3             # макс 3 одновременно
  backoffLimit: 5
  ttlSecondsAfterFinished: 300
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: worker
        image: busybox
        command: ["sh", "-c", "echo Processing item $HOSTNAME; sleep $((RANDOM % 5 + 2)); echo Done"]
```

```bash
kubectl apply -f parallel-job.yaml
kubectl get jobs parallel-job --watch
# COMPLETIONS будет расти: 0/10 → 3/10 → 6/10 → 10/10

# Сколько Pod-ов было создано
kubectl get pods -l job-name=parallel-job
```

---

## Шаг 3. Indexed Job — шардирование

`indexed-job.yaml`:
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: indexed-job
spec:
  completions: 5
  parallelism: 2
  completionMode: Indexed     # ← каждый Pod получит JOB_COMPLETION_INDEX
  backoffLimit: 3
  ttlSecondsAfterFinished: 300
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: worker
        image: busybox
        command:
        - sh
        - -c
        - 'echo "Shard $JOB_COMPLETION_INDEX of 5"; sleep 5; echo done'
```

```bash
kubectl apply -f indexed-job.yaml
kubectl get pods -l job-name=indexed-job
# Pod-ы будут называться indexed-job-<index>-...

# Логи каждого индекса
for i in 0 1 2 3 4; do
  POD=$(kubectl get pods -l job-name=indexed-job,batch.kubernetes.io/job-completion-index=$i -o jsonpath='{.items[0].metadata.name}')
  echo "--- Shard $i ---"
  kubectl logs $POD
done
```

> Indexed Jobs полезны для batch-обработки: каждый Pod обрабатывает свой шард данных.

---

## Шаг 4. CronJob

`cronjob.yaml`:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: hello-cron
spec:
  schedule: "*/1 * * * *"             # каждую минуту
  concurrencyPolicy: Forbid           # не запускать если предыдущий ещё работает
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      ttlSecondsAfterFinished: 300
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: hello
            image: busybox
            command: ["sh", "-c", "echo Hello at $(date)"]
```

```bash
kubectl apply -f cronjob.yaml
kubectl get cronjobs

# Подождём 2-3 минуты
sleep 120

# Появятся Jobs
kubectl get jobs -l cronjob.kubernetes.io/name=hello-cron

# Логи последнего
LATEST_POD=$(kubectl get pods -l cronjob.kubernetes.io/name=hello-cron --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
kubectl logs $LATEST_POD
```

---

## Шаг 5. concurrencyPolicy variations

| Policy | Поведение |
|---|---|
| `Allow` (default) | Параллельные запуски разрешены |
| `Forbid` | Skip новый запуск если предыдущий не завершён |
| `Replace` | Убить текущий, запустить новый |

```yaml
spec:
  schedule: "*/2 * * * *"
  concurrencyPolicy: Replace
  # Хорошо для tasks где важна актуальность, не накопление
```

---

## Шаг 6. activeDeadlineSeconds — таймаут

```yaml
apiVersion: batch/v1
kind: Job
metadata: {name: timeout-job}
spec:
  activeDeadlineSeconds: 30       # если не завершился за 30 сек — fail
  backoffLimit: 0                  # без повторов
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: long
        image: busybox
        command: ["sh", "-c", "sleep 60"]    # 60 сек — будет терминирован
```

```bash
kubectl apply -f - <<EOF
$(cat above)
EOF
sleep 35
kubectl get jobs timeout-job
# COMPLETIONS: 0/1, STATUS: Failed
```

---

## Шаг 7. Real-world CronJob — backup

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: db-backup
spec:
  schedule: "0 2 * * *"               # каждый день в 02:00
  timeZone: "Europe/Moscow"           # K8s 1.27+
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 7
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      ttlSecondsAfterFinished: 86400  # 24 часа
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: backup
            image: postgres:16
            env:
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef: {name: db-creds, key: password}
            command:
            - sh
            - -c
            - |
              pg_dump -h db -U postgres mydb | gzip > /backups/$(date +%Y%m%d-%H%M%S).sql.gz
            volumeMounts:
            - name: backups
              mountPath: /backups
          volumes:
          - name: backups
            persistentVolumeClaim:
              claimName: backup-storage
```

---

## Cleanup

```bash
kubectl delete -f cronjob.yaml
kubectl delete -f indexed-job.yaml
kubectl delete -f parallel-job.yaml
kubectl delete -f job.yaml
```

---

## Что вы узнали

- **Job** — одноразовая задача, гарантирует успешное завершение
- `parallelism` + `completions` → параллельная обработка
- `completionMode: Indexed` → каждый Pod получает `JOB_COMPLETION_INDEX` (для шардирования)
- `backoffLimit` — макс. число неудачных запусков перед Failed
- `activeDeadlineSeconds` — общий timeout
- `ttlSecondsAfterFinished` — автоудаление (must в production)
- **CronJob** — Job по расписанию (cron syntax)
- `concurrencyPolicy: Forbid` — для backup, ETL
- `timeZone` — K8s 1.27+ (по умолчанию UTC)
- Production use cases: миграции БД, backup, аналитика, очистка
