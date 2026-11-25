"""Self-contained HTML reports in the DataPassport identity.

The design: each report opens with a burgundy passport *cover* carrying the
dataset's Seal (a guilloché rosette drawn from its fingerprint), followed by a
*data page* of facts and a machine-readable line, then the detail. One file,
fonts embedded, no network requests, light and dark themes, works without
JavaScript, and respects reduced motion. Statuses are written as words with
drawn icons, never as coloured dots.
"""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING, Any

from ..drift import cdf
from ..fingerprint import short
from .fonts import font_css
from .seal import SEAL_CSS, seal_svg
from .words import DRIFT_WORDS, RESULT_WORDS, comparison_lede, passport_lede, type_words

if TYPE_CHECKING:
    from ..compare import Comparison
    from ..models import ColumnProfile, Passport
    from ..rules import CheckReport

E = html.escape

# --------------------------------------------------------------------- styles

CSS = """
:root{
--font-display:'DP Young Serif',Georgia,serif;--font-text:'DP Public Sans',system-ui,sans-serif;
--font-data:'DP Spline Mono',ui-monospace,monospace;
--cover-1:#8A2A3F;--cover-2:#5A1526;--cover-3:#2C0911;--foil:#E7C88A;--foil-2:#B98F4E;
--bg:#F5F6F8;--bg-light:rgba(138,42,63,.10);--surface:#FFFFFF;--surface-2:#FAFAFB;
--ink:#1D1618;--muted:#6B6164;--faint:#958B8E;--line:rgba(29,22,24,.08);
--accent:#8A2A3F;--chart:#9C3550;--chart-soft:rgba(156,53,80,.14);--base:#8F8589;
--ok:#26734A;--warn:#93600A;--bad:#B8361E;
--shadow:0 1px 0 rgba(255,255,255,.9) inset,0 1px 2px rgba(60,20,30,.05),0 12px 32px -14px rgba(70,20,32,.20);
--shadow-lift:0 1px 2px rgba(60,20,30,.06),0 30px 60px -28px rgba(70,20,32,.35);
--seal-ink:#EDD29A;--seal-glow:#F3D9A4;--seal-glow-opacity:.2;--radius:22px;
color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#0B0C0F;--bg-light:rgba(138,42,63,.20);--surface:#151215;--surface-2:#1A1619;
--ink:#F3EDEA;--muted:#A99FA2;--faint:#7C7275;--line:rgba(255,255,255,.07);
--chart:#E58AA0;--chart-soft:rgba(229,138,160,.16);--base:#8E8488;
--ok:#7DD3A0;--warn:#F2BE5C;--bad:#FF8E73;
--shadow:0 1px 0 rgba(255,255,255,.05) inset,0 20px 40px -20px rgba(0,0,0,.8);
--shadow-lift:0 1px 0 rgba(255,255,255,.05) inset,0 40px 70px -30px rgba(0,0,0,.9);
--seal-glow-opacity:.22;color-scheme:dark}}
:root[data-theme=dark]{--bg:#0B0C0F;--bg-light:rgba(138,42,63,.20);--surface:#151215;--surface-2:#1A1619;
--ink:#F3EDEA;--muted:#A99FA2;--faint:#7C7275;--line:rgba(255,255,255,.07);--chart:#E58AA0;
--chart-soft:rgba(229,138,160,.16);--base:#8E8488;--ok:#7DD3A0;--warn:#F2BE5C;--bad:#FF8E73;
--shadow:0 1px 0 rgba(255,255,255,.05) inset,0 20px 40px -20px rgba(0,0,0,.8);
--shadow-lift:0 1px 0 rgba(255,255,255,.05) inset,0 40px 70px -30px rgba(0,0,0,.9);--seal-glow-opacity:.22;color-scheme:dark}
*{box-sizing:border-box}
html{font-size:clamp(15px,.9rem + .2vw,17px)}
body{margin:0;color:var(--ink);font:400 1rem/1.55 var(--font-text);-webkit-font-smoothing:antialiased;
background:radial-gradient(70rem 36rem at 50% -8rem,var(--bg-light),transparent 70%),var(--bg);min-height:100vh}
main{max-width:70rem;margin:0 auto;padding:clamp(16px,4vw,48px) clamp(16px,4vw,40px) 4rem}
a{color:var(--accent)}
:focus-visible{outline:2.5px solid var(--chart);outline-offset:3px;border-radius:8px}
.data,.fp{font-family:var(--font-data);font-variant-numeric:tabular-nums}
/* cover */
.cover{position:relative;border-radius:calc(var(--radius) + 6px);color:#FBF1E6;overflow:hidden;
background:radial-gradient(120% 150% at 12% -10%,var(--cover-1) 0%,var(--cover-2) 46%,var(--cover-3) 100%);
box-shadow:0 1px 0 rgba(255,255,255,.18) inset,0 -1px 0 rgba(0,0,0,.3) inset,0 34px 60px -28px rgba(60,10,22,.75),0 10px 22px -12px rgba(60,10,22,.5);
padding:clamp(22px,4vw,44px) clamp(20px,4.5vw,52px) clamp(46px,6vw,70px);display:grid;
grid-template-columns:auto 1fr;gap:clamp(18px,4vw,48px);align-items:center}
.cover::before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.55;
background:repeating-radial-gradient(circle at 86% 120%,transparent 0 13px,rgba(231,200,138,.05) 13px 14px)}
.cover::after{content:"";position:absolute;left:0;right:0;top:0;height:45%;pointer-events:none;
background:linear-gradient(rgba(255,255,255,.07),transparent)}
.cover>*{position:relative}
.cover .seal{filter:drop-shadow(0 2px 0 rgba(0,0,0,.25)) drop-shadow(0 0 18px rgba(231,200,138,.12))}
.kind{margin:0 0 .35rem;color:#EBCDAA;font-size:.95rem}
h1{font:400 clamp(2rem,1.2rem + 3vw,3.4rem)/1.05 var(--font-display);margin:0 0 .8rem;letter-spacing:-.005em;
text-shadow:0 1px 0 rgba(0,0,0,.35);overflow-wrap:anywhere}
.lede{margin:0;max-width:44ch;font-size:clamp(1.02rem,.95rem + .3vw,1.2rem);line-height:1.5;color:#F1DED2}
.fpline{margin:1.1rem 0 0;display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;color:#E3C9BA;font-size:.92rem}
.fpline .fp{color:#F6DFB2;font-size:.9rem}
button.copy{font:500 .85rem var(--font-text);color:#FBF1E6;background:rgba(255,255,255,.10);border:0;border-radius:999px;
padding:.45rem .95rem;min-height:2.25rem;cursor:pointer;box-shadow:0 1px 0 rgba(255,255,255,.15) inset;
transition:background .18s,transform .12s}
button.copy:hover{background:rgba(255,255,255,.18)}button.copy:active{transform:scale(.96)}
/* data page */
.page{position:relative;margin:calc(-1 * clamp(26px,3.5vw,40px)) clamp(10px,2.4vw,26px) 0;background:var(--surface);
border-radius:0 0 var(--radius) var(--radius);box-shadow:var(--shadow-lift);padding:clamp(20px,3vw,34px) clamp(18px,3vw,36px) 1.2rem}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,8.5rem),1fr));gap:1.1rem 1.6rem;margin:0}
.facts dt{color:var(--muted);font-size:.88rem}.facts dd{margin:.15rem 0 0;font-size:1.12rem;font-weight:500}
.mrz{margin:1.3rem 0 0;color:var(--faint);font-size:.8rem;letter-spacing:.06em;white-space:nowrap;overflow:hidden;
text-overflow:clip;-webkit-mask-image:linear-gradient(90deg,#000 85%,transparent)}
/* sections */
h2{font:400 1.55rem/1.2 var(--font-display);margin:3.2rem 0 1rem}
.panel{background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
.head{display:flex;justify-content:space-between;align-items:end;gap:1rem;flex-wrap:wrap;margin:3.2rem 0 1rem}
.head h2{margin:0}
input[type=search]{font:inherit;color:var(--ink);background:var(--surface);border:0;border-radius:14px;padding:.6rem 1rem;
min-height:2.75rem;min-width:min(16rem,100%);box-shadow:var(--shadow)}
.row{display:grid;grid-template-columns:minmax(9rem,1.6fr) minmax(7rem,1fr) minmax(5rem,.7fr) minmax(8rem,1.3fr) 2rem;
gap:1rem;align-items:center;padding:.85rem 1.2rem;position:relative}
.row+.row::before,details+details>summary::before{content:"";position:absolute;top:0;left:1.2rem;right:1.2rem;border-top:1px solid var(--line)}
details{position:relative}
summary{list-style:none;cursor:pointer;transition:background .18s}
summary::-webkit-details-marker{display:none}
summary:hover{background:var(--surface-2)}
.name{font-weight:600;overflow-wrap:anywhere}.typ{display:block;color:var(--muted);font-size:.86rem;font-weight:400}
.miss{font-size:.95rem}.miss .bar{display:block;height:5px;border-radius:3px;background:var(--line);margin-top:.35rem;overflow:hidden}
.miss .bar i{display:block;height:100%;background:var(--warn);border-radius:3px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.chev{color:var(--faint);transition:transform .25s cubic-bezier(.3,1.4,.5,1);justify-self:end;font-size:1.3rem;line-height:1}
details[open] .chev{transform:rotate(90deg)}
.more{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1.6rem;padding:.4rem 1.2rem 1.5rem 1.2rem}
.more dl{display:grid;grid-template-columns:auto 1fr;gap:.3rem 1.2rem;margin:0;font-size:.93rem;align-content:start}
.more dt{color:var(--muted)}.more dd{margin:0;font-variant-numeric:tabular-nums}
.cats{list-style:none;margin:0;padding:0;font-size:.93rem}
.cats li{display:grid;grid-template-columns:1fr auto;gap:.6rem;padding:.25rem 0;position:relative}
.cats .b{position:absolute;left:0;bottom:0;height:2px;border-radius:2px;background:var(--chart);opacity:.55}
.tok{font-family:var(--font-data);font-size:.82rem;color:var(--muted)}
.note{color:var(--muted);font-size:.93rem}
svg.chart{display:block;width:100%;height:auto;max-width:12rem}
.chart .area{fill:url(#dp-area)}.chart .line{fill:none;stroke:var(--chart);stroke-width:1.6;stroke-linejoin:round}
.chart .base{fill:none;stroke:var(--base);stroke-width:1.3;stroke-dasharray:3 3}
.chart.big{max-width:22rem}
/* status words */
.st{display:inline-flex;gap:.4rem;align-items:center;font-weight:600;font-size:.95rem}
.st svg{width:1.05em;height:1.05em;flex:none}
.st.ok{color:var(--ok)}.st.warn{color:var(--warn)}.st.bad{color:var(--bad)}.st.skip{color:var(--faint);font-weight:500}
/* comparison */
.seals{display:flex;align-items:center;gap:.4rem}
.seals .arrow{color:#EBCDAA;font-size:1.6rem;padding:0 .2rem}
.ledger{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,6.5rem),1fr));gap:1rem 1.6rem;margin:0}
.ledger dd{margin:0;font:400 2rem/1.1 var(--font-display)}.ledger dt{color:var(--muted);font-size:.9rem;margin-top:.2rem}
.ledger div{display:flex;flex-direction:column-reverse}
.change{display:grid;grid-template-columns:minmax(10rem,auto) 1fr;gap:1rem;align-items:center;padding:.9rem 1.2rem;position:relative}
.change+.change::before{content:"";position:absolute;top:0;left:1.2rem;right:1.2rem;border-top:1px solid var(--line)}
.drift{grid-template-columns:minmax(9rem,1.2fr) minmax(10rem,1.3fr) minmax(8rem,1fr) minmax(8rem,1.2fr)}
.legend{display:flex;gap:1.4rem;color:var(--muted);font-size:.88rem;margin:.7rem .2rem 0}
.legend i{display:inline-block;width:1.3rem;border-top:2px solid var(--chart);vertical-align:middle;margin-right:.4rem}
.legend i.b{border-top:2px dashed var(--base)}
pre{font:.86rem/1.5 var(--font-data);background:var(--surface);box-shadow:var(--shadow);border-radius:16px;padding:1rem 1.2rem;overflow:auto;margin:.6rem 0 0}
.prov{display:grid;grid-template-columns:auto 1fr;gap:.45rem 1.6rem;margin:0;padding:1.3rem 1.4rem;font-size:.95rem}
.prov dt{color:var(--muted)}.prov dd{margin:0;overflow-wrap:anywhere}
footer{margin-top:3.5rem;color:var(--muted);font-size:.9rem;display:flex;gap:.6rem;align-items:center}
footer svg{flex:none}
@media (max-width:760px){
.cover{grid-template-columns:1fr;justify-items:start}.cover .seal svg{width:8.5rem;height:8.5rem}
.row{grid-template-columns:1fr auto 1.6rem;row-gap:.4rem}.row .hide-sm{display:none}
.drift{grid-template-columns:1fr auto}.drift .hide-sm{display:none}
.change{grid-template-columns:1fr}}
@media print{body{background:#fff}button.copy,input[type=search]{display:none}details{break-inside:avoid}}
"""

