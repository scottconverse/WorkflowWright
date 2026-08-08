#!/usr/bin/env python3
"""Build docs/index.html, the GitHub Pages landing page.

Usage:
    python3 docs/build_site.py            # writes docs/index.html
    python3 docs/build_site.py --check    # verify it is up to date, write nothing

The diagram on the page is not hand-copied: it is extracted from the rendered
example artifact in examples/, which render_workflow.py generates from
skill/assets/example-spec.json. So the picture on the landing page is the real
output of the tool the page describes, and regenerating the example updates the
site. That is the same rule the product itself enforces — one source, generated
outputs, no hand-editing — and a landing page that pasted a stale copy of its
own diagram would be arguing against its own thesis.

The page is deliberately self-contained: no CDN, no external stylesheet, no web
font, no analytics. It ships the same way the artifacts do, and for the same
reason — it has to render offline, in a sandboxed viewer, and in five years.

Placeholders are __UPPERCASE__ rather than str.format fields because the CSS is
full of braces; render_workflow.py does the same for the same reason.
"""

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EXAMPLE_ARTIFACT = REPO / "examples" / "ticket-to-pr.html"
OUT = HERE / "index.html"

REPO_URL = "https://github.com/scottconverse/WorkflowWright"


def extract_diagram(path):
    """Pull the pre-rendered inline SVG out of a rendered artifact.

    Returns None when the artifact was rendered without Playwright, in which
    case it carries a CDN script tag instead of an SVG — and the caller should
    fail loudly rather than shipping a page with a hole where the proof goes.
    """
    html = path.read_text(encoding="utf-8")
    match = re.search(r"<svg\b.*?</svg>", html, re.DOTALL)
    if not match:
        return None
    svg = match.group(0)
    # The artifact sets a fixed max-width for print; the page is responsive.
    svg = re.sub(r'style="max-width:[^"]*"', 'style="max-width:100%"', svg, count=1)
    return svg


# --------------------------------------------------------------------- styles

