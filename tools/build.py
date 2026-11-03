#!/usr/bin/env python3
"""Build the DevOps & Cloud Architecture Path.

content/<folder>/NN-section.md  ->  <folder>/index.html (one interactive entry point per topic folder)

Rules enforced (the build fails if any is broken):
  * every @concept has @plain, @problem, @does and at least one @diagram
  * {{v.key}} must exist in tools/versions.yaml
  * fenced yaml / json / python / bash / hcl code must parse (opt out with `nocheck`)
  * internal links and #anchors must resolve; ids are unique
Usage: python3 tools/build.py [--check]
"""
import re, sys, json, html, ast, shlex, subprocess, pathlib, shutil
import yaml, markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.styles import get_all_styles

ROOT = pathlib.Path(__file__).resolve().parent.parent
CUR = yaml.safe_load((ROOT / "tools/curriculum.yaml").read_text())
VER = yaml.safe_load((ROOT / "tools/versions.yaml").read_text())
ERR, WARN = [], []
TERRAFORM = shutil.which("terraform")
KINDS = {"app", "env", "cp", "ext", "ok", "bad", "db", "info", "vm", "warn", "plain"}
MSG = {"req": "request", "tls": "encrypted / authenticated", "resp": "response", "bad": "error / denied",
       "xds": "configuration push", "tele": "telemetry", "warn": "decision / note"}
esc = html.escape


def err(where, msg): ERR.append(f"{where}: {msg}")


# ------------------------------------------------------------------ markdown
def subst(text, where):
    def r(m):
        k = m.group(1)
        if k not in VER:
            err(where, f"unknown version key {{{{v.{k}}}}}"); return "?"
        return str(VER[k])
    return re.sub(r"\{\{\s*v\.([a-z0-9_]+)\s*\}\}", r, text)


def check_code(lang, code, where, attrs):
    if "nocheck" in attrs or re.search(r"<[A-Za-z][A-Za-z0-9_-]*>", code): return
    try:
        if lang in ("yaml", "yml"):
            list(yaml.safe_load_all(code))
        elif lang == "json":
            json.loads(code)
        elif lang in ("ini", "toml-ini"):
            import configparser
            cp = configparser.RawConfigParser(strict=False, delimiters=("=",), allow_no_value=True); cp.optionxform = str
            cp.read_string(code)
        elif lang in ("python", "py"):
            ast.parse(code)
        elif lang in ("bash", "sh"):
            r = subprocess.run(["bash", "-n"], input=code, text=True, capture_output=True)
            if r.returncode: err(where, "bash syntax: " + r.stderr.strip().splitlines()[0][:140])
        elif lang in ("hcl", "terraform", "tf"):
            if TERRAFORM:
                r = subprocess.run([TERRAFORM, "fmt", "-no-color", "-"], input=code, text=True, capture_output=True)
                if r.returncode: err(where, "terraform syntax: " + (r.stderr.strip().splitlines() or ["?"])[0][:140])
    except Exception as e:
        err(where, f"{lang} does not parse: {str(e).splitlines()[0][:140]}")


STYLE = "github-dark" if "github-dark" in set(get_all_styles()) else "monokai"
FMT = HtmlFormatter(nowrap=True)


def code_html(lang, code, title="", attrs=()):
    try: lx = get_lexer_by_name(lang if lang not in ("tf", "terraform") else "hcl")
    except Exception: lx = TextLexer()
    body = highlight(code.rstrip("\n"), lx, FMT)
    cls = "code lab" if "lab" in attrs else "code"
    t = esc(title) if title else ""
    return (f'<div class="{cls}"><header><span class="l">{esc(lang or "text")}</span><span class="t">{t}</span>'
            f'<button type="button">Copy</button></header><pre><code>{body}</code></pre></div>')


