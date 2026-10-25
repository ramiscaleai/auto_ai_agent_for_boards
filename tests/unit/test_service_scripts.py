import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [
    ROOT / "scripts" / "service" / "install.sh",
    ROOT / "scripts" / "service" / "run_agent.sh",
    ROOT / "scripts" / "service" / "uninstall.sh",
]


def test_service_scripts_are_valid_bash():
    for script in SCRIPTS:
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_run_agent_uses_private_runtime_dir():
    text = (ROOT / "scripts" / "service" / "run_agent.sh").read_text()
    assert "/tmp/auto_ai_agent" not in text
    assert "install -d -m 700" in text
