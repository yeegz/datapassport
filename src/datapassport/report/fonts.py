"""Bundled, subset fonts (SIL Open Font License; licences in this folder).

- Young Serif: display. An engraved, banknote-like serif for the passport voice.
- Public Sans: text. The US government's typeface for forms and official
  documents, which suits a passport. Plain zeros and clear figures for data-heavy pages.
- Spline Sans Mono: raw data only (fingerprints, hashes, the machine-readable line).

Fonts are embedded as base64 so reports work offline and make no network requests.
"""

from __future__ import annotations

import base64
from functools import cache
from importlib import resources

FACES = [
    ("DP Young Serif", "young-serif.woff2", "400"),
    ("DP Public Sans", "public-sans.woff2", "100 900"),
    ("DP Spline Mono", "spline-sans-mono.woff2", "300 700"),
]


@cache
def font_css() -> str:
    out = []
    for family, file, weight in FACES:
        data = resources.files("datapassport.report").joinpath("fonts", file).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        out.append(
            f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{b64}) format('woff2');"
            f"font-weight:{weight};font-display:swap}}"
        )
    return "".join(out)
