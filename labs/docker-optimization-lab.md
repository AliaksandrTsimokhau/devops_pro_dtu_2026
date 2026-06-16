# Docker (and Podman) — image optimization lab

**Goal.** Take a small Python app that needs C compilers to install its deps, and shrink its image from **~1.05 GB → ~70 MB** through six progressive iterations. Each iteration teaches one specific best practice.

**Why this matters.** Production image size affects:
- **Pull time** in CI/CD and at pod scheduling (cold-start of services)
- **Attack surface** — every tool inside the image is something an attacker can use
- **Storage cost** — registries charge per GB; nodes cache per GB
- **Compliance** — fewer packages → fewer CVEs to triage

**Time.** ~90 minutes to do every iteration end-to-end. Each one is self-contained — you can stop after any iteration.

**Audience.** You've already met the Dockerfile basics. Now you want to know what "production-ready" actually means in concrete commands.

---

## Tooling — Docker or Podman?

Every command in this lab is shown for **both** Docker and Podman. The Dockerfile itself is identical. Pick one and stick with it for the session.

| Operation | Docker | Podman |
|-----------|--------|--------|
| Build | `docker build -t TAG .` | `podman build -t TAG .` |
| Run, throwaway | `docker run --rm -p 5000:5000 TAG` | `podman run --rm -p 5000:5000 TAG` |
| List images | `docker images` | `podman images` |
| Inspect history | `docker history TAG` | `podman history TAG` |
| Remove image | `docker rmi TAG` | `podman rmi TAG` |
| Multi-arch | `docker buildx build --platform=...` | `podman build --platform=...` |
| CVE scan (built-in) | `docker scout cves TAG` | `podman image scan TAG` (or `trivy image TAG`) |
| Disk usage | `docker system df` | `podman system df` |
| Pull base | `docker pull python:3.12-slim` | `podman pull python:3.12-slim` |

> 💡 If you're on Linux without root, install `podman` — it's rootless by default and uses the same OCI image format Docker produces.

---

## Setup

### 1. Workspace

```bash
mkdir docker-optimization-lab && cd docker-optimization-lab
```

### 2. `app.py` — a small Flask app that exercises `cryptography`

```python
from flask import Flask
from cryptography.fernet import Fernet
import os

app = Flask(__name__)
KEY = os.environ.get("APP_KEY", Fernet.generate_key().decode())
cipher = Fernet(KEY.encode())

@app.route("/")
def index():
    token = cipher.encrypt(b"hello from docker").decode()
    return f"signed token: {token}\n"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

### 3. `requirements.txt` — versions pinned for reproducibility

```text
flask==3.0.3
cryptography==42.0.7
gunicorn==22.0.0
```

> `cryptography` is deliberately included. When wheels aren't available for your CPU arch, pip has to compile it from source — which is what forces us to install C build tools and triggers the size explosion we're going to fix.

### 4. Add 50 MB of "junk" that shouldn't ship with the image

This simulates accidentally committed logs / debug dumps / test fixtures.

- **Linux / macOS:** `dd if=/dev/zero of=temp-dump.log bs=1M count=50`
- **Windows (PowerShell):** `fsutil file createnew temp-dump.log 52428800`

---

# Iteration 0 — The naive baseline (~1.05 GB)

**Goal.** Reproduce how an inexperienced engineer writes their first Dockerfile.

### `Dockerfile.0`

```dockerfile
# Naive: full Python image, copy everything, install deps
FROM python:3.12

WORKDIR /app

# Copy EVERYTHING (including temp-dump.log, .git, .env, …)
COPY . .

# Install deps — works because python:3.12 has gcc baked in
RUN pip install -r requirements.txt

CMD ["python", "app.py"]
```

### Build & measure

```bash
# Docker
docker build -f Dockerfile.0 -t lab:0-naive .
docker images lab:0-naive --format "{{.Size}}"