STYLES = """
  /* Tokens are inherited from the artifact template in
     skill/scripts/render_workflow.py so the site and the tool's own output
     look like the same product. The three kind colours are load-bearing:
     blue is code, violet is an agent, amber is a human, in every diagram
     this tool draws and everywhere on this page. */
  :root {
    --bg: #fbfbfa; --panel: #ffffff; --ink: #1c1b1a; --muted: #6b6866;
    --line: #e6e3e0; --accent: #7c5cff;
    --code: #1d4ed8; --code-bg: #dbeafe;
    --agent: #6d28d9; --agent-bg: #ede9fe;
    --human: #b45309; --human-bg: #fef3c7;
    --warn: #b91c1c; --warn-bg: #fee2e2;
    --term-bg: #1c1b1f; --term-ink: #e7e4ee;
    --radius: 14px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17161a; --panel: #201f24; --ink: #eceaf0; --muted: #9c98a6;
      --line: #322f39; --accent: #a78bfa;
      --code: #93c5fd; --code-bg: #1e3a5f;
      --agent: #c4b5fd; --agent-bg: #3b2d63;
      --human: #fcd34d; --human-bg: #4a3410;
      --warn: #fca5a5; --warn-bg: #4a1d1d;
      --term-bg: #0f0e12; --term-ink: #e7e4ee;
    }
  }

  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    * { animation: none !important; transition: none !important; }
  }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 16px/1.65 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 0 24px; }
  a { color: inherit; }
  :focus-visible {
    outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px;
  }
  code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

  /* --- nav --------------------------------------------------------------- */
  .nav {
    position: sticky; top: 0; z-index: 20;
    background: color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--line);
  }
  .nav-in { display: flex; align-items: center; gap: 16px; height: 60px; }
  .brand {
    font-weight: 680; letter-spacing: -0.02em; font-size: 16.5px;
    text-decoration: none; display: inline-flex; align-items: center; gap: 9px;
  }
  .mark { width: 15px; height: 15px; flex: none; }
  .nav-links { display: flex; gap: 22px; margin-left: auto; align-items: center; }
  .nav-links a {
    font-size: 14.5px; color: var(--muted); text-decoration: none;
  }
  .nav-links a:hover { color: var(--ink); }
  .ghost {
    border: 1px solid var(--line); border-radius: 9px; padding: 7px 14px;
    font-size: 14.5px; text-decoration: none; background: var(--panel);
    display: inline-block; font-weight: 550;
  }
  .ghost:hover { border-color: var(--muted); }
  .menu { margin-left: auto; display: none; }
  .menu summary {
    list-style: none; cursor: pointer; border: 1px solid var(--line);
    border-radius: 9px; padding: 7px 13px; font-size: 14.5px; background: var(--panel);
  }
  .menu summary::-webkit-details-marker { display: none; }
  .menu[open] .menu-panel { display: flex; }
  .menu-panel {
    display: none; position: absolute; right: 24px; left: 24px; margin-top: 10px;
    flex-direction: column; gap: 2px; background: var(--panel);
    border: 1px solid var(--line); border-radius: 12px; padding: 8px;
    box-shadow: 0 12px 28px rgba(0,0,0,0.10);
  }
  .menu-panel a {
    padding: 10px 12px; text-decoration: none; border-radius: 8px; font-size: 15px;
  }
  .menu-panel a:hover { background: var(--bg); }
  @media (max-width: 860px) {
    .nav-links { display: none; }
    .menu { display: block; }
  }

  /* --- type -------------------------------------------------------------- */
  h1 {
    font-size: clamp(2.1rem, 5.2vw, 3.15rem); line-height: 1.08;
    letter-spacing: -0.033em; margin: 0 0 18px; font-weight: 700;
  }
  h2 {
    font-size: clamp(1.45rem, 3vw, 1.95rem); line-height: 1.2;
    letter-spacing: -0.022em; margin: 0 0 14px; font-weight: 670;
  }
  h3 { font-size: 1.02rem; margin: 0 0 7px; font-weight: 640; letter-spacing: -0.008em; }
  p { margin: 0 0 16px; }
  .lede { font-size: clamp(1.05rem, 2vw, 1.2rem); color: var(--muted); max-width: 60ch; }
  .eyebrow {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.11em;
    color: var(--muted); font-weight: 640; margin: 0 0 12px;
  }
  .prose { max-width: 64ch; }
  .prose p { color: var(--muted); }
  .prose strong { color: var(--ink); font-weight: 620; }
  /* Clears the sticky nav when an anchor is jumped to, so the heading does not
     land underneath it. */
  section { padding: 74px 0; border-top: 1px solid var(--line); scroll-margin-top: 72px; }
  section:first-of-type { border-top: none; }

  /* --- hero -------------------------------------------------------------- */
  .hero { padding: 64px 0 58px; border-top: none; }
  .hero-grid {
    display: grid; grid-template-columns: 1.08fr 0.92fr; gap: 52px; align-items: center;
  }
  @media (max-width: 900px) { .hero-grid { grid-template-columns: 1fr; gap: 38px; } }
  .cta-row { display: flex; flex-wrap: wrap; gap: 12px; margin: 26px 0 0; }
  .btn {
    background: var(--ink); color: var(--bg); text-decoration: none;
    padding: 11px 21px; border-radius: 10px; font-weight: 600; font-size: 15px;
    display: inline-block; border: 1px solid var(--ink);
  }
  .btn:hover { opacity: 0.88; }
  .btn-2 {
    background: var(--panel); color: var(--ink); border: 1px solid var(--line);
    padding: 11px 21px; border-radius: 10px; font-weight: 600; font-size: 15px;
    text-decoration: none; display: inline-block;
  }
  .btn-2:hover { border-color: var(--muted); }

  /* the assignment card — the one bold moment on the page */
  .assign {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: var(--radius); padding: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }
  .assign-row {
    display: grid; grid-template-columns: 92px 1fr; gap: 14px; align-items: start;
    padding: 15px 14px; border-radius: 10px;
  }
  .assign-row + .assign-row { border-top: 1px solid var(--line); }
  .assign-what { font-size: 13.5px; color: var(--muted); line-height: 1.5; }
  .assign-what b { display: block; color: var(--ink); font-weight: 620; font-size: 14px; }
  .kind {
    display: inline-block; font-size: 12px; font-weight: 680; padding: 4px 11px;
    border-radius: 7px; letter-spacing: 0.015em;
  }
  .k-code  { background: var(--code-bg);  color: var(--code); }
  .k-agent { background: var(--agent-bg); color: var(--agent); }
  .k-human { background: var(--human-bg); color: var(--human); }
  .assign-cap {
    font-size: 12.5px; color: var(--muted); padding: 12px 14px 6px;
    border-top: 1px solid var(--line); margin-top: 2px;
  }

  /* --- proof strip ------------------------------------------------------- */
  .strip { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  .strip-in { display: flex; flex-wrap: wrap; gap: 10px; padding: 18px 0; }
  .fact {
    font-size: 13px; background: var(--panel); border: 1px solid var(--line);
    border-radius: 999px; padding: 5px 13px; color: var(--muted);
  }
  .fact b { color: var(--ink); font-weight: 620; }

  /* --- generic panels ---------------------------------------------------- */
  .panel {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: var(--radius); padding: 24px;
  }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
  /* Grid items default to min-width:auto, so a wide code block sets a floor the
     track cannot shrink below and the whole page scrolls sideways on a phone.
     The scroll belongs inside the <pre>, not on the document. */
  .grid-2 > *, .grid-3 > *, .compile > *, .hero-grid > * { min-width: 0; }
  @media (max-width: 900px) {
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
  }

  /* --- failure list ------------------------------------------------------ */
  .fails { list-style: none; margin: 0; padding: 0; }
  .fails li {
    padding: 15px 0; border-top: 1px solid var(--line);
    display: grid; grid-template-columns: 210px 1fr; gap: 18px;
  }
  .fails li:first-child { border-top: none; padding-top: 0; }
  .fails b { font-weight: 620; letter-spacing: -0.008em; }
  .fails span { color: var(--muted); font-size: 15px; }
  @media (max-width: 700px) { .fails li { grid-template-columns: 1fr; gap: 5px; } }

  /* --- code / terminal --------------------------------------------------- */
  pre {
    background: var(--term-bg); color: var(--term-ink); border-radius: 11px;
    padding: 17px 19px; overflow-x: auto; font-size: 13px; line-height: 1.6;
    margin: 0; border: 1px solid transparent;
  }
  pre.plain {
    background: var(--panel); color: var(--ink); border: 1px solid var(--line);
  }
  .t-dim { color: #8f8a9c; }
  .t-warn { color: #f7a8a8; }
  .t-ok { color: #86e2b0; }
  .t-key { color: #c4b5fd; }
  .t-str { color: #9fd0ff; }
  .cap { font-size: 13px; color: var(--muted); margin: 10px 0 0; }

  /* --- compile row ------------------------------------------------------- */
  .compile { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; align-items: start; }
  @media (max-width: 900px) { .compile { grid-template-columns: 1fr; } }
  .outs { display: flex; flex-direction: column; gap: 10px; margin: 0; padding: 0; list-style: none; }
  .out {
    display: flex; gap: 13px; align-items: baseline;
    border: 1px solid var(--line); border-radius: 11px; padding: 13px 15px;
    background: var(--panel);
  }
  .out code { font-size: 12.5px; color: var(--accent); font-weight: 600; white-space: nowrap; }
  .out span { font-size: 14px; color: var(--muted); }

  /* --- diagram ----------------------------------------------------------- */
  figure { margin: 0; }
  /* Fixed light backing in both schemes: the SVG is drawn once at generation
     time in a single theme, so a dark card would put dark ink on dark. The
     artifact template makes the same choice for the same reason. */
  .diagram {
    background: #ffffff; border: 1px solid var(--line); border-radius: 11px;
    padding: 20px 14px; text-align: center; overflow-x: auto;
  }
  /* The example workflow is tall and narrow (seven nodes stacked). Cap the
     height so it sits beside its explanation instead of towering over it, and
     override the artifact's width="100%" so the box tracks the drawing rather
     than letterboxing it. */
  .diagram svg { width: auto; height: auto; max-width: 100%; max-height: 600px; }
  .legend {
    display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px;
    color: var(--muted); margin: 14px 0 0; padding: 0; list-style: none;
  }
  .legend li { display: inline-flex; align-items: center; gap: 8px; }
  .sw { width: 12px; height: 12px; border-radius: 4px; display: inline-block; flex: none; }

  /* --- steps ------------------------------------------------------------- */
  .steps { counter-reset: s; list-style: none; margin: 0; padding: 0; }
  .steps li {
    counter-increment: s; position: relative; padding: 0 0 26px 46px;
    border-left: 2px solid var(--line); margin-left: 13px;
  }
  .steps li:last-child { border-left-color: transparent; padding-bottom: 0; }
  .steps li::before {
    content: counter(s); position: absolute; left: -14px; top: -2px;
    width: 27px; height: 27px; border-radius: 50%; background: var(--panel);
    border: 1px solid var(--line); color: var(--muted);
    font-size: 12.5px; font-weight: 660; display: grid; place-items: center;
  }
  .steps p { color: var(--muted); font-size: 15px; margin: 4px 0 0; }

  /* --- limits ------------------------------------------------------------ */
  .limits { list-style: none; margin: 0; padding: 0; }
  .limits li {
    padding: 13px 0; border-top: 1px solid var(--line); color: var(--muted);
    font-size: 15px;
  }
  .limits li:first-child { border-top: none; }
  .limits b { color: var(--ink); font-weight: 620; }

  /* --- footer ------------------------------------------------------------ */
  footer { border-top: 1px solid var(--line); padding: 40px 0 60px; }
  .foot {
    display: flex; flex-wrap: wrap; gap: 12px 26px; align-items: center;
    font-size: 14px; color: var(--muted);
  }
  .foot a { color: var(--muted); text-decoration: none; }
  .foot a:hover { color: var(--ink); text-decoration: underline; }
  .foot .sep { margin-left: auto; }
"""

