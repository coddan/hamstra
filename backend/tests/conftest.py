import os
import tempfile

os.environ["ARR_DATA_DIR"] = tempfile.mkdtemp(prefix="arr-test-")
os.environ["ARR_TMDB_API_KEY"] = ""
os.environ["ARR_SCHEDULER_ENABLED"] = "false"
os.environ["ARR_API_KEY"] = "change-me"
os.environ["ARR_MIN_FREE_GB"] = "0"