def md(text, where, stats=None):
    text = subst(text, where)
    holes = []

    def hole(h): holes.append(h); return f"\n\nQQHOLE{len(holes)-1}QQ\n\n"

    def inc(m):
        parts = shlex.split(m.group(1)); rel = parts[0]; attrs = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        fl = [p for p in parts[1:] if "=" not in p]
        f = ROOT / rel
        if not f.exists(): err(where, f"@include missing file {rel}"); return ""
        lines = f.read_text().split("\n")
        if "lines" in attrs:
            a, b = attrs["lines"].split("-"); lines = lines[int(a) - 1:int(b)]
        code = "\n".join(lines)
        lang = attrs.get("lang") or {"py": "python", "yml": "yaml", "tf": "hcl", "sh": "bash"}.get(f.suffix[1:], f.suffix[1:] or "text")
        if f.name == "Dockerfile": lang = "docker"
        if f.name == "Jenkinsfile": lang = "groovy"
        if stats is not None: stats["code"] += 1; stats["codelines"] += len(lines)
        return hole(code_html(lang, code, attrs.get("title", rel), fl))
    text = re.sub(r"(?m)^@include\s+(.+)$", inc, text)

    def fence(m):
        info = m.group(1).strip(); code = m.group(2)
        parts = shlex.split(info) if info else []
        lang = parts[0] if parts else "text"
        title = ""; attrs = []
        for p in parts[1:]:
            if p.startswith("title="): title = p[6:]
            else: attrs.append(p)
        check_code(lang, code, where, attrs)
        if stats is not None: stats["code"] += 1; stats["codelines"] += code.count("\n") + 1
        return hole(code_html(lang, code, title, attrs))
    text = re.sub(r"(?ms)^```([^\n]*)\n(.*?)\n```[ \t]*$", fence, text)

    def callout(m):
        kind = m.group(1); inner = md(m.group(2), where)
        label = {"note": "Note", "tip": "Tip", "warn": "Careful", "danger": "Danger"}[kind]
        return hole(f'<div class="callout {kind}"><b class="t">{label}</b><div>{inner}</div></div>')
    text = re.sub(r"(?ms)^:::(note|tip|warn|danger)[ \t]*\n(.*?)\n:::[ \t]*$", callout, text)
    out = markdown.markdown(text, extensions=["tables", "sane_lists"])
    out = out.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    for i in range(len(holes) - 1, -1, -1):
        out = out.replace(f"<p>QQHOLE{i}QQ</p>", holes[i]).replace(f"QQHOLE{i}QQ", holes[i])
    return out


# ------------------------------------------------------------------ diagrams
class DG:
    def __init__(self, where): self.where = where; self.n = 0

    def node(self, s, num=None):
        if isinstance(s, dict): return self.group(s)
        p = [x.strip() for x in str(s).split("|")]
        title, sub, kind = p[0], (p[1] if len(p) > 1 else ""), (p[2] if len(p) > 2 else "plain")
        if kind not in KINDS: err(self.where, f"diagram node kind '{kind}'"); kind = "plain"
        self.n += 1
        badge = f'<span class="num">{num}</span>' if num else ""
        subh = f"<small>{esc(sub)}</small>" if sub else ""
        return f'<div class="nd k-{kind}" data-s="{self.n}">{badge}<b>{esc(title)}</b>{subh}</div>'

    def group(self, g):
        kind = g.get("kind", "plain"); col = " col" if g.get("col") else ""
        inner = "".join(self.node(x) for x in g.get("nodes", []))
        return f'<div class="grp k-{kind}"><div class="gl">{esc(g.get("group", ""))}</div><div class="gb{col}">{inner}</div></div>'

    def render(self, typ, spec, caption, mode):
        w = self.where
        if typ == "flow":
            col = spec.get("dir") == "col"; num = spec.get("numbered")
            items = [self.node(n, i + 1 if num else None) for i, n in enumerate(spec["nodes"])]
            a = '<div class="arw">↓</div>' if col else '<div class="arw">→</div>'
            body = f'<div class="{"flowcol" if col else "flowrow"}">{a.join(items)}</div>'
        elif typ == "rows":
            rows = []
            for r in spec["rows"]:
                items = [self.node(x) for x in r["items"]]
                if r.get("arrows"): rows.append(f'<div class="flowrow">{"<div class=arw>→</div>".join(items)}</div>')
                else: rows.append(f'<div class="flowrow" style="gap:12px">{"".join(items)}</div>')
            body = '<div class="down">↓</div>'.join(rows) if spec.get("down", True) else '<div style="height:10px"></div>'.join(rows)
        elif typ == "layers":
            ls = []
            for L in spec["layers"]:
                ls.append(f'<div class="layer"><div class="ll">{esc(L["label"])}</div><div class="lc">{"".join(self.node(x) for x in L["nodes"])}</div></div>')
            body = f'<div class="layers">{"".join(ls)}</div>'
        elif typ == "cmp":
            cs = []
            for c in spec["cards"]:
                k = c.get("kind", "plain"); self.n += 1
                lis = "".join(f"<li>{esc(i)}</li>" for i in c.get("items", []))
                cs.append(f'<div class="k-{k}" data-s="{self.n}"><h6>{esc(c["h"])}</h6><ul>{lis}</ul></div>')
            body = f'<div class="cmp">{"".join(cs)}</div>'
        elif typ == "seq":
            ac = spec["actors"]; n = len(ac); used = set()
            head = "".join(self.node(a) for a in ac).replace('data-s="', 'data-h="')
            rows = [f'<div class="row head">{head}</div>']
            for st in spec["steps"]:
                m = re.match(r"note\s+(\d+)(?:\.\.(\d+))?\s*:\s*(.+)$", st)
                if m:
                    a = int(m.group(1)); b = int(m.group(2) or a); self.n += 1
                    if not (0 <= a < n and 0 <= b < n): err(w, "seq note out of range")
                    rows.append(f'<div class="row"><div class="nt" data-s="{self.n}" style="grid-column:{a+1}/span {b-a+1};--sp:{b-a+1}">{esc(m.group(3))}</div></div>')
                    continue
                m = re.match(r"(\d+)\s*>\s*(\d+)\s*:\s*(.+?)(?:\s*\|\s*(\w+))?$", st)
                if not m: err(w, f"bad seq step '{st}'"); continue
                a, b, label, kind = int(m.group(1)), int(m.group(2)), m.group(3), (m.group(4) or "req")
                if kind not in MSG: err(w, f"seq kind '{kind}'"); kind = "req"
                if not (0 <= a < n and 0 <= b < n): err(w, f"seq index in '{st}'"); continue
                used.add(kind); self.n += 1
                lo, hi = min(a, b), max(a, b); sp = hi - lo + 1
                cls = "self" if a == b else ("r" if b > a else "l")
                rows.append(f'<div class="row"><div class="msg {cls}" data-s="{self.n}" style="grid-column:{lo+1}/span {sp};--sp:{sp};--mc:var(--m-{kind})">{esc(label)}</div></div>')
            leg = "".join(f'<span><i style="background:var(--m-{k})"></i>{MSG[k]}</span>' for k in MSG if k in used)
            body = f'<div class="seqwrap"><div class="seq" style="--n:{n};min-width:{max(n*150, 0)}px">{"".join(rows)}</div></div><div class="legend">{leg}</div>'
        else:
            err(w, f"unknown diagram type '{typ}'"); body = ""
        return body


