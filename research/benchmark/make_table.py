"""Rebuild the markdown table of a results file from its JSON (e.g. after the table format changed).

  python research/benchmark/make_table.py research/results/<run>.json [more.json ...]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_benchmark import save  # noqa: E402

for name in sys.argv[1:]:
    path = Path(name)
    data = json.loads(path.read_text())
    save(path, data)
    print(f"rebuilt {path.with_suffix('.md')}")
