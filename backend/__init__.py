"""Makes the repo root importable so sibling top-level modules
(resume_contact.py, app/) can be imported from anywhere in this package.
Runs once, before any backend submodule, since Python initializes a
package's __init__.py before importing any of its submodules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