def _quote_caption(m):
    v = m.group(2).rstrip()
    if v[:1] in ('"', "'", "|", ">"): return m.group(0)
    return f'{m.group(1)}"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def diagram(typ, text, where, secid, idx, stats):
    text = re.sub(r"(?m)^(caption:[ \t]*)(.+)$", _quote_caption, text)
    try: spec = yaml.safe_load(text) or {}
    except Exception as e:
        err(where, f"diagram yaml: {str(e).splitlines()[0][:120]}"); return ""
    cap = spec.get("caption", "")
    if not cap: err(where, "diagram needs a caption")
    mode = spec.get("mode") or ("reveal" if typ in ("seq", "rows") else "sweep")
    g = DG(where); body = g.render(typ, spec, cap, mode)
    stats["diagrams"] += 1
    anim = "" if spec.get("still") else ' data-anim="1"'
    btn = '' if spec.get("still") else '<button type="button" class="btn">▶ Replay</button>'
    cls = "dg reveal" if mode == "reveal" else "dg"
    if spec.get("still"): cls += " still"
    return f'<figure class="{cls}"{anim}>{body}<figcaption><span class="cap">{esc(cap)}</span>{btn}</figcaption></figure>'


# ------------------------------------------------------------------ section parsing
SUBS = {"plain", "problem", "does", "body", "diagram", "choose", "check", "h"}


PQ = {}
SIMS = []