# Podman
podman build -f Dockerfile.0 -t lab:0-naive .
podman images lab:0-naive --format "{{.Size}}"
```

**Observation:** ~**1.05 GB**.

- Full Debian + GCC + dev headers + every Python stdlib component → ~1 GB before we even run pip
- Our 50 MB junk file shipped with it
- Every system tool an attacker could need is in there

> 🎯 **Why this is wrong.** "It works" is not enough. You're shipping a development environment, not a runtime.

---

# Iteration 1 — Context hygiene + cache order (~1.05 GB, but fast rebuilds)

**Goal.** Cut the build context, stop the junk leaking in, and make dependency installation cacheable.

### `.dockerignore` — block junk from ever entering the context

```text
# Big files
temp-dump.log
*.log
*.tar
*.zip

# VCS / dev
.git
.gitignore
.github/
.vscode/
.idea/

# Local cruft
__pycache__/
*.pyc
.venv/
venv/
.env
.env.*

# Other Dockerfiles in this lab
Dockerfile*
README*
```

### `Dockerfile.1` — pin tag, copy deps before code

```dockerfile
# Pin a specific minor version — never use 'latest'
FROM python:3.12.4

WORKDIR /app

# 1. Dependencies first — change rarely, cache-friendly
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2. Application code last — changes most often
COPY app.py .

CMD ["python", "app.py"]
```

### Build & measure

```bash
docker build -f Dockerfile.1 -t lab:1-hygiene .
# OR
podman build -f Dockerfile.1 -t lab:1-hygiene .
```

Now **change `app.py`** (add a print) and rebuild:

```bash
time docker build -f Dockerfile.1 -t lab:1-hygiene .
# OR
time podman build -f Dockerfile.1 -t lab:1-hygiene .
```

**Observation:**

- Image size still ~**1.05 GB** — same base, same deps
- But the rebuild after a code change is **5–10 s** instead of 1–2 min, because pip's layer was cached
- Build context is now KB instead of 50+ MB

> 🎯 **Lesson.** `.dockerignore` and instruction order are *free* wins. Always do them first.

> ⚠ **Tag pinning trade-off.** `python:3.12.4` is reproducible but stops getting security updates. For prod, pin to a digest: `python:3.12-slim@sha256:abcd…` — fully immutable, you decide when to rebase.

---

# Iteration 2 — Slim base + clean up build tools (~400 MB)

**Goal.** Drop the full Debian + dev image. Install only what we need to compile `cryptography`, then remove it in the same layer.

### `Dockerfile.2`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Build tools, install + cleanup, all in ONE layer
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         libffi-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip

# Note: requirements.txt must be present BEFORE the RUN above
# In a real Dockerfile you'd COPY it before the RUN — see below
```

Realistically with proper layering:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         libffi-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip

COPY app.py .

CMD ["python", "app.py"]
```

### Build & measure

```bash
docker build -f Dockerfile.2 -t lab:2-slim .
docker images lab:2-slim --format "{{.Size}}"
# OR
podman build -f Dockerfile.2 -t lab:2-slim .
podman images lab:2-slim --format "{{.Size}}"
```

**Observation:** ~**400 MB**. Down from 1 GB.

- `python:3.12-slim` is ~130 MB instead of ~1 GB
- Build tools added then removed *in the same RUN* → not stored in the final layer
- `pip install --no-cache-dir` → no pip wheel cache left behind
- `rm -rf /root/.cache/pip` is belt-and-braces

> 🎯 **Lesson 1.** Anything you install in a layer is **permanent** — even if you `rm` it in a later layer, the bytes are still there in the lower layer's history. The only way to truly remove something is to never let it land or to remove it within the same `RUN`.

> 🎯 **Lesson 2.** `--no-install-recommends` cuts ~30 % off Debian package installs.

### Inspect layers

```bash
docker history lab:2-slim
# OR
podman history lab:2-slim
```

Notice the single fat `RUN` layer absorbs all the install/remove work.

---

# Iteration 3 — Multi-stage build (~190 MB)

**Goal.** Use a heavy "builder" image to compile deps, then copy only the artifacts into a fresh, pristine runtime.

### `Dockerfile.3`

```dockerfile
# ===== Stage 1 — builder =====
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a self-contained prefix we can later copy wholesale
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ===== Stage 2 — runtime =====
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy ONLY the installed Python packages from the builder
COPY --from=builder /install /usr/local

