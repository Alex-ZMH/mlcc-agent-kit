"""Read the selected native UPF headers in the v100 preparation allocation."""
import json
import os
from pathlib import Path
import re

from mlcc.method_inputs import parse_upf_header
from mlcc.method_tasks import method_pseudopotentials
from mlcc.tasks import utc_now

root = Path(__file__).resolve().parents[2]
method_path = root / "workspace/configs/cazro3-berry-capability-v001.json"
method = json.loads(method_path.read_text(encoding="utf-8"))
site = json.loads((root / "workspace/configs/site.v100-berry-dev-v001.json").read_text(encoding="utf-8"))
raw = {}
headers = {}
for element, filename in method_pseudopotentials(method, site).items():
    text = Path(filename).read_text()
    excerpt = re.search(r'<UPF\b[^>]*>', text).group(0) + "\n" + re.search(r'<PP_HEADER\b[^>]*>', text, re.S).group(0)
    raw[element] = {"source_path": filename, "native_excerpt": excerpt}
    headers[element] = parse_upf_header(excerpt, filename)
snapshot = {"schema": "mlcc.upf-header-snapshot.v1", "observed_at": utc_now(),
            "ssh_alias": site["ssh"]["alias"], "method_set": method["method_set"],
            "headers": headers, "native_excerpts": raw, "scheduler_job_id": os.environ["SLURM_JOB_ID"],
            "inspection": "native_files_read_on_v100_in_Slurm", "numerical_jobs": []}
output = (method_path.parent / method["input_qualification"]["header_snapshot"]).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
with output.open("x", encoding="utf-8") as stream:
    json.dump(snapshot, stream, indent=2)
    stream.write("\n")
print(output)