# ------------------------------------------------------------------ page body

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WorkflowWright — assign each step to the cheapest resource that can do it</title>
<meta name="description" content="Design agent workflows by assigning each step to code, an agent, or a human — then compile one spec into a design doc, a diagram, and a runnable orchestrator with bounded retries.">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="data:image/svg+xml,__FAVICON__">
<style>__STYLES__</style>
</head>
<body>

<nav class="nav">
  <div class="wrap nav-in">
    <a class="brand" href="#top">__MARK__ WorkflowWright</a>
    <div class="nav-links">
      <a href="#idea">The idea</a>
      <a href="#compile">One spec</a>
      <a href="#modes">Modes</a>
      <a href="#driver">Generated code</a>
      <a href="#start">Install</a>
      <a class="ghost" href="__REPO__">GitHub</a>
    </div>
    <details class="menu">
      <summary aria-label="Menu">Menu</summary>
      <div class="menu-panel">
        <a href="#idea">The idea</a>
        <a href="#compile">One spec, four outputs</a>
        <a href="#modes">Modes</a>
        <a href="#driver">Generated code</a>
        <a href="#start">Install</a>
        <a href="__REPO__">GitHub</a>
      </div>
    </details>
  </div>
</nav>

<main id="top">

  <header class="wrap hero">
    <div class="hero-grid">
      <div>
        <h1>Agent workflows fail for structural reasons, not prompting reasons.</h1>
        <p class="lede">The model call that should have been a function. The retry loop
        with no ceiling. The check folded into the producer's own turn, where nobody can
        count it. WorkflowWright makes you assign every step to code, an agent, or a
        person — then compiles that decision into a diagram and a runnable orchestrator
        that cannot drift apart.</p>
        <div class="cta-row">
          <a class="btn" href="#start">Install it</a>
          <a class="btn-2" href="__REPO__">View on GitHub</a>
          <a class="btn-2" href="__REPO__/blob/main/docs/manual.md">Read the manual</a>
        </div>
      </div>

      <div class="assign" role="table" aria-label="How each step is assigned">
        <div class="assign-row" role="row">
          <span class="kind k-code" role="cell">Code</span>
          <span class="assign-what" role="cell"><b>Deterministic, ~free</b>
          Anything whose output is fixed by its input. Moving a ticket, running a linter,
          branching on a rule you can write down.</span>
        </div>
        <div class="assign-row" role="row">
          <span class="kind k-agent" role="cell">Agent</span>
          <span class="assign-what" role="cell"><b>Variable, costs tokens</b>
          Ambiguous input, novel output, judgment at scale. The steps you cannot write
          as an <code>if</code>.</span>
        </div>
        <div class="assign-row" role="row">
          <span class="kind k-human" role="cell">Human</span>
          <span class="assign-what" role="cell"><b>Highest judgment, scarcest</b>
          Taste, accountability, and anything irreversible or expensive to undo.</span>
        </div>
        <p class="assign-cap">These three colours are the same ones the tool draws in
        every diagram it generates, including the one below.</p>
      </div>
    </div>
  </header>

  <div class="strip">
    <div class="wrap strip-in">
      <span class="fact"><b>MIT</b> licensed</span>
      <span class="fact"><b>Python 3.10+</b>, standard library only</span>
      <span class="fact"><b>88 tests</b>, no network or token spend</span>
      <span class="fact">CI on <b>Linux and Windows</b></span>
      <span class="fact">Claude skill <b>+ standalone scripts</b></span>
    </div>
  </div>

  <section id="idea" class="wrap">
    <p class="eyebrow">The idea</p>
    <h2>Most of designing a workflow is assignment</h2>
    <div class="prose">
      <p>Pick the cheapest resource that can actually do each step, then decide what
      happens when it fails. Almost everything else follows from that.</p>
      <p>Two errors account for most broken pipelines. <strong>Over-assigning to
      agents</strong>, because when you have an agent available every step looks like an
      agent step — including the ones a five-line script does deterministically, for free,
      the same way every time. And <strong>approval gates in the middle</strong>, each of
      which caps throughput at one person's availability no matter how much compute you
      point at the rest.</p>
      <p>WorkflowWright ships a review rubric of twelve such patterns. These are the ones
      it finds most often:</p>
    </div>
    <ul class="fails">
      <li><b>Agent-shaped code</b><span>A model call whose output is fully determined by
      its input — and which is therefore right 99% of the time, which is much harder to
      debug than right always or never.</span></li>
      <li><b>Swallowed loop</b><span>"Run the tests and fix any failures" inside the
      builder's own turn. You cannot count those attempts, cap them, read the output, or
      route the failure anywhere else.</span></li>
      <li><b>Unbounded retry</b><span>A failure edge with no ceiling. Unattended, this is
      the one that produces a surprising invoice.</span></li>
      <li><b>Amnesiac retry</b><span>Failure routed back to a cold invocation, so the agent
      spends tokens re-deriving what it already knew and often makes a different first
      mistake instead of fixing the reported one.</span></li>
      <li><b>Implicit handoff</b><span>Edges that carry no named payload. Works until a node
      is retried, reordered, or isolated — then fails in a way nobody can trace, because
      the missing thing was never named.</span></li>
    </ul>
  </section>

  <section id="compile" class="wrap">
    <p class="eyebrow">One spec, four outputs</p>
    <h2>The diagram, the doc, and the code are generated from the same file</h2>
    <div class="prose">
      <p>Design decisions live in <code>spec.json</code>. Everything else is compiled from
      it, so the picture cannot quietly stop matching the code.</p>
    </div>
    <div class="compile">
      <div>
        <pre><span class="t-dim">// spec.json — one node and its failure edge</span>
{
  <span class="t-key">"id"</span>: <span class="t-str">"build"</span>,
  <span class="t-key">"kind"</span>: <span class="t-str">"agent"</span>,
  <span class="t-key">"model"</span>: <span class="t-str">"sonnet"</span>,
  <span class="t-key">"reads"</span>: [<span class="t-str">"plan.md"</span>, <span class="t-str">"verify-report.txt"</span>],
  <span class="t-key">"max_attempts"</span>: 3,
  <span class="t-key">"on_exhausted"</span>: <span class="t-str">"human"</span>
}
{
  <span class="t-key">"from"</span>: <span class="t-str">"verify"</span>, <span class="t-key">"to"</span>: <span class="t-str">"build"</span>,
  <span class="t-key">"when"</span>: <span class="t-str">"fail"</span>, <span class="t-key">"loop"</span>: true,
  <span class="t-key">"payload"</span>: <span class="t-str">"verify-report.txt"</span>
}</pre>
        <p class="cap">A bounded loop: the builder gets three attempts, each one resuming
        its own session with the verifier's report, then a person decides.</p>
      </div>
      <ul class="outs">
        <li class="out"><code>design.md</code><span>A design doc someone who missed the
        conversation can read and act on.</span></li>
        <li class="out"><code>.mermaid</code><span>Diagram source, for pasting into a
        README or a ticket.</span></li>
        <li class="out"><code>.html</code><span>A self-contained artifact with the diagram
        pre-rendered — no CDN, works offline.</span></li>
        <li class="out"><code>workflow.py</code><span>A runnable orchestrator package:
        driver, retry bounds, routing, prompts, steps.</span></li>
      </ul>
    </div>
  </section>

  <section class="wrap">
    <div class="grid-2" style="align-items:center">
      <div>
        <p class="eyebrow">Real output</p>
        <h2>This is the tool's own diagram</h2>
        <div class="prose">
          <p>Not a mockup. The SVG below is extracted from the artifact
          <code>render_workflow.py</code> generates for the bundled example spec — a
          ticket-to-pull-request workflow — and this page is rebuilt from it.</p>
          <p>Shape carries meaning alongside colour: rectangles are code, rounded nodes
          are agents, hexagons are people. The dashed edge is the bounded retry loop,
          carrying the verifier's report back to the builder.</p>
        </div>
      </div>
      <figure>
        <div class="diagram">__DIAGRAM__</div>
        <ul class="legend">
          <li><i class="sw" style="background:var(--code-bg);border:1px solid var(--code)"></i> Code — deterministic</li>
          <li><i class="sw" style="background:var(--agent-bg);border:1px solid var(--agent)"></i> Agent — judgment</li>
          <li><i class="sw" style="background:var(--human-bg);border:1px solid var(--human)"></i> Human — scarce</li>
        </ul>
        <figcaption class="cap">Humans appear at intake and acceptance only. Everything
        between them runs unattended.</figcaption>
      </figure>
    </div>
  </section>

  <section id="modes" class="wrap">
    <p class="eyebrow">Three modes</p>
    <h2>Depending on what already exists</h2>
    <div class="grid-3">
      <div class="panel">
        <h3>Design</h3>
        <p class="cap" style="margin:0 0 10px">Nothing built yet</p>
        <p style="font-size:15px;color:var(--muted);margin:0">Interviews you and writes the
        spec. It asks for <strong style="color:var(--ink)">one specific recent run</strong>
        of the process, ideally one that went wrong — because failure paths decide whether
        a design survives contact with reality, and nobody volunteers them.</p>
      </div>
      <div class="panel">
        <h3>Critique</h3>
        <p class="cap" style="margin:0 0 10px">A workflow already exists</p>
        <p style="font-size:15px;color:var(--muted);margin:0">Reconstructs a spec from a
        script, a set of prompts, or a CI config, then reviews it against twelve patterns.
        The fields it cannot fill in are usually the parts that are broken. It reviews
        architecture, not the code your workflow produces.</p>
      </div>
      <div class="panel">
        <h3>Scaffold</h3>
        <p class="cap" style="margin:0 0 10px">The spec is agreed</p>
        <p style="font-size:15px;color:var(--muted);margin:0">Compiles the spec into a
        Python package where orchestration is deterministic and agents are separate
        processes. Regenerating overwrites the driver and never touches your prompts
        or steps.</p>
      </div>
    </div>
  </section>

  <section class="wrap">
    <p class="eyebrow">The validator</p>
    <h2>It refuses to generate a workflow that will hurt you</h2>
    <div class="grid-2">
      <div class="prose">
        <p>Structural problems are far cheaper to fix in a spec than in generated code that
        has already spent tokens discovering them. So the scaffolder checks first and exits
        non-zero.</p>
        <p>The spec on the right looks reasonable. It has a producer, a checker, and a
        retry loop. Here is what the validator actually said about it — unedited:</p>
      </div>
      <div>
        <pre><span class="t-dim">$ python3 scaffold_workflow.py triage.json --out ./triage</span>
