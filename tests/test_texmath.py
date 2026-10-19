"""Titles with TeX read as one line of Unicode text: the registry's titles and an adversarial
corpus (#13 compares these outputs with pylatexenc's)."""

import json
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import papers  # noqa: E402
from texmath import tex_text  # noqa: E402

CASES = [
    (r"Marton's Conjecture in $\mathbb{F}_2^n$", "Marton's Conjecture in 𝔽₂ⁿ"),
    (r"Sobolev embeddings in $L^2(\mathbb{R}^n)$", "Sobolev embeddings in L²(ℝⁿ)"),
    (r"Erd\H{o}s on $L^p$", "Erdős on Lᵖ"),
    (r"Sch\"onhage and G\'{e}rard: Poincar\'e duality", "Schönhage and Gérard: Poincaré duality"),
    (r"The $\mathcal{O}$-module $\mathfrak{g}$ and $\mathfrak{sl}_2$", "The 𝒪-module 𝔤 and 𝔰𝔩₂"),
    (r"Bounds for $\zeta(1/2+it)$ and $\Gamma$-functions", "Bounds for ζ(1/2+it) and Γ-functions"),
    (r"Gaps of size $\frac{1}{2}\log p$ between primes", "Gaps of size 1/2 log p between primes"),
    (r"$(\log x)^2$ and $2\sin x$", "(log x)² and 2 sin x"),
    (r"$x^{ab}$ and $x^{\star}$ and $x_{n+1}$", "xᵃᵇ and x^⋆ and xₙ₊₁"),
    (r"Weights $w_{ij}$ and $q^{-1/2}$ exponents", "Weights wᵢⱼ and q^(-1/2) exponents"),
    (r"Sets in $\mathbb{R}^3$ -- a survey", "Sets in ℝ³ – a survey"),
    (r"An $\ell^p$ bound for $\sum_{n\le x} \mu(n)$", "An ℓᵖ bound for ∑_(n≤ x) μ(n)"),
    (r"Mixed: the \emph{Kakeya} problem in $\mathbb{F}_q^n$ \& beyond",
     "Mixed: the Kakeya problem in 𝔽_qⁿ & beyond"),
    # What has no Unicode form stays readable rather than disappearing.
    (r"Unsupported \foo{bar} and $\weird x$", r"Unsupported \foo{bar} and weird x"),
    (r"Escapes: 50\% of $\{x\}$ with \$5", "Escapes: 50% of {x} with $5"),
    (r"Price \$5, set $x$ and \$6", "Price $5, set x and $6"),
    (r"$\$5$ and \# and a\_b", "$5 and # and a_b"),
    (r"$\left\langle f, g \right\rangle$ inner products", "⟨ f, g ⟩ inner products"),
    (r"Inline \(\alpha \to \beta\) and display $$E = mc^2$$", "Inline α → β and display E = mc²"),
    (r"Accents: na\"ive caf\'e, \c{c}a, \v{S}tefan, \~nandu", "Accents: naïve café, ça, Štefan, ñandu"),
    (r"$\mathrm{SL}_2(\mathbb{Z})$ and $\operatorname{Gal}(\bar{\mathbb{Q}}/\mathbb{Q})$",
     "SL₂(ℤ) and Gal(ℚ̅/ℚ)"),
    (r"$\vec{v}$, $\vec v$, $\hat{f}$, $\widehat{fg}$, $\overline{AB}$, $\tilde{\mu}$",
     "vec(v), vec(v), f̂, widehat(fg), A̅B̅, μ̃"),
    (r"$p$-adic $\mathbb{Z}_p$ and $\epsilon$ vs $\varepsilon$", "p-adic ℤₚ and ϵ vs ε"),
    (r"Nested $2^{2^{n}}$ and $e^{i\pi}$", "Nested 2^(2ⁿ) and e^(iπ)"),
]


@pytest.mark.parametrize("tex, text", CASES)
def test_tex_titles_read_as_unicode(tex, text):
    assert tex_text(tex) == text
    assert unicodedata.is_normalized("NFC", tex_text(tex))
    assert "\n" not in tex_text(tex)


def test_registry_titles_are_unchanged_when_they_have_no_tex():
    for p in papers.load(ROOT / "registry"):
        if "$" not in p["title"] and "\\" not in p["title"]:
            assert tex_text(p["title"]) == p["title"]


def test_a_tex_title_is_text_in_the_page_metadata_and_escaped(tmp_path):
    entry = {"id": "arxiv:2601.01234", "title": r"Bounds $a<b$ \& $\mathbb{R}^n$ <script>",
             "authors": ["A. Author"], "listing": "arxiv",
             "links": {"arxiv": "https://arxiv.org/abs/2601.01234"}, "formalisations": []}
    page = papers.paper_page(entry)
    assert "<title>Bounds a&lt;b &amp; ℝⁿ &lt;script&gt; — MachineChecked</title>" in page
    assert '<h1>Bounds a&lt;b &amp; ℝⁿ &lt;script&gt;</h1>' in page
    ld = json.loads(page.split('<script type="application/ld+json">')[1].split("</script>")[0])
    assert ld["name"] == "Bounds a<b & ℝⁿ <script>"
    assert "<script>" not in page.split("<body>")[1]
    assert papers.index_page([entry]).count("Bounds a&lt;b &amp; ℝⁿ") == 1
