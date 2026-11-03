#!/usr/bin/env python3
"""Rebuild the Shop deploy/ tree from the page code blocks and render every overlay with kubectl kustomize,
then validate the rendered output with kubeconform. Exit 1 on any failure."""
import re, glob, pathlib, subprocess, shutil, yaml, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
out = pathlib.Path("/tmp/shopdeploy"); shutil.rmtree(out, ignore_errors=True); out.mkdir()
VER = yaml.safe_load(open(ROOT / "tools/versions.yaml"))
sub = lambda t: re.sub(r"\{\{\s*v\.([a-z0-9_]+)\s*\}\}", lambda m: str(VER.get(m.group(1), m.group(0))), t)
for p in sorted(glob.glob(str(ROOT / "content/14-sample-app-shop/*.md"))):
    for m in re.finditer(r'(?ms)^```(\w+) title="([^"]+)"([^\n]*)\n(.*?)^```', sub(open(p).read())):
        title = m.group(2)
        if re.match(r"^deploy/[\w./-]+\.ya?ml$", title) and "nocheck" not in m.group(3):
            f = out / title; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(m.group(4))
import os, tempfile
CACHE = os.path.join(tempfile.gettempdir(), "kubeconform-cache"); os.makedirs(CACHE, exist_ok=True)
bad = 0
for ov in ["base", "overlays/dev", "overlays/staging", "overlays/prod", "overlays/prod-azure"]:
    r = subprocess.run(["kubectl", "kustomize", str(out / "deploy" / ov)], capture_output=True, text=True)
    if r.returncode:
        bad += 1; print(f"FAIL render {ov}: {r.stderr.strip().splitlines()[0][:230]}"); continue
    k = subprocess.run(["kubeconform", "-strict", "-summary", "-ignore-missing-schemas", "-kubernetes-version", "1.35.0", "-cache", CACHE], input=r.stdout, capture_output=True, text=True)
    docs = len([d for d in yaml.safe_load_all(r.stdout) if d])
    status = "ok  " if k.returncode == 0 else "FAIL"
    if k.returncode: bad += 1
    print(f"{status} {ov:22s} {docs:3d} resources | {(k.stdout.strip().splitlines() or ['']) [-1]}")
    if k.returncode: print("   ", (k.stdout + k.stderr).strip().splitlines()[0][:220])
sys.exit(1 if bad else 0)
