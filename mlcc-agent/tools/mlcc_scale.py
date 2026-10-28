"""Bundle launcher for independent scales, including without DFT dependencies."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mlcc.scale_cli import main

if __name__ == '__main__':
    raise SystemExit(main())
