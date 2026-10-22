import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# .env du dossier timing/ puis celui de la racine du dépôt
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

PG_URI = os.getenv("AIVEN_PG_URI", "")
CH_URI = os.getenv("AIVEN_CH_URI", "")  # https://user:pass@host:port (endpoint HTTPS)
VALKEY_URI = os.getenv("AIVEN_VALKEY_URI", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