JS = """
document.querySelectorAll('button.copy').forEach(b=>b.addEventListener('click',()=>{
if(!navigator.clipboard)return;navigator.clipboard.writeText(b.dataset.copy).then(()=>{const t=b.textContent;
b.textContent='Copied';setTimeout(()=>b.textContent=t,1400)})}));
const f=document.getElementById('filter');if(f){f.addEventListener('input',()=>{const q=f.value.toLowerCase();
document.querySelectorAll('[data-col]').forEach(r=>{r.hidden=!r.dataset.col.toLowerCase().includes(q)})})}
"""

GRADIENT = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
    '<linearGradient id="dp-area" x1="0" x2="0" y1="0" y2="1">'
    '<stop offset="0" stop-color="var(--chart)" stop-opacity=".42"/>'
    '<stop offset="1" stop-color="var(--chart)" stop-opacity=".02"/></linearGradient></defs></svg>'
)

# Drawn icons (stroke, currentColor). No emoji or glyph stand-ins.
ICONS = {
    "ok": '<path d="M4 10.5l3.6 3.6L16 5.8" fill="none" stroke="currentColor" stroke-width="2.1" '
    'stroke-linecap="round" stroke-linejoin="round"/>',
    "warn": '<path d="M10 3.2l7.6 13.3H2.4z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>'
    '<path d="M10 8.2v3.6" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
    '<circle cx="10" cy="14.1" r="1.05" fill="currentColor"/>',
    "bad": '<path d="M5.5 5.5l9 9M14.5 5.5l-9 9" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/>',
    "skip": '<path d="M5 10h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "lock": '<rect x="4.5" y="9" width="11" height="8" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/>'
    '<path d="M7 9V6.8a3 3 0 0 1 6 0V9" fill="none" stroke="currentColor" stroke-width="1.6"/>',
}


