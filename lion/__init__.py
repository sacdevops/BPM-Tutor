"""Backward-compatibility shim — canonical code is now in lib/lion/."""
from lib.lion import *  # noqa: F401, F403
from lib.lion import LionEncoder, LionDecoder, dumps, loads, strip_markdown_fences  # explicit re-export