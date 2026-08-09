"""Cross-platform smoke test for the published pipx user journey."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], env: dict[str, str], *, expected: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, env=env, capture_output=True, text=True)
    output = (completed.stdout + completed.stderr).strip()
    print(f"$ {' '.join(command)}")
    if output:
        print(output)
    if completed.returncode not in expected:
        raise SystemExit(f"Command exited {completed.returncode}; expected {expected}")
    return completed


def pipx(env: dict[str, str], *arguments: str, expected: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-m", "pipx", *arguments], env, expected=expected)


def main() -> int:
    wheels = sorted(Path("dist").glob("apsara_agentic-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected one Apsara wheel in dist/, found {len(wheels)}")
    wheel = wheels[0].resolve()

    with tempfile.TemporaryDirectory(prefix="apsara-pipx-") as temporary:
        root = Path(temporary)
        home = root / "home"
        binary_dir = root / "bin"
        workspace = root / "workspace"
        home.mkdir()
        binary_dir.mkdir()
        workspace.mkdir()
        env = os.environ.copy()
        env.update({
            "PIPX_HOME": str(home),
            "PIPX_BIN_DIR": str(binary_dir),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "NO_COLOR": "1",
        })

        pipx(env, "install", str(wheel))
        executable = binary_dir / ("apsara.exe" if os.name == "nt" else "apsara")
        if not executable.exists():
            raise SystemExit(f"pipx did not create {executable}")

        run([str(executable), "--version"], env)
        run([str(executable), "--help"], env)
        run([str(executable), "init", "--workspace", str(workspace), "--no-chat", "--no-color"], env)
        if not (workspace / ".apsara" / "config.toml").exists():
            raise SystemExit("First-run initialization did not create .apsara/config.toml")

        doctor = run(
            [str(executable), "doctor", "--workspace", str(workspace), "--no-live", "--no-color"],
            env,
            expected=(0, 1),
        )
        doctor_output = doctor.stdout + doctor.stderr
        if "code-intelligence" not in doctor_output or "No provider configured" not in doctor_output:
            raise SystemExit("Doctor did not explain optional intelligence/provider setup")

        pipx(env, "upgrade", "apsara-agentic")
        run([str(executable), "--version"], env)
        pipx(env, "uninstall", "apsara-agentic")
        listing = pipx(env, "list", "--json")
        installed = json.loads(listing.stdout or "{}").get("venvs", {})
        if "apsara-agentic" in installed:
            raise SystemExit("pipx uninstall left apsara-agentic installed")

    print("pipx lifecycle smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