def icon(name: str) -> str:
    return f'<svg viewBox="0 0 20 20" aria-hidden="true">{ICONS[name]}</svg>'


def status(kind: str, words: str) -> str:
    return f'<span class="st {kind}">{icon(kind)}{E(words)}</span>'


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="generator" content="datapassport"><title>{E(title)}</title>'
        f"<style>{font_css()}{SEAL_CSS}{CSS}</style></head><body>{GRADIENT}<main>{body}</main>"
        f"<script>{JS}</script></body></html>\n"
    )


# ------------------------------------------------------------------- helpers


def _n(v: Any, digits: int = 4) -> str:
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        if v != v:
            return "NaN"
        if v != 0 and (abs(v) >= 1e7 or abs(v) < 1e-3):
            return f"{v:.3g}"
        return f"{v:,.{digits}g}"
    return E(str(v))


def _bytes(n: int | None) -> str:
    if n is None:
        return "–"
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return str(n)


def _hist(qs: list[float], lo: float, hi: float, bins: int) -> list[float]:
    width = (hi - lo) / bins
    mass = [max(0.0, cdf(qs, lo + width * (i + 1)) - cdf(qs, lo + width * i)) for i in range(bins)]
    if qs and qs[0] <= lo:
        mass[0] += cdf(qs, lo)
    return mass


