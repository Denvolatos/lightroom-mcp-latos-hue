"""Constants and paths shared by the server parts."""
from pathlib import Path

HOST = "127.0.0.1"
PORT = 58770

# Shared with the Lightroom plug-in. NOT under AppData: Claude Desktop is an MSIX app and silently
# redirects the AppData of the programs it starts, so Lightroom would not see these files.
DATA_DIR = Path.home() / "LrMcp"
TOKEN_FILE = DATA_DIR / "token"
PREVIEW_DIR = DATA_DIR / "previews"
LOG_FILE = DATA_DIR / "server.log"

POLL_HOLD_SECONDS = 10.0        # how long /poll waits for a job before answering "none"
PLUGIN_SEEN_SECONDS = 25.0      # plug-in counts as connected if it polled within this time
PREVIEW_MAX_AGE_SECONDS = 24 * 3600
PREVIEW_MIN_EDGE = 256
PREVIEW_MAX_EDGE = 2048
PREVIEW_DEFAULT_EDGE = 1024
