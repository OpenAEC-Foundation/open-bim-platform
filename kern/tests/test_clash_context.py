import models
import pytest

from openbim_kern.clash import ClashCheck, ClashModel, run_checks
from openbim_kern.clash_context import ModelContext, classify


@pytest.mark.parametrize(
    "soort,afstand,relatie,systeem,fa,fb,emmer,reden,ernst",
    [
        ("hard", 0.30, "vulling", False, "afwerking", "constructie", "aangrenzend", "vulling", "klein"),
        ("hard", 0.30, "samenstel", False, "constructie", "constructie", "aangrenzend", "samenstel", "klein"),
        ("hard", 0.30, "verbonden", False, "constructie", "constructie", "aangrenzend", "verbonden", "klein"),
        ("hard", 0.03, None, True, "installaties", "installaties", "aangrenzend", "zelfde_systeem", "klein"),
        ("hard", 0.06, None, True, "installaties", "installaties", "beoordelen", None, "groot"),
        ("hard", 0.03, None, False, "constructie", "constructie", "aangrenzend", "aansluiting", "klein"),
        ("hard", 0.002, None, False, "afwerking", "installaties", "contact", "contact", "klein"),
        ("hard", 0.20, None, False, "constructie", "installaties", "beoordelen", None, "kritiek"),
        ("hard", 0.20, None, False, "afwerking", "installaties", "beoordelen", None, "groot"),
        ("hard", 0.01, None, False, "afwerking", "installaties", "beoordelen", None, "klein"),
        ("afstand", 0.03, None, False, "afwerking", "installaties", "beoordelen", None, "klein"),
        ("dubbel", 0.20, "verbonden", False, "constructie", "constructie", "beoordelen", None, "groot"),
    ],
)
def test_classify(soort, afstand, relatie, systeem, fa, fb, emmer, reden, ernst):
    r = classify(soort, afstand, relatie, systeem, fa, fb, None)
    assert (r.emmer, r.emmer_reden, r.ernst) == (emmer, reden, ernst)


def test_fixed_severity_only_for_the_review_bucket():
    assert classify("hard", 0.20, None, False, "afwerking", "installaties", "klein").ernst == "klein"
    assert classify("hard", 0.002, None, False, "afwerking", "installaties", "kritiek").ernst == "klein"


def test_category_is_sorted():
    r = classify("hard", 0.2, None, False, "installaties", "constructie", None)
    assert r.categorie == "constructie × installaties"


@pytest.fixture(scope="module")
def context_round(tmp_path_factory):
    path = models.ifc_clash_context(tmp_path_factory.mktemp("ctx") / "context.ifc")
    m = ClashModel(sleutel="m", versie="1", pad=path)
    return path, run_checks([ClashCheck(set_a=[m], set_b=[m], soort="hard")])


def find(found, name_a, name_b):
    (hit,) = [c for c in found if {c.a.naam, c.b.naam} == {name_a, name_b}]
    return hit


def test_every_rule_is_reached_on_the_test_model(context_round):
    _, found = context_round
    reasons = {
        ("Deur", "Dragende wand"): "vulling",
        ("Deel 1", "Deel 2"): "samenstel",
        ("Wand 1", "Wand 2"): "verbonden",
        ("Leiding 1", "Leiding 2"): "zelfde_systeem",
        ("Kolom", "Ligger"): "aansluiting",
        ("Kanaal bij vloer", "Vloer"): "contact",
    }
    for (a, b), reason in reasons.items():
        hit = find(found, a, b)
        assert hit.emmer_reden == reason, (a, b)
        assert hit.emmer in {"aangrenzend", "contact"}
        assert hit.ernst == "klein"


def test_the_duct_through_the_bearing_wall_is_to_be_reviewed(context_round):
    _, found = context_round
    hit = find(found, "Kanaal", "Dragende wand")
    assert (hit.emmer, hit.emmer_reden, hit.ernst) == ("beoordelen", None, "kritiek")
    assert hit.categorie == "constructie × installaties"
    assert hit.raster
    assert hit.ruimte == "Gang 1"
    assert hit.a.verdieping == hit.b.verdieping


def test_buckets_add_up_to_the_total(context_round):
    path, found = context_round
    m = ClashModel(sleutel="m", versie="1", pad=path)
    both = run_checks(
        [ClashCheck(set_a=[m], set_b=[m], soort="hard"), ClashCheck(set_a=[m], set_b=[m], soort="dubbel")]
    )
    counts = {}
    for c in both:
        counts[c.emmer] = counts.get(c.emmer, 0) + 1
    assert sum(counts.values()) == len(both)
    dubbel = [c for c in both if c.soort == "dubbel"]
    assert dubbel and all(c.emmer == "beoordelen" and c.ernst == "groot" for c in dubbel)


def test_no_grid_or_space_gives_empty_fields(ifc_small):
    m = ClashModel(sleutel="s", versie="1", pad=ifc_small, klassen=["IfcDuctSegment"])
    w = ClashModel(sleutel="s", versie="1", pad=ifc_small, klassen=["IfcWall"])
    found = run_checks([ClashCheck(set_a=[m], set_b=[w], soort="hard")])
    assert found and all(c.raster is None and c.ruimte is None for c in found)


def test_a_failing_context_never_fails_the_round(context_round, monkeypatch):
    path, found = context_round

    def boom(*_args, **_kwargs):
        raise RuntimeError("kapot")

    for name in ("raster", "ruimte", "relatie", "zelfde_systeem", "familie", "naam", "verdieping"):
        monkeypatch.setattr(ModelContext, name, boom)
    m = ClashModel(sleutel="m", versie="1", pad=path)
    again = run_checks([ClashCheck(set_a=[m], set_b=[m], soort="hard")])
    assert len(again) == len(found)
    assert all(c.raster is None and c.ruimte is None for c in again)