def distribution_svg(
    target: list[float],
    base: list[float] | None = None,
    *,
    w: int = 180,
    h: int = 44,
    label: str = "",
    big: bool = False,
) -> str:
    """Area chart of ``target`` with an optional dashed outline of ``base``."""
    series = [q for q in (target, base) if q]
    if not series:
        return ""
    lo = min(q[0] for q in series)
    hi = max(q[-1] for q in series)
    cls = "chart big" if big else "chart"
    if hi <= lo:
        return (
            f'<svg class="{cls}" viewBox="0 0 {w} {h}" role="img" aria-label="{E(label)}: every value is {_n(lo)}">'
            f'<rect x="{w / 2 - 2}" y="2" width="4" height="{h - 2}" rx="2" fill="var(--chart)"/></svg>'
        )
    levels = sorted(set(target) | set(base or []))
    if len(levels) <= 16:
        return _discrete_svg(target, base, levels, w=w, h=h, label=label, cls=cls)
    bins = 28
    tm = _hist(target, lo, hi, bins)
    bm = _hist(base, lo, hi, bins) if base else None
    top = max(tm + (bm or [])) or 1
    step = w / bins

    def pts(mass: list[float]) -> list[tuple[float, float]]:
        out = [(0.0, h - mass[0] / top * (h - 3))]
        out += [((i + 0.5) * step, h - m / top * (h - 3)) for i, m in enumerate(mass)]
        out.append((w, h - mass[-1] / top * (h - 3)))
        return out

    t = pts(tm)
    line = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in t)
    parts = [f'<path class="area" d="{line} L{w} {h} L0 {h}Z"/>', f'<path class="line" d="{line}"/>']
    if bm:
        b = pts(bm)
        parts.append(f'<path class="base" d="M{" L".join(f"{x:.1f} {y:.1f}" for x, y in b)}"/>')
    desc = f"{label}: values from {_n(lo)} to {_n(hi)}, median {_n(target[len(target) // 2])}"
    if base:
        desc += f"; before, median {_n(base[len(base) // 2])}"
    return (
        f'<svg class="{cls}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
        f'aria-label="{E(desc)}">{"".join(parts)}</svg>'
    )