def _plain_text(md_src):
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md_src)
    t = re.sub(r"[`*_]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_section(path, folder, fidx, sidx, stats):
    raw = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.S)
    where = f"{folder['slug']}/{path.name}"
    if not m: err(where, "missing front matter"); return None
    meta = yaml.safe_load(m.group(1)); body = m.group(2)
    secid = f"s{sidx:02d}-" + re.sub(r"^\d+-", "", path.stem)
    lines = body.split("\n"); i = 0; fence = False
    top = []; cur = None; sub = None; buf = []

    def flush_sub():
        nonlocal sub, buf
        if cur is not None and sub is not None:
            cur["parts"].append((sub[0], sub[1], "\n".join(buf)))
        elif cur is None and buf and top is not None:
            top.append(("md", "\n".join(buf)))
        sub = None; buf = []

    for ln in lines:
        s = ln.strip()
        if s.startswith("```"): fence = not fence
        mm = None if fence else re.match(r"^@(concept|lab|plain|problem|does|body|diagram|choose|check|h|end)\b[ \t]*(.*)$", ln)
        if not mm: buf.append(ln); continue
        d, arg = mm.group(1), mm.group(2).strip()
        if d in ("concept", "lab"):
            flush_sub(); cur = {"kind": d, "title": arg, "parts": []}; sub = ("body", "") if d == "lab" else None; buf = []
        elif d == "end":
            flush_sub()
            if cur: top.append((cur["kind"], cur)); cur = None
        elif d in SUBS and cur is not None:
            flush_sub(); sub = (d, arg); buf = []
        else:
            err(where, f"stray @{d}")
    flush_sub()
    if cur: err(where, f"unterminated @{cur['kind']} '{cur['title']}'"); top.append((cur["kind"], cur))

    out = []; toc = []; n = 0
    intro = md(top[0][1], where, stats) if top and top[0][0] == "md" else ""
    for kind, blk in top:
        if kind == "md":
            if blk is top[0][1]: continue
            out.append(md(blk, where, stats)); continue
        n += 1; cid = f"{secid}-c{n}"; stats["concepts"] += (kind == "concept")
        title = blk["title"]; toc.append((cid, title, []))
        parts = blk["parts"]; have = {p[0] for p in parts}
        if kind == "concept":
            for need in ("plain", "problem", "does", "diagram"):
                if need not in have: err(where, f"concept '{title}' is missing @{need}")
        h = [f'<section class="concept{" lab" if kind=="lab" else ""}" id="{cid}"><header>'
             f'<span class="cno">{"LAB" if kind=="lab" else f"{sidx}.{n}"}</span><h3>{esc(title)}</h3></header>']
        tiles = []
        for lab, key, cls in (("In plain words", "plain", "plain"), ("The problem it solves", "problem", "problem"), ("What it does", "does", "does")):
            for p in parts:
                if p[0] == key: tiles.append(f'<div class="tile {cls}"><h4>{lab}</h4>{md(p[2], where, stats)}</div>')
        if tiles: h.append(f'<div class="trio">{"".join(tiles)}</div>')
        di = 0; subs = []
        cd = dict(id=cid, t=title, plain=_plain_text(next((p[2] for p in parts if p[0] == "plain"), "")), checks=[], choose=[])
        for p in parts:
            if p[0] == "diagram": di += 1; h.append(diagram(p[1], p[2], f"{where} [{title}]", secid, di, stats))
            elif p[0] == "body": h.append(md(p[2], f"{where} [{title}]", stats))
            elif p[0] == "h":
                hid = f"{cid}-h{len(subs)+1}"; subs.append((hid, p[1]))
                h.append(f'<h4 id="{hid}">{esc(p[1])}</h4>' + md(p[2], f"{where} [{title}]", stats))
            elif p[0] == "choose":
                rows = [r for r in p[2].strip().split("\n") if r.strip()]
                head = esc(p[1] or "When to choose what"); rr = []
                for r in rows:
                    c = [x.strip() for x in r.split("|")]
                    if len(c) != 3: err(where, f"choose row needs 3 columns: '{r[:50]}'"); continue
                    cd["choose"].append(c)
                    rr.append(f'<div class="opt"><div><em>Option</em><b>{esc(c[0])}</b></div><div class="w"><em>Choose when</em>{esc(c[1])}</div><div class="a"><em>Avoid when</em>{esc(c[2])}</div></div>')
                h.append(f'<div class="choose"><h5>{head}</h5>{"".join(rr)}</div>')
            elif p[0] == "check":
                qa = []
                for r in p[2].strip().split("\n"):
                    if "||" in r:
                        q, a = r.split("||", 1); cd["checks"].append([q.strip(), a.strip()]); qa.append(f"<details><summary>{esc(q.strip())}</summary><p>{esc(a.strip())}</p></details>")
                    elif r.strip(): err(where, f"check line needs '||': '{r[:40]}'")
                h.append(f'<div class="checks"><b>Check yourself</b>{"".join(qa)}</div>')
        h.append("</section>"); out.append("".join(h)); toc[-1] = (toc[-1][0], toc[-1][1], subs); PQ.setdefault(secid, []).append(cd)
    return dict(id=secid, title=meta.get("title", path.stem), meta=meta, intro=intro, html="\n".join(out), toc=toc, path=where)


def text_of(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))


# ------------------------------------------------------------------ page chrome
def top_bar(rel, crumb, folders, cur_slug=None, section_nav=True):
    menu = "".join(
        f'<a href="{rel}{f["slug"]}/index.html" class="{"cur" if f["slug"]==cur_slug else ""}"><b style="background:{f["accent"]}">{i:02d}</b>{esc(f["title"])}</a>'
        for i, f in enumerate(folders))
    nav = ('<button class="btn" id="prev" type="button">← <span class="lbl">Prev</span></button>'
           '<button class="btn" id="next" type="button"><span class="lbl">Next</span> →</button>'
           '<button class="btn" id="subsbtn" type="button" title="Subtitles: show the plain-words summary of the concept in view (C)">CC</button>'
           '<button class="btn" id="textbtn" type="button" title="Text mode: larger type, no animation, narrow column (R)">Aa</button>'
           '<button class="btn pri" id="start" type="button" title="Walk through every concept (T)">▶ <span class="lbl">Start</span></button>'
           '<button class="btn" id="stop" type="button" title="Stop the walkthrough (Esc)">■ <span class="lbl">Stop</span></button>') if section_nav else ""
    side = '<button class="btn sidebtn" id="sidebtn" type="button" aria-label="Contents">☰</button>' if section_nav else ""
    return (f'<header class="top">{side}<a class="brand" href="{rel}index.html"><img src="{rel}assets/logo.svg" alt="DevOps Arch Logo" class="brand-logo" width="32" height="32"><span>DevOps &amp; Cloud Path</span></a>'
            f'<span class="crumb" data-base="{esc(crumb)}">{esc(crumb)}</span><span class="spacer"></span>'
            f'<div class="ctl">{nav}<a class="btn" href="{rel}plan.html" title="Choose modules or single concepts">Pick</a><a class="btn" href="{rel}review.html" title="Flashcards and quizzes">Review</a><a class="btn" href="{rel}simulators.html" title="Interactive simulators">Sims</a><a class="btn" href="{rel}Istio-Masterclass.html" title="Istio Service Mesh Masterclass">Istio</a><div class="menu"><button class="btn" type="button">Topics ▾</button><div>{menu}</div></div>'
            f'<button class="btn" id="theme" type="button" aria-label="Toggle theme">◐</button></div></header>')