<span class="t-warn">refusing to scaffold a spec with structural problems:</span>
  - Edge test -&gt; fix names no payload. An unnamed edge
    carries an assumption, not data.
  - Node 'test' has a fail edge but no pass edge — the
    success path goes nowhere.
  - No terminal node — every path loops forever.
  - Node 'fix' is the target of a retry edge but has no
    max_attempts. Unbounded retries against a paid API
    are the one design error here that costs real money
    unattended.</pre>
        <p class="cap">Four real defects, none of which are visible by reading the spec
        casually, and the last of which bills you while you sleep.</p>
      </div>
    </div>
  </section>

  <section id="driver" class="wrap">
    <p class="eyebrow">The generated orchestrator</p>
    <h2>Four things it gets right that are easy to get wrong by hand</h2>
    <div class="prose">
      <p>Each of these was a bug first. All four are pinned by tests, so regenerating or
      refactoring cannot quietly undo them.</p>
    </div>
    <ol class="steps">
      <li>
        <h3>Retries are counted against the node the failure re-enters</h3>
        <p>Not the checker that failed. A checker failing is the checker doing its job —
        count attempts there and the first legitimate rejection exhausts the loop.</p>
      </li>
      <li>
        <h3>A retried agent resumes its own session</h3>
        <p>The producer already holds the context of what it attempted; what it lacks is
        the news that it failed. Starting cold throws away the first to deliver the
        second.</p>
      </li>
      <li>
        <h3>Every payload is a file</h3>
        <p>So <code>--only build</code> reruns one node against the last run's inputs
        instead of replaying the whole workflow to reach it — and a failed run leaves
        something readable behind.</p>
      </li>
      <li>
        <h3>Prompts travel on stdin, never argv</h3>
        <p>They carry whole payload files. Windows caps a command line at 8191 characters
        through <code>cmd.exe</code> shims, which also truncate at the first newline —
        silently, so the agent answers a fragment and the run still looks fine.</p>
      </li>
    </ol>
  </section>

  <section class="wrap">
    <p class="eyebrow">Terminal or assistant</p>
    <h2>Two ways to run agent nodes, one set of guarantees</h2>
    <div class="prose">
      <p>Routing, retry ceilings, and payloads live in the driver, not at the process
      boundary — so they are identical either way. Only the model call moves.</p>
    </div>
    <div class="grid-2">
      <div class="panel">
        <h3>Subprocess <span class="kind k-code" style="margin-left:6px">default</span></h3>
        <p style="font-size:15px;color:var(--muted);margin:10px 0 0">Each agent node
        spawns an agent CLI, and the run goes start to finish on its own. What you want
        from a terminal, from CI, or from cron.</p>
      </div>
      <div class="panel">
        <h3>Delegate <span class="kind k-agent" style="margin-left:6px">--delegate</span></h3>
        <p style="font-size:15px;color:var(--muted);margin:10px 0 0">The run parks at each
        agent node, writes the composed prompt to the run directory, and continues when you
        leave the answer beside it. No CLI on PATH, and no nested session spending tokens
        out of sight — the mode for working inside an assistant rather than a shell.</p>
      </div>
    </div>
    <div style="margin-top:22px">
      <pre><span class="t-dim">$ python3 workflow.py --delegate</span>