def _shares(qs: list[float], levels: list[float]) -> list[float]:
    """Share of rows at each discrete level, read off the quantile summary."""
    n = len(qs) - 1
    return [sum(1 for q in qs[:-1] if q == v) / n if n else 0.0 for v in levels]


def _discrete_svg(
    target: list[float], base: list[float] | None, levels: list[float], *, w: int, h: int, label: str, cls: str
) -> str:
    """Bars for columns with only a few distinct values (counts, ratings, flags)."""
    t = _shares(target, levels)
    b = _shares(base, levels) if base else None
    top = max(t + (b or [])) or 1
    slot = w / len(levels)
    bw = max(2.0, min(slot * 0.62, 26.0))
    parts = []
    for i, share in enumerate(t):
        bh = max(1.5, share / top * (h - 3))
        x = i * slot + (slot - bw) / 2
        parts.append(
            f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2" '
            f'fill="url(#dp-area)" stroke="var(--chart)" stroke-width="1.2"/>'
        )
        if b:
            by = h - b[i] / top * (h - 3)
            parts.append(f'<path class="base" d="M{x - 2:.1f} {by:.1f}H{x + bw + 2:.1f}"/>')
    desc = f"{label}: {len(levels)} distinct values from {_n(levels[0])} to {_n(levels[-1])}"
    return f'<svg class="{cls}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="{E(desc)}">{"".join(parts)}</svg>'


def _quantiles(c: ColumnProfile) -> list[float]:
    if c.numeric and c.numeric.quantiles:
        return c.numeric.quantiles
    if c.temporal and c.temporal.quantiles:
        return c.temporal.quantiles
    return []


def _missing(c: ColumnProfile) -> str:
    if c.nulls == 0:
        words = "None missing"
    elif c.count == 0:
        words = "All missing"
    else:
        words = f"{c.null_fraction:.1%} missing"
    return (
        f'<span class="miss">{words}<span class="bar" aria-hidden="true">'
        f'<i style="width:{c.null_fraction * 100:.1f}%"></i></span></span>'
    )


def _mrz(kind: str, name: str, rows: int, cols: int, fp: str) -> str:
    clean = "".join(ch if ch.isalnum() else "<" for ch in name.upper())[:24]
    line = f"{kind}<{clean}<<{rows}<<{cols}<<{fp[:28].upper()}"
    return E(line.ljust(88, "<"))


def _seal_label(name: str, rows: int, fp: str) -> str:
    return f"{name} · {rows:,} rows · {fp[:12]}"


# ------------------------------------------------------------------ passport


