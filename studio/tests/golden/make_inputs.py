"""Rebuild the golden-set inputs that refkit itself made (golden.json "made_with": gen ... then cutout).

  refkit's python: python studio/tests/golden/make_inputs.py [name ...]

Each is generated with Z-Image at the recorded seed, cut out with BiRefNet and saved as inputs/<name>.png.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from refkit import __main__ as cli  # noqa: E402
from refkit import cutout, gen  # noqa: E402
from refkit.common import SCRATCH  # noqa: E402

HERE = Path(__file__).parent
spec = json.loads((HERE / "golden.json").read_text(encoding="utf-8"))
work = SCRATCH / "golden-inputs"
work.mkdir(parents=True, exist_ok=True)
names = sys.argv[1:] or [k for k, v in spec["inputs"].items() if v.get("prompt")]
for name in names:
    item = spec["inputs"][name]
    seed = int(item["made_with"].split("--seed ")[1].split()[0])
    args = cli.build().parse_args(["gen", item["prompt"], "-m", "z-image", "--seed", str(seed), "--size", "1024x1024",
                                   "--out", str(work)])
    img = Path(gen.main(args)["outputs"][0])
    cut = cutout.cut(img, work)
    shutil.copyfile(cut, HERE / item["file"])
    print("golden input", name, "->", HERE / item["file"])