def page(title, rel, body, folder_slug="", accent="#0ea5b7"):
    extra = (f'<script src="{rel}assets/practice-{folder_slug}.js"></script><script src="{rel}assets/pq-core.js"></script><script src="{rel}assets/practice.js"></script>' if folder_slug else "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><link rel="icon" type="image/svg+xml" href="{rel}assets/logo.svg"><link rel="stylesheet" href="{rel}assets/site.css"><link rel="stylesheet" href="{rel}assets/code.css">'
            f'<style>:root{{--accent:{accent}}}</style></head><body data-folder="{folder_slug}">{body}<div id="subs" aria-live="polite"></div><script src="{rel}assets/site.js"></script>{extra}</body></html>')


def load_sims():
    out = []
    for f in sorted((ROOT / "sims").glob("[0-9]*.html")):
        t = f.read_text(errors="ignore")
        m = {k: (re.search(r'<meta name="sim:%s" content="([^"]*)"' % k, t) or [None, ""])[1] for k in ("title", "topic", "summary", "concepts")}
        out.append(dict(file=f.name, **m))
    return out


def _check_objectives(meta, where, errors):
    for o in meta.get("objectives", []) or []:
        if not isinstance(o, str):
            errors.append(f"{where}: objective is not plain text (unquoted colon?): {o!r}")


