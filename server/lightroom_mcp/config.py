"""Constants and paths shared by the server parts."""
from pathlib import Path

HOST = "127.0.0.1"
PORT = 58770                 # first port of the range; also the one an old (0.2.x) plug-in polls
PORT_COUNT = 20             # servers take the first free port in PORT .. PORT + PORT_COUNT - 1

# Shared with the Lightroom plug-in. NOT under AppData: Claude Desktop is an MSIX app and silently
# redirects the AppData of the programs it starts, so Lightroom would not see these files.
DATA_DIR = Path.home() / "LrMcp"
TOKEN_FILE = DATA_DIR / "token"          # legacy: only written by the server that holds PORT (for old plug-ins)
SERVERS_DIR = DATA_DIR / "servers"       # one small text file per running server: port, token, pid
PREVIEW_DIR = DATA_DIR / "previews"
LOG_FILE = DATA_DIR / "server.log"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"   # things the user's AI keeps for the user (named versions, later recipes and notes)
VERSIONS_DIR = KNOWLEDGE_DIR / "versions"
EDIT_DIR = DATA_DIR / "edits"            # one JSON file per change: the old values, so it can be restored
READONLY_FILE = DATA_DIR / "readonly"    # if this file exists, every write is refused (also checked by the plug-in)
MAX_KEYS_PER_EDIT = 30

POLL_HOLD_SECONDS = 10.0        # how long /poll waits for a job before answering "none"
PLUGIN_SEEN_SECONDS = 25.0      # plug-in counts as connected if it polled within this time
CONNECT_WAIT_SECONDS = 6.0      # a call waits this long for a plug-in that is still (re)connecting
PREVIEW_MAX_AGE_SECONDS = 24 * 3600
PREVIEW_MIN_EDGE = 256
PREVIEW_MAX_EDGE = 2048
PREVIEW_DEFAULT_EDGE = 1024