COPY app.py .

CMD ["python", "app.py"]
```

### Build & measure

```bash
docker build -f Dockerfile.3 -t lab:3-multistage .
docker run --rm -p 5000:5000 lab:3-multistage
# OR
podman build -f Dockerfile.3 -t lab:3-multistage .
podman run --rm -p 5000:5000 lab:3-multistage
```

In another terminal: `curl http://localhost:5000/` — you should see a signed token. The app works despite the runtime stage having no `gcc`.

```bash
docker images lab:3-multistage --format "{{.Size}}"
# OR
podman images lab:3-multistage --format "{{.Size}}"
```

**Observation:** ~**190 MB**. Down from 400 MB.

- The `builder` stage carried `gcc`, `libffi-dev`, dev headers, apt caches → **all discarded**
- Only `/install` (the compiled packages + Python bytecode) crossed the stage boundary
- `gcc` is no longer in the runtime image → attacker can't compile a payload inside

> 🎯 **Lesson.** Multi-stage is the single highest-leverage technique in Dockerfile authoring. If you only adopt one practice, this is it.

### Confirm gcc is gone

```bash
docker run --rm lab:3-multistage which gcc
# (exit code 1 — not found)

# OR
podman run --rm lab:3-multistage which gcc
```

---

# Iteration 4 — Security hardening (~190 MB but production-grade)

**Goal.** Same size — but now: non-root user, OCI labels, healthcheck, exec-form CMD, no extraneous metadata.

### `Dockerfile.4`

```dockerfile
# ===== Stage 1 — builder =====
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ===== Stage 2 — runtime =====
FROM python:3.12-slim AS runtime

# OCI annotations — useful for registries, CVE scanners, supply-chain tooling
LABEL org.opencontainers.image.title="docker-optimization-lab"
LABEL org.opencontainers.image.description="Sample Flask + cryptography app, optimized image."
LABEL org.opencontainers.image.source="https://example.invalid/repo"
LABEL org.opencontainers.image.licenses="MIT"

# Create an unprivileged user (uid:gid 10001:10001 by convention)
RUN groupadd --system --gid 10001 app \
    && useradd  --system --uid 10001 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /install /usr/local

COPY --chown=app:app app.py .

# Drop privileges
USER 10001:10001

# Pythonic runtime hygiene
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/').status==200 else 1)"

# Exec form → PID 1 is python, SIGTERM is delivered to it, graceful shutdown works
CMD ["python", "app.py"]
```

### Build & measure

```bash
docker build -f Dockerfile.4 -t lab:4-hardened .
docker inspect lab:4-hardened --format='{{.Config.User}} | {{.Config.Healthcheck.Test}}'
# OR
podman build -f Dockerfile.4 -t lab:4-hardened .
podman inspect lab:4-hardened --format='{{.Config.User}} | {{.Config.Healthcheck.Test}}'
```

Should print `10001:10001 | [CMD-SHELL python -c …]`.

**Verify the process runs as non-root inside the container:**

```bash
docker run --rm lab:4-hardened id
# uid=10001(app) gid=10001(app) groups=10001(app)

# OR
podman run --rm lab:4-hardened id
```

**Observation:** Size still **~190 MB**. The hardening is essentially free.

> 🎯 **Lesson.** Security-by-default doesn't cost size. Non-root + healthcheck + OCI labels + exec-form CMD are all production table-stakes.

> 💡 **Why non-root matters.** A container breakout that lands as root has many more kernel surfaces to attack. Running as uid 10001 limits the blast radius even before namespace user-remap is configured.

