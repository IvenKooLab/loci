"""入口：python main.py ingest|search|ask"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from second_brain.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