[10:22:14] intake [code] Fetch ticket, create worktree
[10:22:14] scout [agent] Locate relevant code and prior art

<span class="t-ok">=== scout is delegated ===</span>
This node is specified for model opus, limited to tools: Read, Grep, Glob.
Prompt written to : run/scout.prompt.md
Write the answer to: run/scout.result.md
<span class="t-dim">exit 76 — attempt counts and the retry ceiling are preserved across the pause</span></pre>
      <p class="cap">Real output from the bundled example. The prompt is fully composed
      with payloads substituted, so you do exactly the work a model would have done.</p>
    </div>
  </section>

  <section id="start" class="wrap">
    <p class="eyebrow">Install</p>
    <h2>Three ways in, depending on where you work</h2>
    <div class="prose">
      <p><strong>Do not use GitHub's green Code button.</strong> That downloads the
      source tree, where <code>SKILL.md</code> sits two directories deep, and the
      claude.ai uploader rejects it. Use one of these instead — both are one step.</p>
    </div>
    <div class="grid-2">
      <div>
        <pre class="plain"><span class="t-dim"># Claude Code — paste into a session</span>
/plugin marketplace add scottconverse/WorkflowWright
/plugin install workflowwright@workflowwright

<span class="t-dim"># and to remove it</span>
/plugin uninstall workflowwright</pre>
        <p class="cap"><b>Claude Code.</b> No clone, no build step, and updates arrive
        through <code>/plugin marketplace update</code>.</p>
        <pre class="plain"><span class="t-dim"># Claude desktop or web</span>
