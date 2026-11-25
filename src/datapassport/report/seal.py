"""The Seal: a guilloché rosette drawn from a fingerprint.

Passports and banknotes carry guilloché, fine interlaced line patterns that are
easy to recognise and hard to reproduce. DataPassport draws one per dataset
version, with every parameter derived from the content fingerprint. The same
data always draws the same seal, and a single changed value draws a visibly
different one, so two reports can be told apart at a glance.

The seal is decoration plus a recognition aid. The fingerprint text stays the
authority; never compare seals instead of fingerprints.
"""

from __future__ import annotations

import html
import math

TAU = 2 * math.pi


def _params(fingerprint: str) -> list[int]:
    hexstr = (fingerprint or "0" * 64).ljust(64, "0")[:64]
    return [int(hexstr[i : i + 2], 16) for i in range(0, 64, 2)]


def _path(points: list[tuple[float, float]]) -> str:
    it = iter(points)
    x0, y0 = next(it)
    return f"M{x0:.1f} {y0:.1f}" + "".join(f"L{x:.1f} {y:.1f}" for x, y in it) + "Z"


def _band(cx: float, cy: float, r0: float, amp: float, petals: int, curves: int, twist: float, steps: int = 150) -> str:
    """Interlaced sinusoidal rings: r(θ) = r0 + amp·sin(petals·θ + phase)."""
    paths = []
    for j in range(curves):
        phase = j * TAU / curves
        pts = []
        for s in range(steps):
            t = s * TAU / steps
            r = r0 + amp * math.sin(petals * t + phase) + amp * 0.35 * math.sin((petals * 2 + 1) * t - phase * twist)
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
        paths.append(_path(pts))
    return "".join(paths)


def _rosette(cx: float, cy: float, big: float, small: float, d: float, steps: int = 720) -> str:
    """Hypotrochoid: the classic spirograph rosette at the centre."""
    k = (big - small) / small
    turns = int(small / math.gcd(int(big), int(small)))
    pts = []
    total = steps * max(1, min(turns, 8))
    for s in range(total + 1):
        t = s * TAU * max(1, min(turns, 8)) / total
        x = (big - small) * math.cos(t) + d * math.cos(k * t)
        y = (big - small) * math.sin(t) - d * math.sin(k * t)
        pts.append((cx + x, cy + y))
    return _path(pts)


def seal_svg(
    fingerprint: str,
    *,
    label: str = "",
    size: int = 220,
    uid: str = "s",
    animate: bool = True,
    title: str | None = None,
) -> str:
    """Return an inline SVG seal for ``fingerprint``.

    Colours come from CSS custom properties (``--seal-ink``, ``--seal-soft``)
    so the seal follows the light or dark theme.
    """
    p = _params(fingerprint)
    c = 120.0
    outer = _band(c, c, 84, 6 + p[0] % 5, 7 + p[1] % 9, 14 + p[2] % 8, 1 + p[3] % 3)
    middle = _band(c, c, 58, 5 + p[4] % 5, 5 + p[5] % 7, 12 + p[6] % 6, 1 + p[7] % 3)
    big = 30 + p[8] % 8
    small = 5 + p[9] % 9
    if big % small == 0:
        small += 1
    centre = _rosette(c, c, big, small, 8 + p[10] % 12)
    ticks = "".join(
        f'<line x1="{c + 103 * math.cos(i * TAU / 120):.1f}" y1="{c + 103 * math.sin(i * TAU / 120):.1f}" '
        f'x2="{c + (106 if i % 5 else 108) * math.cos(i * TAU / 120):.1f}" '
        f'y2="{c + (106 if i % 5 else 108) * math.sin(i * TAU / 120):.1f}"/>'
        for i in range(120)
    )
    rot = (p[11] / 255) * 360
    text = html.escape(label)
    anim = " dp-seal-anim" if animate else ""
    t = html.escape(title or f"Seal drawn from fingerprint {fingerprint[:12]}")
    return (
        f'<svg class="dp-seal{anim}" viewBox="0 0 240 240" width="{size}" height="{size}" role="img" '
        f'aria-label="{t}"><title>{t}</title>'
        f'<defs><path id="{uid}-ring" d="M{c} {c}m-94 0a94 94 0 1 1 188 0a94 94 0 1 1 -188 0"/>'
        f'<radialGradient id="{uid}-g"><stop offset="0" stop-color="var(--seal-glow)" stop-opacity=".9"/>'
        f'<stop offset="1" stop-color="var(--seal-glow)" stop-opacity="0"/></radialGradient></defs>'
        f'<circle cx="{c}" cy="{c}" r="116" fill="url(#{uid}-g)" class="dp-seal-glow"/>'
        f'<g class="dp-seal-lines"><g transform="rotate({rot:.1f} {c} {c})" fill="none" stroke="var(--seal-ink)">'
        f'<circle cx="{c}" cy="{c}" r="111" stroke-width=".9"/><circle cx="{c}" cy="{c}" r="100" stroke-width=".5"/>'
        f'<g stroke-width=".7" class="dp-seal-ticks">{ticks}</g>'
        f'<path class="dp-ring dp-r1" d="{outer}" stroke-width=".95" stroke-opacity=".95"/>'
        f'<path class="dp-ring dp-r2" d="{middle}" stroke-width=".9" stroke-opacity=".85"/>'
        f'<path class="dp-ring dp-r3" d="{centre}" stroke-width="1"/>'
        f'<circle cx="{c}" cy="{c}" r="3" fill="var(--seal-ink)" stroke="none"/></g></g>'
        f'<text class="dp-seal-text" font-size="9.2" fill="var(--seal-ink)">'
        f'<textPath href="#{uid}-ring" startOffset="50%" text-anchor="middle">{text}</textPath></text>'
        f"</svg>"
    )


SEAL_CSS = """
.dp-seal{display:block;overflow:visible}
.dp-seal-text{font-family:var(--font-display);letter-spacing:0}
.dp-seal-glow{opacity:var(--seal-glow-opacity,0)}
.dp-seal-lines{transform-box:view-box;transform-origin:120px 120px}
@media (prefers-reduced-motion:no-preference){
.dp-seal-anim .dp-seal-lines{animation:dp-stamp 1.25s cubic-bezier(.3,1.45,.45,1) backwards}
.dp-seal-anim .dp-ring{animation:dp-ink .9s ease-out backwards}
.dp-seal-anim .dp-r2{animation-delay:.12s}.dp-seal-anim .dp-r3{animation-delay:.24s}
@keyframes dp-stamp{0%{transform:rotate(-24deg) scale(1.12);opacity:0}55%{opacity:1}
78%{transform:rotate(2.5deg) scale(.992)}100%{transform:none}}
@keyframes dp-ink{from{opacity:0}to{opacity:1}}
}
"""
