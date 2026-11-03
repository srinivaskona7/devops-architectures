#!/usr/bin/env python3
"""Deep syntax audit of every fenced code block, including blocks marked nocheck.
Tools used when present: shellcheck (bash), ruff (python), yamllint-style parse + kubeconform (k8s manifests),
terraform fmt (hcl), json, node --check (javascript), jq-free JSON. Writes tools/audit.json and prints a summary.
Usage: audit_code.py [--lang bash] [--folder 03-docker] [--show 40]"""
import re, glob, json, subprocess, sys, tempfile, os, collections, pathlib, yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = pathlib.Path(sys.executable).parent
args = sys.argv[1:]
def opt(n, d=None): return args[args.index(n) + 1] if n in args else d
want_lang, want_folder, show = opt("--lang"), opt("--folder"), int(opt("--show", 30))
def tool(n):
    p = BIN / n
    return str(p) if p.exists() else (subprocess.run(["which", n], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip() or None)
SC, RUFF, TF, KC, NODE = tool("shellcheck"), tool("ruff"), tool("terraform"), tool("kubeconform"), tool("node")
PLACE = re.compile(r"<[A-Za-z][A-Za-z0-9_ -]*>|REPLACE_[A-Z_]+|\.\.\.\s*$|^\s*\.\.\.\s*$", re.M)
VER = yaml.safe_load(open(ROOT / "tools/versions.yaml"))
SUBST = lambda t: re.sub(r"\{\{\s*v\.([a-z0-9_]+)\s*\}\}", lambda m: str(VER.get(m.group(1), m.group(0))), t)
KC_CACHE = os.path.join(tempfile.gettempdir(), "kubeconform-cache"); os.makedirs(KC_CACHE, exist_ok=True)
# Only built-in API groups have schemas; custom resources would be skipped by kubeconform after a failed download each.
CORE_GROUPS = {"v1", "apps", "batch", "networking.k8s.io", "policy", "rbac.authorization.k8s.io", "autoscaling", "storage.k8s.io",
               "scheduling.k8s.io", "admissionregistration.k8s.io", "coordination.k8s.io", "discovery.k8s.io", "node.k8s.io",
               "certificates.k8s.io", "events.k8s.io", "flowcontrol.apiserver.k8s.io", "apiextensions.k8s.io"}
res = collections.defaultdict(list); count = collections.Counter(); skipped = collections.Counter()
def run(cmd, code, suffix):
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as f:
        f.write(code); n = f.name
    try: return subprocess.run([*cmd, n], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    finally: os.unlink(n)
def check(lang, code, attrs):
    if lang in ("bash", "sh", "shell"):
        if not SC: return None
        code = re.sub(r"<([A-Za-z][A-Za-z0-9_ -]*)>", lambda m: "PLACEHOLDER_" + re.sub(r"\W", "_", m.group(1)), code)  # <pod> is a teaching placeholder, not a redirect
        # shellcheck: errors only (severity=error) plus SC2086-style quoting is advice, so we keep it out of the failure list
        r = run([SC, "-s", "bash", "-S", "error", "-f", "gcc"], code, ".sh")
        return None if r.returncode == 0 else (r.stdout.strip().splitlines() or [r.stderr.strip()])[0][:200].split(": ", 1)[-1]
    if lang in ("python", "py"):
        if not RUFF: return None
        r = run([RUFF, "check", "--select", "E9,F63,F7,F82", "--no-cache", "--output-format", "concise"], code, ".py")
        return None if r.returncode == 0 else (r.stdout.strip().splitlines() or [r.stderr.strip()])[0][:200]
    if lang in ("yaml", "yml"):
        try: docs = [d for d in yaml.safe_load_all(code) if d is not None]
        except Exception as e: return "yaml: " + str(e).splitlines()[0][:160]
        if KC and docs and not re.search(r"patch", attrs, re.I) and all(isinstance(d, dict) and str(d.get("apiVersion", "")).split("/")[0] in CORE_GROUPS for d in docs) and all(isinstance(d, dict) and "apiVersion" in d and "kind" in d for d in docs):
            r = run([KC, "-summary", "-ignore-missing-schemas", "-strict", "-cache", KC_CACHE], code, ".yaml")
            if r.returncode: return "kubeconform: " + ((r.stdout + r.stderr).strip().splitlines() or ["?"])[0][:180]
        return None
    if lang == "json":
        try: json.loads(code); return None
        except Exception as e: return "json: " + str(e)[:160]
    if lang in ("hcl", "terraform", "tf"):
        if not TF: return None
        r = subprocess.run([TF, "fmt", "-no-color", "-"], input=code, text=True, capture_output=True, timeout=30)
        return None if r.returncode == 0 else "hcl: " + (r.stderr.strip().splitlines() or ["?"])[0][:180]
    if lang in ("javascript", "js"):
        if not NODE: return None
        r = run([NODE, "--check"], code, ".js")
        return None if r.returncode == 0 else (r.stderr.strip().splitlines() or ["?"])[-1][:160]
    return None
jobs = []
for p in sorted(glob.glob(str(ROOT / "content/*/*.md"))):
    folder = pathlib.Path(p).parent.name
    if want_folder and folder != want_folder: continue
    text = SUBST(open(p).read())
    for m in re.finditer(r"(?ms)^```([A-Za-z0-9_+-]*)([^\n]*)\n(.*?)^```", text):
        lang, attrs, code = (m.group(1) or "text"), m.group(2), m.group(3)
        if want_lang and lang != want_lang: continue
        count[lang] += 1
        if PLACE.search(code) and lang not in ("bash", "sh", "shell") and "<" in code:
            skipped[lang] += 1; continue
        jobs.append((lang, code, attrs, f"{folder}/{pathlib.Path(p).name}", text[:m.start()].count("\n") + 2))
from concurrent.futures import ThreadPoolExecutor
def work(j):
    lang, code, attrs, f, line = j
    try: return j, check(lang, code, attrs)
    except subprocess.TimeoutExpired: return j, "timed out"
    except Exception as e: return j, f"audit error: {e}"
with ThreadPoolExecutor(int(os.environ.get("AUDIT_JOBS", "6"))) as ex:
    for i, (j, bad) in enumerate(ex.map(work, jobs)):
        if bad: res[j[0]].append(dict(file=j[3], line=j[4], nocheck="nocheck" in j[2], msg=bad))
        if i % 100 == 0: print(f"  ... {i}/{len(jobs)}", flush=True)
json.dump(res, open(ROOT / "tools/audit.json", "w"), indent=1)
print("tools:", dict(shellcheck=bool(SC), ruff=bool(RUFF), terraform=bool(TF), kubeconform=bool(KC), node=bool(NODE)))
print(f"{'lang':12s}{'blocks':>7s}{'skipped':>9s}{'problems':>10s}")
for l, n in count.most_common():
    print(f"{l:12s}{n:7d}{skipped[l]:9d}{len(res[l]):10d}")
shown = 0
for l, items in res.items():
    for it in items:
        if shown >= show: break
        print(f"  [{l}] {it['file']}:{it['line']}{' (nocheck)' if it['nocheck'] else ''}  {it['msg']}"); shown += 1

fatal = [it for items in res.values() for it in items if not it["nocheck"]]
print(f"fatal (not marked nocheck): {len(fatal)}")
sys.exit(1 if fatal else 0)
