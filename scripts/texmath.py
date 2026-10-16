"""TeX in a paper's title, as plain Unicode text.

arXiv titles often carry a little TeX (`$\\mathbb{F}_2^n$`, `$L^p$`, `Erd\\H{o}s`). The static pages
show titles where no TeX renderer runs (page titles, search results, the papers list), so the
common notation is turned into its Unicode characters: blackboard, calligraphic and fraktur
letters, Greek, the usual relations and operators, and sub- and superscripts where Unicode has
them. What has no Unicode form is kept readably (`x^(ab)`), never dropped.
"""

from __future__ import annotations

import re
import unicodedata

BB = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ"))
BB.update(dict(zip("0123456789", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡")))
CAL = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵"))
FRAK = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                "𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝔖𝔗𝔘𝔙𝔚𝔛𝔜ℨ𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷"))
SUP = dict(zip("0123456789+-=()niabcdefghjklmoprstuvwxyzABDEGHIJKLMNOPRTUVW",
               "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ"))
SUB = dict(zip("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"))
SYM = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "infty": "∞", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "times": "×", "cdot": "·", "cdots": "⋯", "ldots": "…", "dots": "…", "to": "→",
    "rightarrow": "→", "leftarrow": "←", "mapsto": "↦", "in": "∈", "notin": "∉",
    "subset": "⊂", "subseteq": "⊆", "cup": "∪", "cap": "∩", "ell": "ℓ", "pm": "±", "mp": "∓",
    "sim": "∼", "simeq": "≃", "approx": "≈", "cong": "≅", "equiv": "≡", "partial": "∂",
    "nabla": "∇", "sqrt": "√", "sum": "∑", "prod": "∏", "int": "∫", "oplus": "⊕",
    "otimes": "⊗", "circ": "∘", "forall": "∀", "exists": "∃", "emptyset": "∅", "hbar": "ℏ",
    "star": "⋆", "ast": "∗", "prime": "′", "wedge": "∧", "vee": "∨", "neg": "¬", "langle": "⟨", "rangle": "⟩", "|": "‖", "aleph": "ℵ",
    "{": "{", "}": "}", ",": " ", ";": " ", ":": " ", "!": "", " ": " ", "%": "%", "&": "&",
    "log": "log", "exp": "exp", "sin": "sin", "cos": "cos", "lim": "lim", "max": "max",
    "min": "min", "sup": "sup", "inf": "inf", "det": "det", "dim": "dim", "deg": "deg",
}
ACCENT = {"'": "\u0301", "`": "\u0300", '"': "\u0308", "^": "\u0302", "~": "\u0303",
          "H": "\u030b", "c": "\u0327", "v": "\u030c", "=": "\u0304", "u": "\u0306"}
FONTS = {"mathbb": BB, "Bbb": BB, "mathcal": CAL, "mathfrak": FRAK}
PLAIN = ("mathrm", "text", "textrm", "mathit", "mathbf", "textbf", "textit", "emph",
         "operatorname", "mathsf", "boldsymbol", "bm", "mathbold")


def _group(s: str, i: int) -> tuple[str, int]:
    """The argument at `s[i]`: a braced group or one character; and the index after it."""
    if i < len(s) and s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            if depth == 0:
                return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    if i < len(s) and s[i] == "\\":
        m = re.match(r"\\([A-Za-z]+|.)", s[i:])
        return m.group(0), i + len(m.group(0))
    return (s[i], i + 1) if i < len(s) else ("", i)


def _script(text: str, table: dict, mark: str) -> str:
    t = _math(text)
    if t and all(ch in table for ch in t):
        return "".join(table[ch] for ch in t)
    return mark + (t if len(t) == 1 else f"({t})")


def _math(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", s[i:])
            name, i = m.group(1), i + len(m.group(0))
            if name in FONTS:
                arg, i = _group(s, i)
                out.append("".join(FONTS[name].get(c, c) for c in _math(arg)))
            elif name in PLAIN:
                arg, i = _group(s, i)
                out.append(_math(arg))
            elif name in ("left", "right", "big", "Big", "bigl", "bigr", "Bigl", "Bigr"):
                continue
            elif name == "frac":
                a, i = _group(s, i)
                b, i = _group(s, i)
                out.append(f"{_math(a)}/{_math(b)}")
            else:
                out.append(SYM.get(name, name))
        elif ch in "^_":
            arg, i = _group(s, i + 1)
            out.append(_script(arg, SUP if ch == "^" else SUB, ch))
        elif ch in "{}":
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def tex_text(s: str) -> str:
    """A title with its TeX turned into Unicode text."""
    if "\\" not in s and "$" not in s:
        return s
    # Accents outside mathematics: \"o, \'{e}, \H{o}, …
    def accent(m):
        base = m.group(2) or m.group(3) or ""
        return unicodedata.normalize("NFC", base + ACCENT[m.group(1)]) if base else ""
    s = re.sub(r"\\([\'`\"^~=]|[Hcvu](?=[{\s]))\s*(?:\{(\w?)\}|(\w))", accent, s)
    parts = re.split(r"(\$\$?[^$]*\$\$?|\\\(.*?\\\))", s)
    out = []
    for p in parts:
        if p.startswith("$") or p.startswith("\\("):
            out.append(_math(p.strip("$")[2:-2] if p.startswith("\\(") else p.strip("$")))
        else:
            out.append(re.sub(r"\\(textbf|textit|emph|textrm)\{([^{}]*)\}", r"\2", p)
                       .replace("--", "–").replace("~", " ").replace("\\&", "&"))
    return re.sub(r"\s+", " ", "".join(out)).strip()