---

# Iteration 5 — Distroless runtime (~70 MB)

**Goal.** Strip the runtime image to the absolute minimum — no shell, no package manager, no `apt`. Just Python and your code.

### `Dockerfile.5`

> ⚠ **Two version-coupling traps to avoid.**
> 1. `gcr.io/distroless/python3-debian12` ships **Python 3.11** (it's built on Debian 12 / Bookworm). The builder **must** use the same `3.11` minor — compiled wheels for `cryptography` are ABI-tied to a specific CPython.
> 2. Distroless's `sys.path` doesn't always include `/usr/local/lib/python3.11/site-packages/`. Instead of guessing what's on `sys.path`, install with `pip --target=/pkg` (flat layout) and add `/pkg` to `PYTHONPATH` — explicit beats implicit.

```dockerfile
# ===== Stage 1 — builder =====
# IMPORTANT: must match runtime Python version (distroless/python3-debian12 → 3.11)
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# --target installs flat into /pkg — no Python-version-specific subdirectory.
# Works regardless of what distroless's site-packages search path is.
RUN pip install --no-cache-dir --target=/pkg -r requirements.txt


# ===== Stage 2 — distroless runtime =====
# Distroless: only the language runtime + its deps. No shell, no apt, no curl.
FROM gcr.io/distroless/python3-debian12:nonroot AS runtime

WORKDIR /app

# The 'nonroot' variant already runs as uid 65532; this line is explicit insurance.
USER nonroot:nonroot

# Copy installed packages and make Python find them via PYTHONPATH
COPY --from=builder /pkg /pkg
ENV PYTHONPATH=/pkg

COPY --chown=nonroot:nonroot app.py .

EXPOSE 5000

# distroless/python3 sets ENTRYPOINT to /usr/bin/python3 — CMD is just the args.
CMD ["app.py"]
```

### Build & measure

```bash
docker build -f Dockerfile.5 -t lab:5-distroless .
docker images lab:5-distroless --format "{{.Size}}"
# OR
podman build -f Dockerfile.5 -t lab:5-distroless .
podman images lab:5-distroless --format "{{.Size}}"
```

**Observation:** ~**70 MB**. About **15× smaller** than the naive baseline.

**Verify it works:**

```bash
docker run --rm -p 5000:5000 lab:5-distroless
# in another shell:
curl http://localhost:5000/
```

**Try to debug inside it:**

```bash
docker run --rm -it lab:5-distroless sh
# error: exec sh: no such file or directory
```

Right — there's no shell. That's the point.

> 🎯 **Lesson 1.** Distroless gets you the smallest possible Python runtime that still works. Attack surface is near-zero.

> 🎯 **Lesson 2.** Debugging is harder — you can't `kubectl exec -- sh`. Use *ephemeral debug containers* (`kubectl debug` / `docker debug`) or attach `busybox` as a sidecar.

> ⚠ **Alternative:** `python:3.12-alpine` is a small image too (~60 MB) but uses musl libc — some Python wheels aren't built for musl and pip falls back to source compilation. Trade-off: smaller but sometimes slower builds and rarer ABI bugs.

---

# Iteration 6 (bonus) — Multi-arch with `buildx` / `podman build --platform`

**Goal.** Build the same image for both `amd64` and `arm64` from a single source.

### Docker (buildx)

```bash
# First time only: create a multi-arch builder backed by BuildKit + QEMU
docker buildx create --name multi --use --bootstrap

# Build and push (multi-arch must push to a registry — can't keep locally)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile.5 \
  -t registry.example.com/myapp:1.0.0 \
  --push .
```

### Podman (built-in, no extra setup)

```bash
podman build \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile.5 \
  --manifest registry.example.com/myapp:1.0.0 \
  .

podman manifest push registry.example.com/myapp:1.0.0
```

**Observation:** the resulting manifest list points at one image per architecture. The pulling client (Docker daemon, Kubernetes kubelet, etc.) automatically picks the right one for its node.

> 💡 **Why multi-arch?** Apple Silicon laptops + AWS Graviton nodes (both `arm64`) make `amd64`-only images a real pain. Building both at once costs minutes; debugging a wrong-arch image at 3am costs hours.

---

# Final leaderboard

Run this to see every iteration's size side-by-side:

```bash
docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep lab:
# OR
podman images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep lab:
```

**Expected (approximate, varies by arch and base image version):**

| Iteration | Tag | Size | Δ from previous | Key technique |
|-----------|-----|------|-----------------|---------------|
| 0 | `lab:0-naive` | ~1.05 GB | — | baseline |
| 1 | `lab:1-hygiene` | ~1.05 GB | 0 % | `.dockerignore` + cache order + pinned tag |
| 2 | `lab:2-slim` | ~400 MB | **-62 %** | slim base + install/remove build tools in one `RUN` |
| 3 | `lab:3-multistage` | ~190 MB | **-53 %** | multi-stage: builder + runtime |
| 4 | `lab:4-hardened` | ~190 MB | 0 % | non-root + OCI labels + healthcheck (security, not size) |
| 5 | `lab:5-distroless` | ~70 MB | **-63 %** | distroless runtime — no shell, minimal CVE surface |

**Net result:** ~**15× smaller** image with **strictly less** attack surface and full multi-arch support.

---

# Inspection toolbox — use these on every image

| What | Docker | Podman |
|------|--------|--------|
| Quick size | `docker images TAG` | `podman images TAG` |
| Layer-by-layer size | `docker history TAG` | `podman history TAG` |
| Full image metadata | `docker inspect TAG` | `podman inspect TAG` |
| What user runs as | `docker inspect TAG --format='{{.Config.User}}'` | `podman inspect TAG --format='{{.Config.User}}'` |
| CVE scan | `docker scout cves TAG` | `podman image scan TAG` or `trivy image TAG` |
| Files inside | `docker run --rm TAG ls /usr/local/lib` | `podman run --rm TAG ls /usr/local/lib` |
| Disk reclaim | `docker system df` then `docker system prune` | `podman system df` then `podman system prune` |
| Dive (deep layer browser) | `dive TAG` | `dive TAG` (same tool) |

> 💡 Install `dive` (https://github.com/wagoodman/dive) for an interactive TUI that shows every file in every layer with size sorting. Invaluable for "what's making this huge?" investigations.

---

# Cleanup

```bash
# Docker
docker rmi lab:0-naive lab:1-hygiene lab:2-slim lab:3-multistage lab:4-hardened lab:5-distroless
docker buildx prune -f
docker system prune -f

# Podman
podman rmi lab:0-naive lab:1-hygiene lab:2-slim lab:3-multistage lab:4-hardened lab:5-distroless
podman system prune -f
```

---

# What to take away

1. **`.dockerignore` and cache order are free** — do them on day one, never lose them.
2. **Anything installed in a layer stays in the image** — install + clean must happen in the *same* `RUN`.
3. **Multi-stage is the highest-leverage technique** — builder gets dirty, runtime stays clean.
4. **Non-root + healthcheck + exec-form CMD don't cost size** — they're table-stakes for production.
5. **Distroless / minimal runtimes** trade debuggability for attack surface — pick by your operability story.
6. **Multi-arch from day one** — Apple Silicon laptops + Graviton nodes make `arm64` mandatory.

**Reading list:**

- Docker docs — Building best practices: https://docs.docker.com/build/building/best-practices/
- Distroless project: https://github.com/GoogleContainerTools/distroless
- `dive`: https://github.com/wagoodman/dive
- Podman build reference: https://docs.podman.io/en/latest/markdown/podman-build.1.html
- Trivy (CVE scanner): https://aquasecurity.github.io/trivy/
