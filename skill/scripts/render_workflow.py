#!/usr/bin/env python3
"""Compile a workflow spec into a design doc, a Mermaid diagram, and an HTML artifact.

Usage:
    python3 render_workflow.py spec.json [--out DIR]

All three outputs come from the same spec so they cannot drift apart. The validator
enforces the structural rules that matter most in practice: every node has a defined
failure path, every retry loop is bounded, and every edge names what it carries.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

KINDS = ("code", "agent", "human")
KIND_LABEL = {"code": "Code", "agent": "Agent", "human": "Human"}

MERMAID_VERSION = "10.9.1"
MERMAID_URL = (
    f"https://cdnjs.cloudflare.com/ajax/libs/mermaid/{MERMAID_VERSION}/mermaid.min.js"
)


# --------------------------------------------------------------------------- load


def load_spec(path):
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"spec is not valid JSON: {exc}")
    for field in ("name", "goal", "trigger", "entry", "nodes", "edges"):
        if field not in spec:
            sys.exit(f"spec is missing required field: {field}")
    spec.setdefault("isolation", "none")
    spec.setdefault("open_questions", [])
    return spec


# ----------------------------------------------------------------------- validate


def validate(spec):
    """Return a list of human-readable problems. Structural errors, not style notes."""
    problems = []
    nodes = {n["id"]: n for n in spec["nodes"]}

    if len(nodes) != len(spec["nodes"]):
        problems.append("Duplicate node ids — every node needs a unique id.")

    if spec["entry"] not in nodes:
        problems.append(f"entry '{spec['entry']}' is not a node id.")

    for node in spec["nodes"]:
        if node.get("kind") not in KINDS:
            problems.append(
                f"Node '{node['id']}' has kind {node.get('kind')!r}; "
                f"must be one of {', '.join(KINDS)}."
            )
        if node.get("kind") != "agent" and node.get("model"):
            problems.append(
                f"Node '{node['id']}' is kind '{node.get('kind')}' but specifies a model. "
                "Only agent nodes run a model."
            )

    outgoing = {nid: [] for nid in nodes}
    for edge in spec["edges"]:
        for end in ("from", "to"):
            if edge.get(end) not in nodes:
                problems.append(f"Edge {end} '{edge.get(end)}' is not a node id.")
        if edge.get("when") not in ("always", "pass", "fail"):
            problems.append(
                f"Edge {edge.get('from')} -> {edge.get('to')} has when="
                f"{edge.get('when')!r}; must be always, pass, or fail."
            )
        if not edge.get("payload"):
            problems.append(
                f"Edge {edge.get('from')} -> {edge.get('to')} names no payload. "
                "An unnamed edge carries an assumption, not data."
            )
        if edge.get("from") in outgoing:
            outgoing[edge["from"]].append(edge)

    terminal = []
    for nid, edges in outgoing.items():
        whens = {e.get("when") for e in edges}
        if not edges:
            terminal.append(nid)
            continue
        if "always" in whens:
            continue
        if "pass" in whens and "fail" not in whens:
            problems.append(
                f"Node '{nid}' has a pass edge but no fail edge — undefined behaviour "
                "when this step fails."
            )
        if "fail" in whens and "pass" not in whens:
            problems.append(
                f"Node '{nid}' has a fail edge but no pass edge — the success path "
                "goes nowhere."
            )

    if len(terminal) == 0:
        problems.append("No terminal node — every path loops forever.")

    # Any node targeted by a fail edge is a retry target and needs a bound.
    for edge in spec["edges"]:
        if edge.get("when") == "fail" and edge.get("to") in nodes:
            target = nodes[edge["to"]]
            if not target.get("max_attempts") or target["max_attempts"] < 1:
                problems.append(
                    f"Node '{target['id']}' is the target of a retry edge but has no "
                    "max_attempts. Unbounded retries against a paid API are the one "
                    "design error here that costs real money unattended."
                )
            elif not target.get("on_exhausted"):
                problems.append(
                    f"Node '{target['id']}' has max_attempts but no on_exhausted — "
                    "undefined behaviour once retries run out."
                )

    return problems


# ------------------------------------------------------------------------ mermaid


def mm_escape(text):
    """Mermaid quoted labels tolerate most things; quotes and newlines are the risk."""
    return str(text).replace('"', "'").replace("\n", " ").strip()


def mm_id(node_id):
    return re.sub(r"[^A-Za-z0-9_]", "_", str(node_id))


def build_mermaid(spec):
    # Rendering stays defensive about invalid specs: an unknown kind or a dangling
    # edge is reported by the validator, but the diagram still draws so you can see
    # the problem in context instead of getting a traceback.
    shapes = {
        "code": '{id}["{label}"]',
        "agent": '{id}("{label}")',
        "human": '{id}{{{{"{label}"}}}}',
    }
    known = {n["id"] for n in spec["nodes"]}
    lines = ["flowchart TD"]

    for node in spec["nodes"]:
        kind = node.get("kind", "code")
        if kind not in shapes:
            kind = "code"
        # Labels are rendered as SVG text (htmlLabels is off, so that headless
        # pre-rendering measures them correctly). <br/> is the only markup that
        # survives that path — no <small>, no inline styling.
        label = mm_escape(node["label"])
        if kind == "agent" and node.get("model"):
            label += f"<br/>{mm_escape(node['model'])}"
        if node.get("max_attempts", 1) > 1:
            label += f"<br/>max {node['max_attempts']} attempts"
        lines.append(
            "    " + shapes[kind].format(id=mm_id(node["id"]), label=label)
        )

    lines.append("")

    for edge in spec["edges"]:
        if edge.get("from") not in known or edge.get("to") not in known:
            continue  # dangling; the validator reports it
        src, dst = mm_id(edge["from"]), mm_id(edge["to"])
        when = edge.get("when", "always")
        payload = mm_escape(edge.get("payload", ""))
        if when == "always":
            label = payload
        else:
            label = f"{when}: {payload}" if payload else when
        if edge.get("loop"):
            arrow = f'-. "{label}" .->' if label else "-.->"
        else:
            arrow = f'-- "{label}" -->' if label else "-->"
        lines.append(f"    {src} {arrow} {dst}")

    lines.append("")
    lines.append("    classDef code fill:#dbeafe,stroke:#1d4ed8,stroke-width:1px,color:#0b2a6b;")
    lines.append("    classDef agent fill:#ede9fe,stroke:#6d28d9,stroke-width:1px,color:#3b0764;")
    lines.append("    classDef human fill:#fef3c7,stroke:#b45309,stroke-width:1px,color:#4a2606;")

    for kind in KINDS:
        members = [mm_id(n["id"]) for n in spec["nodes"] if n.get("kind") == kind]
        if members:
            lines.append(f"    class {','.join(members)} {kind};")

    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------- markdown


def build_markdown(spec, mermaid, problems):
    nodes = spec["nodes"]
    counts = {k: sum(1 for n in nodes if n.get("kind") == k) for k in KINDS}

    out = []
    w = out.append

    w(f"# {spec['name']}\n")
    w(f"**Goal.** {spec['goal']}\n")
    w(f"**Trigger.** {spec['trigger']}\n")
    w(f"**Isolation.** `{spec['isolation']}`\n")
    w(
        f"**Shape.** {len(nodes)} nodes — "
        + ", ".join(f"{counts[k]} {KIND_LABEL[k].lower()}" for k in KINDS)
        + f"; {len(spec['edges'])} edges, "
        + f"{sum(1 for e in spec['edges'] if e.get('loop'))} of them loops.\n"
    )

    if problems:
        w("## Structural problems\n")
        w("These were found by the validator and should be resolved before building:\n")
        for p in problems:
            w(f"- {p}")
        w("")

    w("## Diagram\n")
    w("```mermaid")
    w(mermaid.rstrip())
    w("```\n")

    w("## Nodes\n")
    w("| Node | Who | What | Model | Retries |")
    w("|---|---|---|---|---|")
    for n in nodes:
        model = n.get("model") or ("—" if n.get("kind") != "agent" else "default")
        attempts = n.get("max_attempts", 1)
        retry = "—" if attempts <= 1 else f"{attempts}, then {n.get('on_exhausted', 'fail')}"
        detail = str(n.get("detail", "")).replace("|", "\\|")
        w(f"| `{n['id']}` | {KIND_LABEL.get(n.get('kind'), n.get('kind', '?'))} | {detail} | {model} | {retry} |")
    w("")

    w("## Flow\n")
    w("| From | Condition | Carries | To |")
    w("|---|---|---|---|")
    for e in spec["edges"]:
        cond = e.get("when", "always")
        if e.get("loop"):
            cond += " (loop)"
        w(f"| `{e['from']}` | {cond} | `{e.get('payload', '—')}` | `{e['to']}` |")
    w("")

    human_nodes = [n for n in nodes if n.get("kind") == "human"]
    w("## Where people are involved\n")
    if not human_nodes:
        w(
            "No human nodes. That is a deliberate choice worth stating out loud: this "
            "workflow runs unattended, so its checks are the only thing standing between "
            "a bad output and whatever happens next.\n"
        )
    else:
        for n in human_nodes:
            w(f"- **`{n['id']}` — {n['label']}.** {n.get('detail', '')}")
        w("")
        w(
            "Human touchpoints belong at intake and acceptance, plus any step whose next "
            "action is irreversible. Interior gates cap throughput at one person's "
            "attention regardless of available compute — if any of the above sits in the "
            "middle, check that the action after it genuinely cannot be undone.\n"
        )

    agent_nodes = [n for n in nodes if n.get("kind") == "agent"]
    if agent_nodes:
        w("## Model and tool allocation\n")
        w("| Node | Model | Tools |")
        w("|---|---|---|")
        for n in agent_nodes:
            tools = ", ".join(f"`{t}`" for t in n.get("tools", [])) or "all"
            w(f"| `{n['id']}` | {n.get('model', 'default')} | {tools} |")
        w("")
        w(
            "Scouting and planning decide what everything downstream does, so errors "
            "there propagate and get faithfully implemented — those are the nodes worth "
            "the strongest model. Mechanical transforms are where a cheaper tier pays "
            "off. Narrowing tools on read-only nodes is both a cost control and a safety "
            "property.\n"
        )

    if spec["open_questions"]:
        w("## Open questions\n")
        w("Unresolved. Each of these is a hole in the design, deliberately left visible:\n")
        for q in spec["open_questions"]:
            w(f"- {q}")
        w("")

    w("## Testing a single node\n")
    w(
        "Every edge names its payload, so any node can be run against a fixed input "
        "rather than by replaying the whole workflow. The generated scaffold exposes "
        "this as `--only <node>`, reading that node's inputs from the run directory. "
        "Retry granularity is node granularity: if debugging forces you to rerun "
        "everything, the boundaries are in the wrong place.\n"
    )

    return "\n".join(out)


# ------------------------------------------------------------------ pre-rendering
#
# A persisted artifact that fetches its renderer from a CDN shows an empty box the
# moment the viewer is offline or sandboxed. So the diagram is drawn once here, at
# generation time, and the resulting SVG is inlined — the artifact then has no runtime
# dependencies at all. When that isn't possible (no Playwright, no network), fall back
# to the CDN script tag, which is still correct in a normal browser.


def mermaid_source():
    """Return mermaid.min.js from a local cache, downloading once if needed."""
    cache = Path(
        os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
    ) / "agent-workflow-architect"
    js = cache / f"mermaid-{MERMAID_VERSION}.min.js"
    if js.exists() and js.stat().st_size > 100_000:
        return js.read_text(encoding="utf-8")
    import urllib.request

    cache.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MERMAID_URL, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    js.write_text(text, encoding="utf-8")
    return text


def prerender_svg(mermaid_text):
    """Draw the diagram headlessly and return inline SVG, or None if unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        js = mermaid_source()
    except Exception as exc:
        print(f"note: could not fetch or cache mermaid.min.js: {exc!r}", file=sys.stderr)
        return None

    page_html = (
        "<!DOCTYPE html><html><body><div id='t'></div><script>"
        + js
        + "</script><script>"
        + "mermaid.initialize({startOnLoad:false,securityLevel:'loose',"
        + "theme:'default',flowchart:{curve:'basis',useMaxWidth:true,htmlLabels:false,padding:10}});"
        + "window.__svg=null;"
        + "mermaid.render('g', "
        + json.dumps(mermaid_text)
        + ").then(r=>{window.__svg=r.svg;}).catch(e=>{window.__svg='ERR:'+e.message;});"
        + "</script></body></html>"
    )

    tmp = Path(tempfile.mkdtemp()) / "render.html"
    tmp.write_text(page_html, encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(tmp.as_uri())
            page.wait_for_function("window.__svg !== null", timeout=30_000)
            svg = page.evaluate("window.__svg")
            browser.close()
    except Exception as exc:
        print(f"note: headless render failed: {exc!r}", file=sys.stderr)
        return None
    finally:
        try:
            tmp.unlink()
            tmp.parent.rmdir()
        except OSError:
            pass

    if not svg or svg.startswith("ERR:"):
        if svg:
            print(f"mermaid render error: {svg[4:]}", file=sys.stderr)
        return None
    return svg


# --------------------------------------------------------------------------- html

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__ — workflow</title>
__MERMAID_SCRIPT__
<style>
  :root {
    --bg: #fbfbfa; --panel: #ffffff; --ink: #1c1b1a; --muted: #6b6866;
    --line: #e6e3e0; --accent: #7c5cff;
    --code: #1d4ed8; --code-bg: #dbeafe;
    --agent: #6d28d9; --agent-bg: #ede9fe;
    --human: #b45309; --human-bg: #fef3c7;
    --warn: #b91c1c; --warn-bg: #fee2e2;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17161a; --panel: #201f24; --ink: #eceaf0; --muted: #9c98a6;
      --line: #322f39; --accent: #a78bfa;
      --code: #93c5fd; --code-bg: #1e3a5f;
      --agent: #c4b5fd; --agent-bg: #3b2d63;
      --human: #fcd34d; --human-bg: #4a3410;
      --warn: #fca5a5; --warn-bg: #4a1d1d;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 16px/1.6 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 40px 24px 80px; }
  header { border-bottom: 1px solid var(--line); padding-bottom: 24px; margin-bottom: 32px; }
  h1 { font-size: 32px; margin: 0 0 6px; letter-spacing: -0.02em; }
  .goal { font-size: 18px; color: var(--ink); margin: 0 0 18px; max-width: 68ch; }
  .facts { display: flex; flex-wrap: wrap; gap: 8px; }
  .fact {
    font-size: 13px; background: var(--panel); border: 1px solid var(--line);
    border-radius: 999px; padding: 5px 12px; color: var(--muted);
  }
  .fact b { color: var(--ink); font-weight: 600; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.09em;
       color: var(--muted); margin: 40px 0 14px; font-weight: 600; }
  .panel { background: var(--panel); border: 1px solid var(--line);
           border-radius: 14px; padding: 22px; }
  .legend { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 18px; font-size: 13px; }
  .legend span { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); }
  .swatch { width: 13px; height: 13px; border-radius: 4px; display: inline-block; }
  /* The diagram keeps a light card in both colour schemes: the SVG is drawn once at
     generation time with a single theme, and a fixed light backing means it stays
     legible rather than turning into dark-on-dark. */
  .diagram { text-align: center; overflow-x: auto; background: #ffffff;
             border-radius: 10px; padding: 18px 12px; }
  .diagram svg { max-width: 100%; height: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14.5px; }
  th { text-align: left; font-size: 12px; text-transform: uppercase;
       letter-spacing: 0.06em; color: var(--muted); font-weight: 600;
       padding: 0 12px 10px; border-bottom: 1px solid var(--line); }
  td { padding: 13px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
  .pill { display: inline-block; font-size: 11.5px; font-weight: 600; padding: 3px 9px;
          border-radius: 6px; letter-spacing: 0.02em; white-space: nowrap; }
  .k-code  { background: var(--code-bg);  color: var(--code); }
  .k-agent { background: var(--agent-bg); color: var(--agent); }
  .k-human { background: var(--human-bg); color: var(--human); }
  .muted { color: var(--muted); }
  .loop { color: var(--accent); font-weight: 600; }
  .problems { background: var(--warn-bg); border-color: var(--warn); }
  .problems li { margin-bottom: 8px; }
  ul { margin: 0; padding-left: 20px; }
  li { margin-bottom: 7px; }
  footer { margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--line);
           font-size: 13px; color: var(--muted); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>__NAME__</h1>
    <p class="goal">__GOAL__</p>
    <div class="facts">
      <span class="fact"><b>Trigger</b> · __TRIGGER__</span>
      <span class="fact"><b>Isolation</b> · __ISOLATION__</span>
      <span class="fact"><b>Nodes</b> · __COUNTS__</span>
    </div>
  </header>

  __PROBLEMS__

  <h2>Diagram</h2>
  <div class="panel">
    <div class="legend">
      <span><i class="swatch" style="background:var(--code-bg);border:1px solid var(--code)"></i> Code — deterministic, free, same every time</span>
      <span><i class="swatch" style="background:var(--agent-bg);border:1px solid var(--agent)"></i> Agent — judgment, costs tokens, varies</span>
      <span><i class="swatch" style="background:var(--human-bg);border:1px solid var(--human)"></i> Human — scarce, highest judgment</span>
    </div>
    <div class="diagram">__DIAGRAM__</div>
  </div>

  <h2>Nodes</h2>
  <div class="panel"><table>
    <thead><tr><th>Node</th><th>Who</th><th>What it does</th><th>Model</th><th>Retries</th></tr></thead>
    <tbody>__NODE_ROWS__</tbody>
  </table></div>

  <h2>Flow</h2>
  <div class="panel"><table>
    <thead><tr><th>From</th><th>Condition</th><th>Carries</th><th>To</th></tr></thead>
    <tbody>__EDGE_ROWS__</tbody>
  </table></div>

  __QUESTIONS__

  <footer>
    Generated from <code>__SPECFILE__</code>. The diagram, this table, and the scaffold
    are all compiled from that one file — edit the spec and re-render rather than editing
    any output by hand, or they will drift.
  </footer>
</div>
__MERMAID_INIT__
</body>
</html>
"""


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_html(spec, mermaid, problems, spec_path, svg=None):
    counts = {k: sum(1 for n in spec["nodes"] if n.get("kind") == k) for k in KINDS}
    counts_text = ", ".join(f"{counts[k]} {KIND_LABEL[k].lower()}" for k in KINDS if counts[k])

    node_rows = []
    for n in spec["nodes"]:
        kind = n.get("kind", "code")
        model = n.get("model") or ("&mdash;" if kind != "agent" else "default")
        attempts = n.get("max_attempts", 1)
        retry = (
            '<span class="muted">&mdash;</span>'
            if attempts <= 1
            else f"{attempts}, then {esc(n.get('on_exhausted', 'fail'))}"
        )
        node_rows.append(
            f"<tr><td><code>{esc(n['id'])}</code><br><span class='muted'>{esc(n['label'])}</span></td>"
            f"<td><span class='pill k-{kind if kind in KINDS else 'code'}'>"
            f"{KIND_LABEL.get(kind, esc(kind))}</span></td>"
            f"<td>{esc(n.get('detail', ''))}</td>"
            f"<td><code>{esc(model) if model != '&mdash;' else '&mdash;'}</code></td>"
            f"<td>{retry}</td></tr>"
        )

    edge_rows = []
    for e in spec["edges"]:
        cond = esc(e.get("when", "always"))
        if e.get("loop"):
            cond = f"<span class='loop'>{cond} &#8635;</span>"
        edge_rows.append(
            f"<tr><td><code>{esc(e['from'])}</code></td><td>{cond}</td>"
            f"<td><code>{esc(e.get('payload', '—'))}</code></td>"
            f"<td><code>{esc(e['to'])}</code></td></tr>"
        )

    problems_html = ""
    if problems:
        items = "".join(f"<li>{esc(p)}</li>" for p in problems)
        problems_html = (
            '<h2>Structural problems</h2><div class="panel problems"><ul>'
            + items
            + "</ul></div>"
        )

    questions_html = ""
    if spec["open_questions"]:
        items = "".join(f"<li>{esc(q)}</li>" for q in spec["open_questions"])
        questions_html = (
            '<h2>Open questions</h2><div class="panel"><ul>' + items + "</ul></div>"
        )

    if svg:
        diagram, script, init = svg, "", ""
    else:
        diagram = f'<div class="mermaid">{mermaid}</div>'
        script = f'<script src="{MERMAID_URL}"></script>'
        init = (
            "<script>mermaid.initialize({startOnLoad:true,securityLevel:'loose',"
            "theme:'default',flowchart:{curve:'basis',useMaxWidth:true,htmlLabels:false,padding:10}});</script>"
        )

    replacements = {
        "__NAME__": esc(spec["name"]),
        "__GOAL__": esc(spec["goal"]),
        "__TRIGGER__": esc(spec["trigger"]),
        "__ISOLATION__": esc(spec["isolation"]),
        "__COUNTS__": esc(counts_text),
        "__PROBLEMS__": problems_html,
        "__DIAGRAM__": diagram,
        "__MERMAID_SCRIPT__": script,
        "__MERMAID_INIT__": init,
        "__NODE_ROWS__": "".join(node_rows),
        "__EDGE_ROWS__": "".join(edge_rows),
        "__QUESTIONS__": questions_html,
        "__SPECFILE__": esc(Path(spec_path).name),
    }
    html = HTML_TEMPLATE
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html


# --------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec")
    ap.add_argument("--out", default=".", help="output directory (default: cwd)")
    ap.add_argument(
        "--no-prerender",
        action="store_true",
        help="skip headless SVG pre-rendering; load Mermaid from the CDN instead",
    )
    args = ap.parse_args()

    spec = load_spec(args.spec)
    problems = validate(spec)
    mermaid = build_mermaid(spec)

    svg = None if args.no_prerender else prerender_svg(mermaid)
    if svg is None and not args.no_prerender:
        print(
            "note: could not pre-render the diagram, so the HTML will load Mermaid "
            "from a CDN and needs network access to draw.",
            file=sys.stderr,
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = spec["name"]

    (out / f"{name}.mermaid").write_text(mermaid, encoding="utf-8")
    (out / f"{name}-design.md").write_text(
        build_markdown(spec, mermaid, problems), encoding="utf-8"
    )
    (out / f"{name}.html").write_text(
        build_html(spec, mermaid, problems, args.spec, svg), encoding="utf-8"
    )

    print(f"wrote {out / (name + '-design.md')}")
    print(f"wrote {out / (name + '.mermaid')}")
    print(f"wrote {out / (name + '.html')}")

    if problems:
        print(f"\n{len(problems)} structural problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