def _detail(c: ColumnProfile) -> str:
    rows: list[tuple[str, str]] = [
        ("Stored as", E(c.type)),
        ("Values present", _n(c.count)),
        ("Missing", f"{_n(c.nulls)} ({c.null_fraction:.2%})"),
        ("Distinct", _n(c.distinct) + ("" if c.distinct_exact else ", estimated")),
    ]
    if c.numeric:
        n = c.numeric
        q = n.quantiles
        rows += [
            ("Smallest", _n(n.min)),
            ("Largest", _n(n.max)),
            ("Average", _n(n.mean)),
            ("Spread (std. dev.)", _n(n.std)),
        ]
        if q:
            rows += [("Middle 98%", f"{_n(q[1])} to {_n(q[99])}"), ("Median", _n(q[50]))]
        rows += [("Zeros", _n(n.zeros)), ("Negatives", _n(n.negatives))]
        if n.nan or n.infinite:
            rows += [("Not a number", _n(n.nan)), ("Infinite", _n(n.infinite))]
    if c.text:
        t = c.text
        rows += [
            ("Length", f"{_n(t.min_length)} to {_n(t.max_length)} characters"),
            ("Empty", _n(t.empty)),
            ("Only spaces", _n(t.blank)),
        ]
    if c.temporal:
        rows += [("Earliest", _n(c.temporal.min)), ("Latest", _n(c.temporal.max))]
    if c.boolean:
        rows += [("Yes", _n(c.boolean.get("true"))), ("No", _n(c.boolean.get("false")))]
    for k, v in c.extras.items():
        rows.append((E(k), _n(v) if not isinstance(v, (dict, list)) else E(json.dumps(v))))
    blocks = ["<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"]
    qs = _quantiles(c)
    if c.sensitive:
        blocks.append(
            f'<p class="note">{status("skip", "Withheld")} This column is marked sensitive, '
            "so its distribution and values are not recorded.</p>"
        )
    elif qs:
        blocks.append(f"<div>{distribution_svg(qs, w=360, h=110, label=c.name, big=True)}</div>")
    if c.categories:
        cat = c.categories
        total = max(c.count, 1)
        shown = cat.values if cat.values is not None else cat.tokens
        items = []
        for lab, count in zip(shown, cat.counts, strict=True):
            text = E(lab) if cat.values is not None else f'<span class="tok">#{E(lab)}</span>'
            items.append(
                f"<li><span>{text}</span><span>{count:,}</span>"
                f'<span class="b" style="width:{count / total * 100:.1f}%"></span></li>'
            )
        if cat.other:
            items.append(f'<li><span class="note">Everything else</span><span>{cat.other:,}</span></li>')
        caption = (
            "Most frequent values"
            if cat.values is not None
            else "Most frequent values, shown as tokens because this passport hides raw values"
        )
        blocks.append(
            f'<div><p class="note" style="margin:0 0 .4rem">{caption}</p><ul class="cats">{"".join(items)}</ul></div>'
        )
    return f'<div class="more">{"".join(blocks)}</div>'


def _columns(p: Passport) -> str:
    rows = []
    for name in p.column_names:
        c = p.columns[name]
        qs = _quantiles(c)
        if c.sensitive:
            shape = status("skip", "Withheld")
        elif qs:
            shape = distribution_svg(qs, label=name)
        elif c.categories:
            shape = f'<span class="note">{len(c.categories.counts)} common values</span>'
        elif c.text:
            shape = f'<span class="note">{_n(c.text.min_length)}–{_n(c.text.max_length)} characters</span>'
        else:
            shape = ""
        distinct = _n(c.distinct) + ("" if c.distinct_exact else " est.")
        rows.append(
            f'<details data-col="{E(name)}"><summary class="row">'
            f'<span class="name">{E(name)}<span class="typ">{E(type_words(c.type))}</span></span>'
            f'{_missing(c)}<span class="num hide-sm">{distinct}<span class="typ">distinct</span></span>'
            f'<span class="hide-sm">{shape}</span><span class="chev" aria-hidden="true">›</span>'
            f"</summary>{_detail(c)}</details>"
        )
    return f'<div class="panel" role="list">{"".join(rows)}</div>'


def _provenance(p: Passport) -> str:
    s = p.source
    items = [("Source", E(s.uri or s.kind)), ("Read as", E(s.kind))]
    if s.bytes is not None:
        items.append(("Size", _bytes(s.bytes) + (f" in {s.files} files" if s.files and s.files > 1 else "")))
    if s.sha256:
        items.append(("File sha256", f'<span class="fp">{E(s.sha256)}</span>'))
    items += [
        ("Fingerprint", f'<span class="fp">{E(p.fingerprint.dataset)}</span>'),
        (
            "Method",
            f"{E(p.fingerprint.spec)}, floats to {p.fingerprint.float_digits} significant digits, row order ignored",
        ),
        (
            "Profile",
            "Every row"
            if p.sample.method == "full"
            else f"{p.sample.rows_profiled:,} sampled rows (seed {p.sample.seed}); fingerprint and duplicates use every row",
        ),
        ("Quantiles", "Exact" if p.options.quantiles == "exact" else "Estimated (t-digest)"),
        ("Privacy", "No raw values recorded" if p.options.privacy == "safe" else "Most frequent values included"),
        ("Made by", f"DataPassport {E(p.producer.version)} with {E(p.producer.engine)}, Python {E(p.producer.python)}"),
    ]
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in items)
    cmd = f"datapassport verify {p.name or 'dataset'}.passport.json {s.uri or '<data>'}"
    return (
        f'<h2>Provenance</h2><div class="panel"><dl class="prov">{dl}</dl></div>'
        f'<p class="note" style="margin-top:1.2rem">To check that a copy holds exactly this data:</p>'
        f"<pre>{E(cmd)}</pre>"
    )