Settings → Skills → Upload skill
<span class="t-ok">workflowwright.zip</span> <span class="t-dim">← from the release below</span></pre>
        <p class="cap"><b>Desktop and web</b> read your claude.ai account rather than a
        marketplace, so they take the packaged archive.
        <a href="__REPO__/releases/latest/download/workflowwright.zip"><b>Download
        workflowwright.zip</b></a> · <a href="__REPO__/releases/latest">all releases</a></p>
        <pre class="plain"><span class="t-dim"># Codex and Antigravity — same format, a copy</span>
cp -r skill ~/.codex/skills/workflowwright
cp -r skill ~/.gemini/config/skills/workflowwright</pre>
        <p class="cap"><b>Other hosts.</b> Both read a skill as a directory with
        <code>SKILL.md</code> and frontmatter, which is the shape this already has — no
        adapter, no conversion. Verified by installing to those paths and running the
        scripts from them. <a href="__REPO__/blob/main/AGENTS.md">AGENTS.md</a> covers
        the rest.</p>
        <p class="cap">Then just describe the problem — "every time a bug comes in I read
        the ticket, write a fix, run the tests, and open a PR; can we automate that?" The
        skill triggers on natural phrasing, so you never name it.
        <a href="__REPO__/blob/main/docs/manual.md#installing-and-updating">Full install
        and uninstall guide</a>.</p>
      </div>
      <div>
        <pre class="plain"><span class="t-dim"># or drive the tooling directly</span>
