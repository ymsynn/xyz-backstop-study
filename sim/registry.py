"""Design registry (docs/registry.json): the formulas' terms, the propositions that change them, and every test.

Analysis scripts record their results here, so that no figure or table in the paper is a hand-typed number:
    REG=<test id> REG_MAP="scenario=design,..." python sim/score/takeover_score.py base noclamp own_et_self30
A test is upserted by id; its results are replaced as a whole, so rerunning a script refreshes it.
Results carry no vault PnL (scenario PnL depends on the untestable unwind; see docs/spec/proposal_spec.md, reporting rule).
"""
import datetime, json, os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "docs", "registry.json")
BANNED = {"vault_pnl", "pnl"}


def load():
    with open(PATH) as f:
        return json.load(f)


def save(reg):
    reg["updated"] = datetime.date.today().isoformat()
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(reg, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, PATH)


def commit():
    try:
        h = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", "engine", "sim"], capture_output=True, text=True).stdout.strip()
        return h + ("+dirty" if dirty else "")
    except Exception:
        return None


def design_map():
    """REG_MAP="scenario=design,..." -> dict."""
    m = os.environ.get("REG_MAP", "")
    return dict(kv.split("=", 1) for kv in m.split(",") if "=" in kv)


def record(test_id, results, **meta):
    """results: list of dicts with 'design' plus metric fields (and optionally 'coin', 'case')."""
    for r in results:
        bad = BANNED & set(r)
        if bad:
            raise ValueError(f"registry refuses {bad}: scenario vault PnL is not a result")
    reg = load()
    t = next((t for t in reg["tests"] if t["id"] == test_id), None)
    if t is None:
        t = {"id": test_id}
        reg["tests"].append(t)
    if os.environ.get("REG_MERGE") == "1":   # replace only the designs this run produced
        mine = {r["design"] for r in results}
        if t.get("command") and meta.get("command") and meta["command"] not in t["command"]:
            meta["command"] = t["command"] + " ; " + meta["command"]
        results = [r for r in t.get("results", []) if r["design"] not in mine] + results
    t.update(meta)
    t["results"] = results
    t["source"] = "script"
    t["recorded"] = datetime.date.today().isoformat()
    t["commit"] = commit()
    save(reg)
    print(f"registry: {test_id} <- {len(results)} results")


def maybe_record(results, **meta):
    """Record only when REG is set; scripts call this unconditionally."""
    tid = os.environ.get("REG")
    if tid:
        record(tid, results, **meta)