def _cover(kind: str, title: str, lede: str, fp: str, seal: str, extra: str = "") -> str:
    return (
        f'<header class="cover"><div class="seal">{seal}</div><div><p class="kind">{E(kind)}</p>'
        f'<h1>{E(title)}</h1><p class="lede">{lede}</p>'
        f'<p class="fpline">Fingerprint <span class="fp" title="{E(fp)}">{E(short(fp, 16))}</span>'
        f'<button class="copy" type="button" data-copy="{E(fp)}">Copy</button>{extra}</p></div></header>'
    )


def passport_fragment(p: Passport, *, animate: bool = True) -> str:
    fp = p.fingerprint.dataset
    name = p.name or "Dataset"
    seal = seal_svg(fp, label=_seal_label(name, p.rows, fp), size=210, uid="pp", animate=animate)
    k = p.duplicates.key
    facts = [
        ("Rows", f"{p.rows:,}"),
        ("Columns", f"{len(p.columns)}"),
        ("Exact repeats", "None" if p.duplicates.rows == 0 else f"{p.duplicates.rows:,} rows"),
    ]
    if k:
        facts.append(
            (
                "Key",
                f"{', '.join(k.columns)}: "
                + (
                    "unique, none missing"
                    if not (k.duplicates or k.nulls)
                    else f"{k.duplicates:,} repeat, {k.nulls:,} missing"
                ),
            )
        )
    facts += [("Issued", f"{p.created_at:%-d %b %Y, %H:%M} UTC"), ("Source size", _bytes(p.source.bytes))]
    facts_html = "".join(f"<div><dt>{a}</dt><dd>{E(b)}</dd></div>" for a, b in facts)
    sample_note = ""
    if p.sample.method != "full":
        sample_note = (
            f'<p class="note">Profile from {p.sample.rows_profiled:,} sampled rows. '
            "The fingerprint, row count and repeats cover every row.</p>"
        )
    return (
        _cover("Dataset passport", name, E(passport_lede(p)), fp, seal)
        + f'<section class="page" aria-label="Summary"><dl class="facts">{facts_html}</dl>'
        f'<p class="mrz data" aria-hidden="true">{_mrz("P", name, p.rows, len(p.columns), fp)}</p></section>'
        + f'<div class="head"><h2>Columns</h2><input id="filter" type="search" placeholder="Find a column" '
        f'aria-label="Find a column"></div>{sample_note}{_columns(p)}{_provenance(p)}'
    )


def _footer(values: bool) -> str:
    words = "This report holds aggregates only. It contains no rows" + (
        ", but it lists the most frequent values of some columns."
        if values
        else ", and category values appear only as tokens."
    )
    return f'<footer><span class="st skip">{icon("lock")}</span>{words}</footer>'


def passport_html(p: Passport) -> str:
    return _page(f"{p.name or 'Dataset'} passport", passport_fragment(p) + _footer(p.options.privacy == "values"))


# ---------------------------------------------------------------- comparison


