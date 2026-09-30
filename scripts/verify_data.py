import json
from pathlib import Path

p = Path("web/audio")
for f in sorted(p.glob("*.mp3")):
    json_path = f.with_name(f.stem + "_timeline.json")
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        print(f"Track: {f.name:<15} Size: {f.stat().st_size:>9,} bytes  Duration: {data['total_duration']:>6.1f}s  Items: {len(data['timeline'])}")
    else:
        print(f"Track: {f.name} (Missing timeline JSON)")