python3 skill/scripts/render_workflow.py \\
    spec.json --out ./out

python3 skill/scripts/scaffold_workflow.py \\
    spec.json --out ./my-workflow

make test   <span class="t-dim"># 88 tests, no network</span></pre>
        <p class="cap">Nothing here needs an API key. Designing and rendering never call a
        model.</p>
      </div>
    </div>
  </section>

  <section class="wrap">
    <p class="eyebrow">Status and limits</p>
    <h2>What this is not, yet</h2>
    <div class="prose">
      <p>New and openly developed, with a real test suite: 51 stdlib tests covering the
      validator, the renderer, and the generated driver's retry and session behaviour,
      running on Python 3.10–3.13 on Linux and on Windows. No releases have been tagged
      yet.</p>
    </div>
    <ul class="limits" style="max-width:64ch">
      <li><b>The scaffold is a skeleton.</b> Every generated step exits 1 with a TODO until
      you write it — a stub that returned success would be worse than no stub.</li>
      <li><b>Isolation is a design decision, not an implementation.</b> A spec declares
      <code>worktree</code> or <code>sandbox</code> and the docs reason about the choice,
      but the generated code does not create worktrees or containers. That belongs in your
      intake step.</li>
      <li><b>Running a workflow <em>unattended</em> needs the <code>claude</code> CLI</b>
      on PATH. Designing, rendering, critiquing, and scaffolding never call a model at
      all, and <code>--delegate</code> runs a workflow with no CLI involved.</li>
      <li><b>Offline diagrams need Playwright.</b> Without it, rendered artifacts fall back
      to loading Mermaid from a CDN and need network access to draw.</li>
      <li><b>The agent invocation is Claude-shaped.</b> Swapping in another CLI or an SDK
      means editing one function, <code>run_agent</code>, in <code>runner.py</code>.</li>
    </ul>
  </section>

  <section class="wrap" style="text-align:center">
    <h2>Start from the example spec</h2>
    <p class="lede" style="margin:0 auto">It is a complete ticket-to-pull-request workflow
    — seven nodes, a bounded loop, humans at both ends. Adapt it rather than starting from
    an empty file.</p>
    <div class="cta-row" style="justify-content:center">
      <a class="btn" href="__REPO__">View on GitHub</a>
      <a class="btn-2" href="__REPO__/blob/main/skill/assets/example-spec.json">Read the example spec</a>
    </div>
  </section>

