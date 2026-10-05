"""支持 `python3 -m perf_compare`。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