def build():
    folders = CUR["folders"]; report = {}; allids = {}
    global SIMS; SIMS = load_sims()
    css = HtmlFormatter(style=STYLE).get_style_defs(".code pre")
    css = re.sub(r"\.code pre\s*\{[^}]*\}", "", css)  # keep token colours only
    (ROOT / "assets/code.css").write_text(css)
    for fi, f in enumerate(folders):
        d = ROOT / "content" / f["slug"]; stats = dict(code=0, codelines=0, diagrams=0, concepts=0)
        PQ.clear()
        files = sorted(d.glob("[0-9]*.md")) if d.exists() else []
        secs = [parse_section(p, f, fi, si + 1, stats) for si, p in enumerate(files)]
        secs = [s for s in secs if s]
        pqd = dict(slug=f["slug"], title=f["title"], accent=f["accent"], sections=[dict(id=x["id"], title=x["title"], c=[dict(id=c["id"], t=c["t"], p=c["plain"], k=c["checks"], o=c["choose"]) for c in PQ.get(x["id"], [])]) for x in secs])
        (ROOT / "assets" / f"practice-{f['slug']}.js").write_text('(window.__PQ=window.__PQ||{})["%s"]=%s;' % (f["slug"], json.dumps(pqd, ensure_ascii=False, separators=(",", ":"))))
        ids = set(); [ids.update([s["id"]] + [c[0] for c in s["toc"]] + [h[0] for c in s["toc"] for h in c[2]]) for s in secs]
        ids.add("overview"); allids[f["slug"]] = ids
        words = sum(len(text_of(s["html"]).split()) for s in secs)
        report[f["slug"]] = dict(sections=len(secs), words=words, **stats, planned_pages=f["pages"], planned_outline=len(f["outline"]))
        f["_secs"] = secs; f["_stats"] = stats; f["_words"] = words
    # link check across built pages
    for f in folders:
        for s in f["_secs"]:
            blob = s["intro"] + s["html"]
            for m in re.finditer(r'href="([^"#][^"]*?)(#[^"]*)?"', blob):
                u, a = m.group(1), (m.group(2) or "")[1:]
                if u.startswith(("http", "mailto")): continue
                tgt = (ROOT / f["slug"] / u).resolve()
                if not tgt.exists() and not (tgt / "index.html").exists(): err(s["path"], f"broken link {u}")
                elif a:
                    slug = tgt.parent.name if tgt.name == "index.html" else tgt.name
                    if slug in allids and a not in allids[slug]: err(s["path"], f"broken anchor {u}#{a}")
            for m in re.finditer(r'href="#([^"]+)"', blob):
                if m.group(1) not in allids[f["slug"]]: err(s["path"], f"broken anchor #{m.group(1)}")
    if "--check" in sys.argv and not ERR: pass
    for fi, f in enumerate(folders):
        secs = f["_secs"]; prev = folders[fi - 1] if fi else None; nxt = folders[fi + 1] if fi + 1 < len(folders) else None
        mins = sum(max(5, round(len(text_of(s["html"]).split()) / 170 + 0.9 * s["html"].count("<figure") + s["html"].count('class="code') * 0.6)) for s in secs)
        f["_mins"] = mins
        toc = [f'<li data-sec="overview"><a href="#overview"><span class="n">★</span><span>Overview</span></a></li>']
        for si, s in enumerate(secs):
            subs = "".join(f'<li><a href="#{cid}">{esc(t)}</a>' + ("<ul>" + "".join(f'<li><a href="#{hid}">{esc(ht)}</a></li>' for hid, ht in hs) + "</ul>" if hs else "") + "</li>" for cid, t, hs in s["toc"])
            toc.append(f'<li data-sec="{s["id"]}"><a href="#{s["id"]}"><span class="n">{si+1}</span><span>{esc(s["title"])}</span></a><ul>{subs}</ul></li>')
        cards = "".join(f'<a class="sc" href="#{s["id"]}"><span class="n">SECTION {si+1}</span><b>{esc(s["title"])}</b><span>{len(s["toc"])} concepts · {s["meta"].get("minutes") or max(5, round(len(text_of(s["html"]).split())/170))} min</span></a>' for si, s in enumerate(secs))
        outline = "".join(f"<li>{esc(o)}</li>" for o in f["outline"])
        mysims = [x for x in SIMS if x["topic"] == f["slug"]]
        simhtml = ('<h3>Interactive simulators</h3><div class="cardgrid">' + "".join(f'<a class="sc" href="../sims/{x["file"]}"><span class="n">SIMULATOR</span><b>{esc(x["title"])}</b><span>{esc(x["summary"])}</span></a>' for x in mysims) + "</div>") if mysims else ""
        obj = "".join(f"<li>{esc(o)}</li>" for s in secs for o in (s["meta"].get("objectives") or [])[:1])
        ov = (f'<section class="sec" id="overview"><div class="hero"><div class="eyebrow">Topic {fi:02d} · {esc(f["level"])}</div><h1>{esc(f["title"])}</h1><p>{esc(f["tagline"])}</p>'
              f'<div class="chips"><span class="chip"><b>{len(secs)}</b> sections</span><span class="chip"><b>{f["_stats"]["concepts"]}</b> concepts</span>'
              f'<span class="chip"><b>{f["_stats"]["diagrams"]}</b> diagrams</span><span class="chip"><b>~{mins}</b> min</span></div></div>'
              f'<div class="cardgrid">{cards}</div><h3>What you will learn</h3><div class="objectives"><ul>{outline}</ul></div>{simhtml}'
              f'<p style="color:var(--mute);margin-top:18px">Use <b>Next</b> and <b>Prev</b> to move between sections, <b>Start</b> to be walked through every concept automatically, and <b>Topics</b> to jump to another folder.</p></section>')
        order = ["overview"] + [s["id"] for s in secs] + ["review"]
        blocks = [ov]
        for si, s in enumerate(secs):
            k = order.index(s["id"])
            pv = f'<a class="btn" href="#{order[k-1]}">← Previous</a>'
            nx = (f'<a class="btn pri" href="#{order[k+1]}">Next →</a>' if k + 1 < len(order)
                  else (f'<a class="btn pri" href="../{nxt["slug"]}/index.html">Next topic: {esc(nxt["short"])} →</a>' if nxt else '<a class="btn pri" href="../index.html">Back to the path ✓</a>'))
            m = s["meta"]; mm = m.get("minutes") or max(5, round(len(text_of(s["html"]).split()) / 170))
            blocks.append(f'<section class="sec" id="{s["id"]}"><div class="sec-head"><div class="eyebrow">Section {si+1} of {len(secs)}</div><h2>{esc(s["title"])}</h2>'
                          f'<div class="meta">{len(s["toc"])} concepts · about {mm} minutes</div></div>{s["intro"]}'
                          + (f'<div class="callout tip"><b class="t">Goals</b><div><ul>{"".join("<li>"+esc(o)+"</li>" for o in m.get("objectives",[]))}</ul></div></div>' if m.get("objectives") else "")
                          + s["html"] +
                          f'<div class="practice" data-sec="{s["id"]}"></div><div class="done-row"><button class="btn markdone" data-sec="{s["id"]}" type="button">✓ Mark done and continue</button></div><div class="pager">{pv}{nx}</div></section>')
        nx_rev = (f'<a class="btn pri" href="../{nxt["slug"]}/index.html">Next topic: {esc(nxt["short"])} →</a>' if nxt else '<a class="btn pri" href="../index.html">Back to the path ✓</a>')
        blocks.append(f'<section class="sec" id="review"><div class="sec-head"><div class="eyebrow">Topic review</div><h2>Review this topic</h2><div class="meta">Mixed questions from every section</div></div><p>Answer a mixed set drawn from the whole topic. Wrong answers can be added to your flashcards.</p><div class="practice" data-sec="*"></div><div class="pager"><a class="btn" href="#{order[-2]}">← Previous</a>{nx_rev}</div></section>')
        toc.append('<li data-sec="review"><a href="#review"><span class="n">✓</span><span>Topic review</span></a></li>')
        foot = (f'<div class="foot">' + (f'<a id="prevfolder" href="../{prev["slug"]}/index.html">← Previous topic: {esc(prev["short"])}</a>' if prev else '<a href="../index.html">← The full path</a>')
                + (f'<a id="nextfolder" href="../{nxt["slug"]}/index.html">Next topic: {esc(nxt["short"])} →</a>' if nxt else '<a id="nextfolder" href="../index.html">Finish: back to the path</a>')
                + '<a href="../index.html">All topics</a></div>')
        side = (f'<aside class="side" aria-label="Table of contents"><h2>Contents</h2><input id="filter" placeholder="Filter sections..." aria-label="Filter"><ul class="toc">{"".join(toc)}</ul></aside>')
        body = top_bar("../", f["title"], folders, f["slug"]) + f'<div class="shell">{side}<main><div class="inner">{"".join(blocks)}{foot}</div></main></div>'
        outp = ROOT / f["slug"]; outp.mkdir(exist_ok=True)
        (outp / "index.html").write_text(page(f"{f['title']} · DevOps & Cloud Path", "../", body, f["slug"], f["accent"]))
    # plan (picker) page: every folder, section and concept with checkboxes
    try: ppages = json.loads((ROOT / "tools/pages.json").read_text())
    except Exception: ppages = {}
    data = []
    for f in folders:
        n = sum(len(x["toc"]) for x in f["_secs"]); pg = ppages.get(f["slug"], 0)
        data.append(dict(slug=f["slug"], title=f["title"], accent=f["accent"], ppc=round(pg / n, 2) if n and pg else 1.6,
                         secs=[dict(id=x["id"], title=x["title"], c=[[cid, t] for cid, t, _ in x["toc"]]) for x in f["_secs"]]))
    pbody = (top_bar("", "Pick modules and concepts", folders, None, False)
             + '<main style="padding:26px 22px 90px"><div class="inner" style="max-width:1100px">'
             '<div class="hero"><div class="eyebrow">Build your own path</div><h1>Pick modules or single concepts</h1>'
             '<p>Tick a whole topic, a section, or only the concepts you need. Your choice is saved in this browser and each topic page then shows just that selection.</p></div>'
             '<div id="planbar"><input id="q" placeholder="Search all concepts, for example IRSA, PromQL, VPC peering..." aria-label="Search">'
             '<div class="chips" id="presets"></div>'
             '<div class="chips" id="stats"></div>'
             '<div class="row"><button class="btn" id="selvis" type="button">Select shown</button><button class="btn" id="clr" type="button">Clear all</button>'
             '<button class="btn" id="copy" type="button">Copy list</button><button class="btn pri" id="go" type="button">Open my selection →</button></div></div>'
             '<div id="tree"></div></div></main>'
             f'<script>window.__PLAN={json.dumps(data, separators=(",", ":"))};</script>')
    (ROOT / "plan.html").write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pick modules and concepts</title>'
        f'<link rel="stylesheet" href="assets/site.css"><style>:root{{--accent:#0ea5b7}}</style></head><body data-folder="">{pbody}<script src="assets/plan.js"></script></body></html>')
    # review page: flashcards (spaced repetition) and mixed quiz
    rscripts = "".join(f'<script src="assets/practice-{f["slug"]}.js"></script>' for f in folders)
    rbody = (top_bar("", "Flashcards and quizzes", folders, None, False)
             + '<main style="padding:26px 22px 90px"><div class="inner" style="max-width:860px">'
             '<div class="hero"><div class="eyebrow">Remember what you learn</div><h1>Flashcards and quizzes</h1>'
             '<p>Cards come from every concept. Rate each one and it returns after 1, 3, 7, 16 or 35 days, so you review less as you learn more. Progress stays in this browser.</p></div>'
             '<div id="rv"><div class="chips" id="rstats"></div>'
             '<div class="row" id="rctl"><label>Topic <select id="rf"></select></label><label><input type="checkbox" id="rp"> Only my picked concepts</label>'
             '<label>New cards per session <select id="rn"><option>10</option><option selected>20</option><option>40</option></select></label></div>'
             '<div class="row"><button class="btn pri" id="tcards" type="button">Flashcards</button><button class="btn" id="tquiz" type="button">Quiz me</button></div>'
             '<div id="rbody"></div></div></div></main>')
    (ROOT / "review.html").write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Flashcards and quizzes</title>'
        f'<link rel="stylesheet" href="assets/site.css"><style>:root{{--accent:#0ea5b7}}</style></head><body data-folder="">{rbody}{rscripts}<script src="assets/pq-core.js"></script><script src="assets/review.js"></script></body></html>')
    # simulators hub
    cards_s = "".join(f'<a class="sc" href="sims/{x["file"]}"><span class="n">{esc((next((f["title"] for f in folders if f["slug"] == x["topic"]), "")).upper())}</span><b>{esc(x["title"])}</b><span>{esc(x["summary"])}</span></a>' for x in SIMS)
    sbody = (top_bar("", "Interactive simulators", folders, None, False)
             + '<main style="padding:26px 22px 90px"><div class="inner" style="max-width:1100px"><div class="hero"><div class="eyebrow">Learn by stepping through it</div><h1>Interactive simulators</h1>'
             '<p>Each simulator lets you predict what happens, step through it, and change the inputs. They run offline and simplify real systems, which each page lists.</p></div>'
             f'<div class="cardgrid">{cards_s}</div></div></main>')
    (ROOT / "simulators.html").write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Interactive simulators</title>'
        f'<link rel="stylesheet" href="assets/site.css"><style>:root{{--accent:#0ea5b7}}</style></head><body data-folder="">{sbody}<script src="assets/plan.js"></script></body></html>')
    # landing page
    tot_m = sum(f["_mins"] for f in folders)
    cards = '<a class="sc" href="Istio-Masterclass.html" style="border-top:4px solid #466BB0"><span class="n">SPECIAL FEATURE · MASTERCLASS</span><b>Istio Service Mesh Masterclass</b><span>Complete interactive visual guide to Istio service mesh, Envoy proxy, traffic shifting, mTLS, and observability.</span><span><b style="font-size:13px">Interactive visual architecture &amp; deep dives</b></span></a>' + "".join(f'<a class="sc" href="{f["slug"]}/index.html" style="border-top:4px solid {f["accent"]}"><span class="n">TOPIC {i:02d} · {esc(f["level"]).upper()}</span><b>{esc(f["title"])}</b><span>{esc(f["tagline"])}</span><span><b style="font-size:13px">{len(f["_secs"])} sections · {f["_stats"]["concepts"]} concepts · ~{f["_mins"]//60}h {f["_mins"]%60:02d}m</b></span></a>' for i, f in enumerate(folders))
    hero = (f'<div class="hero"><div class="eyebrow">Self-paced curriculum</div><h1>DevOps &amp; Cloud Architecture Path</h1><p>From your first Linux command to architect-level decisions: containers, Kubernetes, Terraform, CI/CD, observability, Python, AWS, Azure and Google Cloud, with one complete e-commerce application delivered end to end.</p>'
            f'<div class="chips"><span class="chip"><b>{len(folders)}</b> topics</span><span class="chip"><b>{sum(len(f["_secs"]) for f in folders)}</b> sections</span><span class="chip"><b>{sum(f["_stats"]["concepts"] for f in folders)}</b> concepts</span><span class="chip"><b>{sum(f["_stats"]["diagrams"] for f in folders)}</b> diagrams</span></div>'
            f'<div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap"><a class="btn pri" href="00-roadmap-prerequisites/index.html" style="padding:12px 18px">Start with the roadmap →</a><a class="btn" href="14-sample-app-shop/index.html" style="padding:12px 18px">Jump to the sample app</a><a class="btn" href="plan.html" style="padding:12px 18px">Pick my own modules and concepts</a><a class="btn" href="review.html" style="padding:12px 18px">Flashcards and quizzes</a><a class="btn" href="simulators.html" style="padding:12px 18px">Interactive simulators</a><a class="btn" href="Istio-Masterclass.html" style="padding:12px 18px;background:#0ea5b7;color:#fff">Istio Masterclass</a></div></div>')
    body = top_bar("", "The full path", folders, None, False) + f'<main style="padding:30px 22px 80px"><div class="inner" style="max-width:1180px">{hero}<div class="cardgrid">{cards}</div><div class="foot">Progress is stored in your browser only. Press <b>T</b> inside a topic to start the guided walkthrough.</div></div></main>'
    (ROOT / "index.html").write_text(page("DevOps & Cloud Architecture Path", "", body))
    (ROOT / "tools/report.json").write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    rep = build()
    tw = sum(r["words"] for r in rep.values())
    print(f"built {len(rep)} folders | sections {sum(r['sections'] for r in rep.values())} | concepts {sum(r['concepts'] for r in rep.values())} | diagrams {sum(r['diagrams'] for r in rep.values())} | code blocks {sum(r['code'] for r in rep.values())} | words {tw}")
    if ERR:
        print(f"\n{len(ERR)} ERROR(S):")
        for e in ERR[:60]: print("  -", e)
        sys.exit(1)
    print("no errors")
