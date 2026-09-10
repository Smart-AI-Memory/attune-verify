"""Build/install a wheel and exercise its CLI outside the source checkout."""

import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> None:
    """Check packaged API/CLI using only a temporary installed environment."""
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="attune-wheel-") as directory:
        work = Path(directory)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(work / "dist"),
            ],
            cwd=root,
            check=True,
        )
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        wheel = next((work / "dist").glob("*.whl"))
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True)
        doc = work / "api.md"
        doc.write_text(
            "```python\nfrom attune_verify import verify, VerifyContext\n```", encoding="utf-8"
        )
        clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        for args in (
            ["check", "api.md", "--format", "json"],
            ["receipts", "api.md", "--output", "receipts.json"],
            ["impact", "receipts.json"],
        ):
            result = subprocess.run(
                [str(python), "-m", "attune_verify", *args],
                cwd=work,
                env=clean_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            report = json.loads(result.stdout)
            assert report.get("passed", True)
            assert not report.get("needs_recheck", False)
        # A checkout receipt must request rechecking when moved to the wheel's
        # interpreter/artifacts, then the installed receipt above stays stable.
        source_env = {**clean_env, "PYTHONPATH": str(root / "src")}
        subprocess.run(
            [
                sys.executable,
                "-m",
                "attune_verify",
                "receipts",
                "api.md",
                "--output",
                "checkout-receipts.json",
            ],
            cwd=work,
            env=source_env,
            capture_output=True,
            check=True,
        )
        comparison = subprocess.run(
            [str(python), "-m", "attune_verify", "impact", "checkout-receipts.json"],
            cwd=work,
            env=clean_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert comparison.returncode == 1, comparison.stderr
        assert all(
            row["status"] == "recheck" for row in json.loads(comparison.stdout)["observations"]
        )
        executable = environment / (
            "Scripts/attune-verify.exe" if os.name == "nt" else "bin/attune-verify"
        )
        subprocess.run([str(executable), "check", "api.md"], cwd=work, env=clean_env, check=True)
        print("Installed wheel API, CLI, receipts and impact: passed")


if __name__ == "__main__":
    main()
