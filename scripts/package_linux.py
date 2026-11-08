"""生成不含运行数据、秘密和构建缓存的 Linux Docker 源码包并核验。"""
from pathlib import Path
import hashlib
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT.parent / "outputs" / "orderflow-linux-docker-v2.zip"
EXCLUDED = {
    "node_modules", "dist", "uploads", "data", "backups", "backup", "secrets",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    ".git", ".venv", "venv", "env", "coverage", ".idea", ".vscode",
}
SUFFIXES = {".py", ".ts", ".vue", ".json", ".html", ".css", ".md", ".txt",
            ".yml", ".yaml", ".ini", ".mako", ".sh", ".conf"}
SPECIAL = {"Dockerfile", ".dockerignore", ".gitignore", ".env.example"}


def include(path):
    relative = path.relative_to(ROOT)
    if any(part.lower() in EXCLUDED for part in relative.parts):
        return False
    if path.is_symlink():
        return False
    name = path.name.lower()
    if name.startswith(".env") and name != ".env.example":
        return False
    if any(word in name for word in ("secret", "backup", "credential")) and path.name != "backup.sh":
        return False
    return path.name in SPECIAL or path.suffix in SUFFIXES


def main():
    if not OUTPUT.parent.is_dir():
        raise RuntimeError("请先创建 outputs 目录")
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and include(p))
    # x 模式禁止覆盖任何旧包。
    with zipfile.ZipFile(OUTPUT, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = "orderflow/" + path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (0o100755 if path.suffix == ".sh" else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert all(not any(part.lower() in EXCLUDED for part in Path(n).parts) for n in names)
        assert all(not Path(n).name.startswith(".env") or Path(n).name == ".env.example" for n in names)
        keys = ["docker-compose.yml", ".env.example", "backend/.env.example", "README.md",
                "backend/Dockerfile", "frontend/Dockerfile", "frontend/package-lock.json",
                "backend/app/services/telegram_bot.py", "backend/tests/test_telegram.py",
                "frontend/src/views/admin/OrdersView.vue", "scripts/deploy.sh"]
        with tempfile.TemporaryDirectory(prefix="orderflow-zip-verify-") as folder:
            for key in keys:
                extracted = Path(archive.extract("orderflow/" + key, folder))
                assert extracted.read_bytes() == (ROOT / key).read_bytes(), key
        for info in archive.infolist():
            if info.filename.endswith(".sh"):
                assert (info.external_attr >> 16) & 0o111
                assert b"\r\n" not in archive.read(info)
    print(f"ZIP: {OUTPUT}")
    print(f"FILES: {len(files)}; BYTES: {OUTPUT.stat().st_size}")
    print("testzip、排除规则、关键文件解压比对及 Linux 脚本权限校验通过")
    print("SHA256: " + hashlib.sha256(OUTPUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