def comparison_fragment(c: Comparison) -> str:
    r = c.rows
    pa, pb = c._base_passport, c._target_passport
    bname, tname = c.base.name or "before", c.target.name or "after"
    s1 = seal_svg(
        c.base.fingerprint,
        label=_seal_label(bname, c.base.rows, c.base.fingerprint),
        size=132,
        uid="sa",
        animate=False,
        title=f"Seal of {bname}",
    )
    s2 = seal_svg(
        c.target.fingerprint,
        label=_seal_label(tname, c.target.rows, c.target.fingerprint),
        size=168,
        uid="sb",
        title=f"Seal of {tname}",
    )
    seals = f'<div class="seals" style="opacity:1">{s1}<span class="arrow" aria-hidden="true">→</span>{s2}</div>'
    title = f"{tname} is the same as {bname}" if c.identical else f"What changed in {tname}"
    out = [
        _cover("Dataset comparison", title, E(comparison_lede(c)), c.target.fingerprint, seals).replace(
            '<header class="cover">', '<header class="cover cmp">'
        )
    ]
    ledger = [(f"{r.after:,}", f"rows, was {r.before:,}")]
    if r.added is not None:
        ledger += [(f"{r.added:,}", "added"), (f"{r.removed:,}", "removed")]
        if r.changed is not None:
            ledger.append((f"{r.changed:,}", "edited"))
    ledger.append((str(len(c.schema_changes)), "schema changes"))
    out.append(
        '<section class="page" aria-label="Summary"><dl class="ledger">'
        + "".join(f"<div><dt>{E(b)}</dt><dd>{E(a)}</dd></div>" for a, b in ledger)
        + f'</dl><p class="mrz data" aria-hidden="true">'
        f"{_mrz('V', tname, c.target.rows, len(pb.columns) if pb else 0, c.target.fingerprint)}</p></section>"
    )
    if c.schema_changes:
        items = []
        for s in c.schema_changes:
            lab = status("bad", "Can break readers") if s.breaking else status("ok", "Compatible")
            items.append(f'<div class="change">{lab}<span>{E(s.describe())}</span></div>')
        out.append(f'<h2>Schema</h2><div class="panel">{"".join(items)}</div>')
    if r.changed_by_column:
        items = []
        top = max(r.changed_by_column.values())
        for k, v in sorted(r.changed_by_column.items(), key=lambda kv: -kv[1]):
            items.append(
                f'<div class="change"><span class="name">{E(k)}</span><span>{v:,} rows '
                f'({v / max(r.before, 1):.1%})<span class="miss"><span class="bar"><i style="width:'
                f'{v / top * 100:.0f}%;background:var(--chart)"></i></span></span></span></div>'
            )
        out.append(
            f'<h2>Edited values</h2><p class="note">Rows matched on {E(", ".join(r.key))}.</p>'
            f'<div class="panel">{"".join(items)}</div>'
        )
    if c.drift:
        order = {"fail": 0, "warn": 1, "pass": 2, "skipped": 3}
        items = []
        for d in sorted(c.drift.values(), key=lambda d: (order[d.status], d.column)):
            chart = ""
            if pa and pb and d.column in pa.columns and d.column in pb.columns:
                qa, qb = _quantiles(pa.columns[d.column]), _quantiles(pb.columns[d.column])
                if qa and qb:
                    chart = distribution_svg(qb, qa, label=d.column)
            kind, words = DRIFT_WORDS[d.status]
            value = getattr(d, d.metric) if d.metric else None
            metric = {
                "psi": "PSI",
                "ks": "KS",
                "wasserstein_norm": "Wasserstein / IQR",
                "js": "Jensen–Shannon",
                "tvd": "Total variation",
            }.get(d.metric or "", d.metric or "")
            shown = "below 0.001" if isinstance(value, float) and 0 <= value < 0.001 else _n(value, 3)
            measure = E(d.note) if d.note else f"{E(metric)} {shown}"
            nulls = "" if abs(d.null_fraction_delta) < 0.0005 else f", missing {d.null_fraction_delta:+.1%}"
            items.append(
                f'<div class="change drift"><span class="name">{E(d.column)}<span class="typ">'
                f"{E(d.kind if d.kind != 'none' else '')}</span></span>{status(kind, words)}"
                f'<span class="note hide-sm">{measure}{nulls}</span><span class="hide-sm">{chart}</span></div>'
            )
        out.append(
            f'<h2>Distributions</h2><div class="panel">{"".join(items)}</div>'
            '<p class="legend"><span><i></i>now</span><span><i class="b"></i>before</span></p>'
        )
    notes = ([r.note] if r.note else []) + c.notes
    if notes:
        out.append("".join(f'<p class="note">{E(n)}</p>' for n in notes))
    return "".join(out)


def comparison_html(c: Comparison) -> str:
    return _page(f"{c.target.name or 'Dataset'} compared", comparison_fragment(c) + _footer(False))


# --------------------------------------------------------------------- check


def check_html(rep: CheckReport) -> str:
    order = ("fail", "error", "warn", "pass", "skipped")
    items = []
    for r in sorted(rep.results, key=lambda r: order.index(r.status)):
        kind, words = RESULT_WORDS[r.status]
        items.append(
            f'<div class="change">{status(kind, words)}<span><b>{E(r.label)}</b>'
            f'<span class="typ">{E(r.message)}</span></span></div>'
        )
    n_fail = rep.counts["fail"] + rep.counts["error"]
    if rep.status == "pass":
        title, lede = "Passed", f"All {rep.counts['pass']} checks passed."
    elif rep.status == "warn":
        title, lede = "Passed with warnings", f"{rep.counts['warn']} warning(s); nothing failed."
    else:
        title, lede = (
            f"{n_fail} check{'s' if n_fail != 1 else ''} failed",
            f"{n_fail} failed, {rep.counts['warn']} warned and {rep.counts['pass']} passed.",
        )
    name = rep.dataset or "dataset"
    seal = seal_svg(rep.fingerprint, label=_seal_label(name, rep.rows, rep.fingerprint), size=180, uid="ck")
    body = (
        _cover(f"Contract check · {name}", title, E(lede), rep.fingerprint, seal)
        + f'<h2>Results</h2><div class="panel">{"".join(items)}</div>'
    )
    return _page(f"{name} check", body + _footer(False))
