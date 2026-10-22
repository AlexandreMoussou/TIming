"""Crée (ou met à jour) le service Aiven Runtime `voyage-app` à partir d'un dépôt Git.

Les URIs Aiven et la clé Anthropic sont lues dans .env et passées en variables de type secret.
Usage (racine du dépôt) : python voyage/deploy_aiven.py <repository_url> [branche]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
env = dotenv_values(ROOT / ".env")
repo, branch = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "main")
SERVICE, PROJECT, CLOUD, PLAN = "voyage-app", "timing", "google-europe-west1", "startup-20-512"

secrets = [{"key": k, "value": env[k], "kind": "secret"}
           for k in ("AIVEN_PG_URI", "AIVEN_CH_URI", "AIVEN_VALKEY_URI", "ANTHROPIC_API_KEY") if env.get(k)]
config = {
    "environment_variables": secrets + [{"key": "PORT", "value": "8080", "kind": "variable"}],
    "ports": [{"name": "web", "port": 8080, "protocol": "HTTP"}],
    "source": {"repository_url": repo, "branch": branch, "build_path": "voyage",
               "containerfile_path": "voyage/Containerfile"},
}
cfg = ["-c", "application.environment_variables=" + json.dumps(config["environment_variables"]),
       "-c", "application.ports=" + json.dumps(config["ports"])]
for k, v in config["source"].items():
    cfg += ["-c", f"application.source.{k}={v}"]
os.environ["AIVEN_AUTH_TOKEN"] = env["AIVEN_AUTH_TOKEN"]
exists = subprocess.run(["avn", "service", "get", SERVICE, "--project", PROJECT], capture_output=True).returncode == 0
cmd = (["avn", "service", "update", SERVICE, "--project", PROJECT] if exists else
       ["avn", "service", "create", SERVICE, "--project", PROJECT, "--service-type", "application",
        "--cloud", CLOUD, "--plan", PLAN]) + cfg
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout[-2000:], r.stderr[-2000:].replace(env.get("ANTHROPIC_API_KEY", "\0"), "***"))
sys.exit(r.returncode)
