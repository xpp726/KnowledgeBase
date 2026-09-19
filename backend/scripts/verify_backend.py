"""部署前后端验收脚本。

默认执行 Alembic 一致性检查、Python 编译检查、旧分层依赖扫描、真实基础设施
健康检查和全量测试。生产环境可用 ``--skip-tests`` 跳过测试，只保留部署前检查。
"""

from __future__ import annotations

import argparse
import asyncio
import compileall
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
LEGACY_IMPORT = re.compile(
    r"(?:from\s+app\.(?:db|models|services)|import\s+app\.(?:db|models|services))\b"
)
SCAN_DIRS = (ROOT / "app", ROOT / "scripts", ROOT / "tests", ROOT / "migrations")


def run_command(label: str, *args: str) -> None:
    print(f"\n=== {label} ===")
    result = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")


def scan_legacy_imports() -> None:
    print("\n=== legacy import scan ===")
    matches: list[str] = []
    for directory in SCAN_DIRS:
        for path in directory.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if LEGACY_IMPORT.search(line):
                    matches.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
    if matches:
        raise RuntimeError("legacy imports found:\n" + "\n".join(matches))
    print("NO_LEGACY_IMPORTS")


def _failed_health_paths(value, prefix: str = "") -> list[str]:
    failures: list[str] = []
    if isinstance(value, dict):
        if value.get("ok") is False:
            failures.append(prefix or "health")
        for key, child in value.items():
            if key != "ok":
                failures.extend(_failed_health_paths(child, f"{prefix}.{key}".strip(".")))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            failures.extend(_failed_health_paths(child, f"{prefix}[{index}]"))
    return failures


async def check_health() -> None:
    from app.infrastructure.health.checks import full_health

    print("\n=== infrastructure health ===")
    result = await full_health()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failures = _failed_health_paths(result)
    if failures:
        raise RuntimeError("health checks failed: " + ", ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="KnowledgeBase backend verification")
    parser.add_argument("--skip-tests", action="store_true", help="skip pytest")
    parser.add_argument("--skip-health", action="store_true", help="skip real service probes")
    args = parser.parse_args()

    try:
        run_command("alembic check", "-m", "alembic", "check")
        if not compileall.compile_dir(str(ROOT / "app"), quiet=1):
            raise RuntimeError("Python compilation failed")
        if not compileall.compile_dir(str(ROOT / "scripts"), quiet=1):
            raise RuntimeError("script compilation failed")
        if not compileall.compile_dir(str(ROOT / "tests"), quiet=1):
            raise RuntimeError("test compilation failed")
        print("\n=== compileall ===\nOK")
        scan_legacy_imports()
        if not args.skip_health:
            asyncio.run(check_health())
        if not args.skip_tests:
            run_command("pytest", "-m", "pytest", "-q")
    except Exception as exc:  # noqa: BLE001
        print(f"\nVERIFY_FAILED: {exc}", file=sys.stderr)
        return 1

    print("\nVERIFY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
