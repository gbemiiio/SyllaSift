"""Backward-compatible alias for the packaged database module."""

import sys

from syllasift.storage import database as _database


sys.modules[__name__] = _database
