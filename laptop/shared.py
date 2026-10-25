"""Load the shared feature module (unoq_app/python/features.py).

It is imported by path under the name "shared_features" because a plain
`import features` from laptop/ would pick up laptop/features.py instead.
"""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED_PATH = REPO / "unoq_app" / "python" / "features.py"


def shared_features():
    if "shared_features" not in sys.modules:
        spec = importlib.util.spec_from_file_location("shared_features", SHARED_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules["shared_features"] = module
        spec.loader.exec_module(module)
    return sys.modules["shared_features"]
