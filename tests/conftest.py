"""Test bootstrap.

The integration's ``__init__.py`` imports Home Assistant, which is not
installed in the lightweight test environment. We register a stub package
module pointing at the component directory so ``hikvision_userpin.client``
(and its relative ``from .const import ...``) can be imported on its own,
without executing ``__init__.py``.
"""

import sys
import types
from pathlib import Path

PKG_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "hikvision_userpin"
)

if "hikvision_userpin" not in sys.modules:
    pkg = types.ModuleType("hikvision_userpin")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["hikvision_userpin"] = pkg
