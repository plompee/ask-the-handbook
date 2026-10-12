import os
import tempfile
from pathlib import Path

# Point the database at a throwaway file before the app is imported.
os.environ["HANDBOOK_DB"] = str(Path(tempfile.mkdtemp(prefix="handbook-test-")) / "test.db")
