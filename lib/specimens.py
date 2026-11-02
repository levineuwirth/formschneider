"""What the curation pages set an initial in: an opening paragraph from
levineuwirth.org for each letter, and the routes as the pages name them;
and the pages' shared styles (bench.css) put into a template."""

from pathlib import Path as File

# Opening paragraphs from the site's essays, one per letter, so an initial
# is judged where it would stand.
TEXT = {
    "A": ("essays/branch-based-local-capture-in-tree-balls",
          "An induced tree-ball does not control shortest paths between arbitrary pairs of its "
          "vertices: a competing path may leave the ball and re-enter. The required radius depends "
          "on the endpoint depths and on the length of their path inside the tree-ball."),
    "F": ("essays/ball-occupation-under-coarse-projections",
          "For degree zero or one, use a singleton cloud, serving as the external port in the "
          "degree-one case. Each round replaces every vertex according to its current degree, "
          "including vertices of degree two or three. For degree reduction, stop when the entire "
          "graph is subcubic."),
    "I": ("essays/asymmetric-forgetting",
          "I have deliberately chosen not to describe what a concept-first curriculum would look "
          "like. This is a separate piece of work that is owed its own diligent treatment, and I "
          "refuse to attempt to distill and collapse it into the closing of this one."),
    "O": ("essays/crawler_chronicles",
          "Only aggregate results and sanitized publication records are public. Raw access logs, "
          "addresses, individual user-agent strings and request sequences remained on the VPS. A "
          "user-agent cohort is a traffic classification, not a verified person or organization."),
    "S": ("essays/verified-inference",
          "Streaming solves a memory problem by creating a regeneration problem. The model and its "
          "auxiliaries are revisited across proof stages. At small context lengths, loading and "
          "converting the weights can dominate even when little token computation is required."),
    "W": ("essays/asymmetric-forgetting",
          "Where do I land amidst all of this, and why do I care? I offer my own retention audit of "
          "sorts not as proof of the mechanism, but as a demonstration that it is at least "
          "observable in lived form."),
}

ROUTES = [
    {"key": "whole", "title": "Whole initials", "short": "whole initials",
     "note": "Letter and ornament both drawn by the model."},
    {"key": "ornament", "title": "Ornament only", "short": "ornament-only initials",
     "note": "Spectral SemiBold's capital kept; the model drew the rest."},
]


def page(template: str, **fill: str) -> str:
    """A page template with the bench's styles and each __KEY__ filled."""
    here = File(__file__).resolve().parent
    out = (here / template).read_text().replace("__BENCH_CSS__", (here / "bench.css").read_text())
    for k, v in fill.items():
        out = out.replace(f"__{k}__", v)
    return out