</main>

<footer>
  <div class="wrap foot">
    <span>WorkflowWright</span>
    <a href="__REPO__">Repository</a>
    <a href="__REPO__/blob/main/docs/manual.md">Manual</a>
    <a href="__REPO__/blob/main/docs/manual.md#the-traps">The traps</a>
    <a href="__REPO__/blob/main/skill/references/spec-schema.md">Spec schema</a>
    <a href="__REPO__/issues">Issues</a>
    <span class="sep"><a href="__REPO__/blob/main/LICENSE">MIT licensed</a></span>
  </div>
</footer>

</body>
</html>
"""

# The mark: three stacked bars in the kind colours — code, agent, human.
MARK = (
    '<svg class="mark" viewBox="0 0 16 16" aria-hidden="true" fill="none">'
    '<rect x="0" y="1" width="16" height="4" rx="1.4" fill="#1d4ed8"/>'
    '<rect x="0" y="6.5" width="16" height="4" rx="1.4" fill="#6d28d9"/>'
    '<rect x="0" y="12" width="16" height="4" rx="1.4" fill="#b45309"/>'
    "</svg>"
)

FAVICON = (
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
    "%3Crect x='0' y='1' width='16' height='4' rx='1.4' fill='%231d4ed8'/%3E"
    "%3Crect x='0' y='6.5' width='16' height='4' rx='1.4' fill='%236d28d9'/%3E"
    "%3Crect x='0' y='12' width='16' height='4' rx='1.4' fill='%23b45309'/%3E"
    "%3C/svg%3E"
)


def build():
    if not EXAMPLE_ARTIFACT.exists():
        sys.exit(
            f"missing {EXAMPLE_ARTIFACT.relative_to(REPO)} — run `make example` first."
        )
    svg = extract_diagram(EXAMPLE_ARTIFACT)
    if svg is None:
        sys.exit(
            f"{EXAMPLE_ARTIFACT.relative_to(REPO)} has no inline SVG, so it was rendered "
            "without Playwright. The page embeds the diagram directly and must not fall "
            "back to a CDN. Install Playwright and re-run `make example`."
        )
    return (
        PAGE.replace("__STYLES__", STYLES)
        .replace("__DIAGRAM__", svg)
        .replace("__MARK__", MARK)
        .replace("__FAVICON__", FAVICON)
        .replace("__REPO__", REPO_URL)
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if index.html is out of date; write nothing",
    )
    args = ap.parse_args()

    page = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != page:
            sys.exit("docs/index.html is out of date — run `make site`.")
        print("docs/index.html is up to date")
        return
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(page):,} bytes, diagram inlined)")


if __name__ == "__main__":
    main()
