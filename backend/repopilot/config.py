import os
from pathlib import Path

# Editable development uses the checkout. Packaged containers explicitly supply /app.
PROJECT_ROOT = Path(
    os.environ.get("REPOPILOT_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
).resolve()
