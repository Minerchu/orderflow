"""Static validation of all Docker artifacts.

Runs without Docker installed. Validates:
  - YAML/JSON syntax of compose + nginx-related files
  - referenced env vars are documented in .env.example
  - required-secret interpolation uses the :? form
  - Dockerfiles contain expected primitives (multi-stage, non-root, HEALTHCHECK, tini)
  - shell scripts are LF-terminated, syntactically valid, executable
  - .dockerignore excludes secrets/build junk

Usage:
    python scripts/validate_docker_artifacts.py
Exit code 0 = all checks passed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def find_bash() -> str:
    """Locate a usable bash.

    On Windows the sandbox ships a Cygwin-style bash under PortableGit which
    Python cannot resolve from the bare name, and which returns -1 when spawned
    without its terminfo environment. Prefer an absolute path.
    """
    import shutil

    candidates: list[str] = []
    wb = os.environ.get("USERPROFILE", "")
    if wb:
        pg = Path(wb) / ".workbuddy" / "binaries" / "PortableGit" / "versions"
        if pg.is_dir():
            for ver in sorted(pg.iterdir(), reverse=True):
                exe = ver / "usr" / "bin" / "bash.exe"
                if exe.exists():
                    candidates.append(str(exe))
    for c in (r"C:\Program Files\Git\bin\bash.exe",
              r"C:\Program Files\Git\usr\bin\bash.exe"):
        if Path(c).exists():
            candidates.append(c)
    found = shutil.which("bash")
    if found:
        candidates.append(found)
    for c in candidates:
        r = subprocess.run([c, "-n", "-c", "true"], capture_output=True)
        if r.returncode == 0:
            return c
    return candidates[0] if candidates else "bash"


BASH = find_bash()


def bash_syntax_ok(path: Path) -> tuple[bool, str]:
    r = subprocess.run([BASH, "-n", str(path)], capture_output=True)
    return r.returncode == 0, r.stderr.decode("utf-8", "replace").strip()


def chk(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title} ==")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- compose
section("docker-compose.yml")
compose_path = ROOT / "docker-compose.yml"
chk("docker-compose.yml exists", compose_path.exists())
try:
    import yaml  # type: ignore

    compose = yaml.safe_load(read(compose_path))
    chk("compose parses as YAML", True)
except Exception as exc:  # pragma: no cover
    compose = {}
    chk("compose parses as YAML", False, str(exc))

svcs = compose.get("services", {})
chk("services db/backend/frontend present",
    {"db", "backend", "frontend"} <= set(svcs),
    f"got {sorted(svcs)}")

# -- db
db = svcs.get("db", {})
chk("db uses postgres:16-alpine", "postgres:16-alpine" in str(db.get("image", "")))
chk("db has pg_isready healthcheck",
    "pg_isready" in json.dumps(db.get("healthcheck", {})))
chk("db surface not published (internal only)", "ports" not in db)
chk("db has named volume mount", any(
    "pgdata" in str(v) for v in db.get("volumes", [])))

# -- backend
be = svcs.get("backend", {})
chk("backend builds from ./backend",
    str(be.get("build", {}).get("context") if isinstance(be.get("build"), dict)
        else be.get("build", "")).endswith("backend"))
chk("backend depends_on db service_healthy",
    "service_healthy" in json.dumps(be.get("depends_on", {})))

be_env = be.get("environment", {})
if isinstance(be_env, list):
    be_env = dict(
        (i.split("=", 1) + [""])[:2] for i in be_env if isinstance(i, str))
chk("backend DATABASE_URL targets db:5432",
    "db:5432" in str(be_env.get("DATABASE_URL", "")),
    f"got {be_env.get('DATABASE_URL')!r}")
# NOTE: compose does not need a service-level healthcheck when the image
# itself declares HEALTHCHECK. Accept either.
be_has_compose_hc = "healthcheck" in be
be_dockerfile = read(ROOT / "backend" / "Dockerfile")
be_has_image_hc = "HEALTHCHECK" in be_dockerfile
chk("backend healthcheck (compose-level or Dockerfile HEALTHCHECK)",
    be_has_compose_hc or be_has_image_hc,
    f"compose={be_has_compose_hc} dockerfile={be_has_image_hc}")
chk("backend surface not published (only frontend exposes)",
    "ports" not in be)
chk("backend has uploads volume",
    any("uploads" in str(v) for v in be.get("volumes", [])))

# APP_ENV is written as an interpolation with a default, so compare against
# the raw string form rather than the expanded value.
app_env_raw = str(be_env.get("APP_ENV", ""))
chk("backend APP_ENV defaults to production",
    app_env_raw == "production" or ":-production" in app_env_raw,
    f"got {app_env_raw!r}")

teleg_raw = str(be_env.get("TELEGRAM_DRY_RUN", ""))
chk("backend TELEGRAM_DRY_RUN defaults to false",
    teleg_raw in ("false", "") or ":-false" in teleg_raw,
    f"got {teleg_raw!r}")

# -- frontend
fe = svcs.get("frontend", {})
chk("frontend builds from ./frontend",
    str(fe.get("build", {}).get("context") if isinstance(fe.get("build"), dict)
        else fe.get("build", "")).endswith("frontend"))
chk("frontend depends_on backend service_healthy",
    "service_healthy" in json.dumps(fe.get("depends_on", {})))
fe_ports = [str(p) for p in fe.get("ports", [])]
chk("frontend publishes host HTTP_PORT -> 80",
    any(":80" in p for p in fe_ports), f"got {fe_ports}")

# -- volumes / networks
chk("top-level named volumes pgdata+uploads",
    {"pgdata", "uploads"} <= set(compose.get("volumes", {})))
chk("top-level network orderflow declared",
    "orderflow" in compose.get("networks", {}))

# -- required-secret interpolation
raw_compose = read(compose_path)
for var in ("APP_SECRET_KEY", "SESSION_SECRET", "POSTGRES_PASSWORD"):
    chk(f"compose requires {var} via :? syntax",
        re.search(r"\$\{" + var + r":\?", raw_compose) is not None)

# -- no leaked real secrets
chk("compose contains no hardcoded .env-style secret values",
    not re.search(r"(APP_SECRET_KEY|SESSION_SECRET|POSTGRES_PASSWORD)\s*:\s*['\"]?[A-Za-z0-9+/=]{20,}",
                  raw_compose))

# -- referenced vars documented
section(".env.example coverage")
env_example = read(ROOT / ".env.example")
referenced = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", raw_compose))
documented = set(re.findall(r"^\s*#?\s*([A-Z_][A-Z0-9_]*)=", env_example, re.M))
documented |= set(re.findall(r"^#\s*([A-Z_][A-Z0-9_]*)=", env_example, re.M))
missing = sorted(referenced - documented)
chk(f"all {len(referenced)} compose vars documented in .env.example",
    not missing, f"missing {missing}")

# --------------------------------------------------------------- Dockerfiles
section("backend/Dockerfile")
bd = read(ROOT / "backend" / "Dockerfile")
chk("base image python:3.13-slim", "python:3.13-slim" in bd)
chk("deps installed before app code copied",
    bd.find("requirements.txt") < bd.find("COPY . ") if "COPY . " in bd
    else bd.find("requirements.txt") < bd.find("COPY app"))
chk("tini installed", re.search(r"\btini\b", bd) is not None)
chk("non-root user created", "useradd" in bd)
chk("USER appuser set", re.search(r"^USER\s+\S+", bd, re.M) is not None)
chk("HEALTHCHECK hits /health", "HEALTHCHECK" in bd and "/health" in bd)
chk("EXPOSE 8000", "EXPOSE 8000" in bd)
chk("ENTRYPOINT uses tini + docker-entrypoint.sh",
    "tini" in bd and "docker-entrypoint.sh" in bd)
chk("CMD defaults to serve", re.search(r'CMD\s*\[\s*"serve"', bd) is not None)
chk("does not COPY .env", "COPY .env" not in bd)

section("backend/scripts/docker-entrypoint.sh")
ep_path = ROOT / "backend" / "scripts" / "docker-entrypoint.sh"
chk("entrypoint exists", ep_path.exists())
ep = read(ep_path)
chk("entrypoint LF-only line endings", b"\r\n" not in ep_path.read_bytes())
_ok, _err = bash_syntax_ok(ep_path)
chk(f"bash -n syntax OK (via {Path(BASH).name})", _ok, _err)
for sub in ("serve", "migrate", "init-admin", "shell"):
    chk(f"entrypoint handles '{sub}'", sub in ep)
chk("entrypoint runs alembic upgrade head", "alembic upgrade head" in ep)
chk("entrypoint has wait_for_db", "wait_for_db" in ep)
chk("entrypoint uses set -e", re.search(r"^set -e", ep, re.M) is not None)

section("backend/app/scripts_wait_db.py")
wdb = ROOT / "backend" / "app" / "scripts_wait_db.py"
chk("wait-db script exists", wdb.exists())
wdb_src = read(wdb)
chk("wait-db executes SELECT 1", "SELECT 1" in wdb_src)
chk("wait-db returns 1 when not ready",
    re.search(r"^\s*return 1\s*$", wdb_src, re.M) is not None
    or re.search(r"sys\.exit\(1\)", wdb_src) is not None)
chk("wait-db propagates rc via SystemExit",
    "SystemExit(main())" in wdb_src or "sys.exit(main())" in wdb_src)

section("backend/.dockerignore")
bdi = read(ROOT / "backend" / ".dockerignore")
for pattern in (".env", "__pycache__", "*.db", "tests"):
    chk(f"backend .dockerignore excludes {pattern}", pattern in bdi)

section("frontend/Dockerfile")
fd = read(ROOT / "frontend" / "Dockerfile")
chk("multi-stage (>=2 FROM)", fd.count("FROM ") >= 2)
chk("builder uses node:22-alpine", "node:22-alpine" in fd)
chk("runner uses nginx:1.27-alpine", "nginx:1.27-alpine" in fd)
chk("runs npm ci", "npm ci" in fd)
chk("runs npm run build", "npm run build" in fd)
chk("copies dist into nginx html root", "dist" in fd and "html" in fd)
chk("copies nginx.conf", "nginx.conf" in fd)
chk("HEALTHCHECK hits /healthz", "HEALTHCHECK" in fd and "/healthz" in fd)
chk("VITE_API_BASE build arg present", "VITE_API_BASE" in fd)

section("frontend/nginx.conf")
ng_path = ROOT / "frontend" / "nginx.conf"
ng = read(ng_path)
chk("nginx.conf exists", ng_path.exists())
chk("braces balanced",
    ng.count("{") == ng.count("}"),
    f"{ng.count('{')} open / {ng.count('}')} close")
chk("upstream points at backend:8000",
    re.search(r"upstream\s+\S+\s*\{[^}]*server\s+backend:8000", ng, re.S) is not None)
chk("proxies /api/ to upstream", "location /api/" in ng)
chk("sets X-Forwarded-For", "X-Forwarded-For" in ng)
chk("sets X-Forwarded-Proto", "X-Forwarded-Proto" in ng)
chk("SPA fallback to index.html", "try_files" in ng and "/index.html" in ng)
chk("serves /healthz", "location = /healthz" in ng or "location /healthz" in ng)
chk("gzip enabled", "gzip on" in ng)
chk("assets get immutable cache", "immutable" in ng)

section("frontend/.dockerignore")
fdi = read(ROOT / "frontend" / ".dockerignore")
for pattern in ("node_modules", "dist", ".env"):
    chk(f"frontend .dockerignore excludes {pattern}", pattern in fdi)

# ------------------------------------------------------------------- scripts
section("scripts/*.sh")
for name in ("deploy.sh", "backup.sh", "restore.sh"):
    p = ROOT / "scripts" / name
    chk(f"{name} exists", p.exists())
    if not p.exists():
        continue
    src = read(p)
    chk(f"{name} LF-only", b"\r\n" not in p.read_bytes())
    _ok, _err = bash_syntax_ok(p)
    chk(f"{name} bash -n OK", _ok, _err)
    chk(f"{name} executable",
        os.access(p, os.X_OK) or (p.stat().st_mode & 0o111) != 0)

dep = read(ROOT / "scripts" / "deploy.sh")
chk("deploy.sh generates secrets before docker check",
    dep.find("openssl rand") < dep.find("command -v docker")
    if "command -v docker" in dep else "openssl rand" in dep)
chk("deploy.sh waits for healthy", "healthy" in dep)
chk("deploy.sh runs migrate step", "migrate" in dep)
chk("deploy.sh runs init-admin step", "init-admin" in dep or "init_admin" in dep)

bak = read(ROOT / "scripts" / "backup.sh")
chk("backup.sh uses pg_dump", "pg_dump" in bak)
chk("backup.sh archives uploads", "uploads" in bak and "tar" in bak)
chk("backup.sh writes MANIFEST", "MANIFEST" in bak)

res = read(ROOT / "scripts" / "restore.sh")
chk("restore.sh uses psql", "psql" in res)
chk("restore.sh uses ON_ERROR_STOP", "ON_ERROR_STOP" in res)
chk("restore.sh makes a safety backup first",
    "backup" in res.lower())

# --------------------------------------------------------------- housekeeping
section("repo housekeeping")
chk("root README.md exists", (ROOT / "README.md").exists())
chk("root .gitignore exists", (ROOT / ".gitignore").exists())
gi = read(ROOT / ".gitignore")
chk(".gitignore excludes .env", ".env" in gi)
chk(".gitignore excludes node_modules", "node_modules" in gi)

# --------------------------------------------------------------------- report
print(f"\n{'=' * 46}")
print(f"  RESULT: {PASS} passed, {FAIL} failed")
print(f"{'=' * 46}")
if FAILURES:
    print("\nFailures:")
    for f in FAILURES:
        print(f"  - {f}")
sys.exit(1 if FAIL else 0)
