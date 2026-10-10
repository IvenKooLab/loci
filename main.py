"""Entry point: python main.py ingest|search|ask"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from loci.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
