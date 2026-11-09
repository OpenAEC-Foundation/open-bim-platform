import logging
import math

import models
import pytest

from openbim_kern.clash import ClashCheck, ClashModel, ClashScene, box_overlap, run_checks
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
    # The duct crosses the wall at x 4.0 to 4.3: axis B (x 5) is nearer than A (x 0), axis 1 (y 0) nearer than 2 (y 10).
    assert hit.raster == "B-1"
    assert hit.ruimte == "Gang 1"
    assert hit.a.verdieping == hit.b.verdieping == "00 begane grond"


def test_a_part_of_an_assembly_gets_the_storey_of_the_assembly(context_round):
    # The members are not in the storey themselves; their assembly is.
    _, found = context_round
    hit = find(found, "Deel 1", "Deel 2")
    assert hit.a.verdieping == hit.b.verdieping == "00 begane grond"


BUCKET_REASONS = {
    "beoordelen": {None},
    "contact": {"contact"},
    "aangrenzend": {"vulling", "samenstel", "verbonden", "zelfde_systeem", "aansluiting"},
}


def test_every_clash_has_a_valid_bucket_and_reason(context_round):
    path, _ = context_round
    m = ClashModel(sleutel="m", versie="1", pad=path)
    both = run_checks(
        [ClashCheck(set_a=[m], set_b=[m], soort="hard"), ClashCheck(set_a=[m], set_b=[m], soort="dubbel")]
    )
    assert both
    for c in both:
        assert c.emmer_reden in BUCKET_REASONS[c.emmer], (c.a.naam, c.b.naam, c.emmer, c.emmer_reden)
        assert c.ernst in {"klein", "groot", "kritiek"}
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


def test_a_failing_context_question_is_logged_once_per_round(context_round, monkeypatch, caplog):
    path, found = context_round
    assert len(found) > 2  # the same question fails for every clash

    def familie(*_args, **_kwargs):
        raise RuntimeError("kapot")

    monkeypatch.setattr(ModelContext, "familie", familie)
    m = ClashModel(sleutel="m", versie="1", pad=path)
    with caplog.at_level(logging.WARNING):
        run_checks([ClashCheck(set_a=[m], set_b=[m], soort="hard")])
    logged = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(logged) == 1
    assert "familie" in logged[0].getMessage() and "kapot" in logged[0].getMessage()


@pytest.mark.parametrize("reader,question", [("_read_spaces", "ruimte"), ("_read_grid", "raster")])
def test_a_failing_reader_runs_once_and_gives_none(ifc_small, monkeypatch, caplog, reader, question):
    import ifcopenshell

    calls = []

    def boom(self):
        calls.append(1)
        raise RuntimeError("kapot")

    monkeypatch.setattr(ModelContext, reader, boom)
    context = ModelContext(ifcopenshell.open(str(ifc_small)), None)
    with caplog.at_level(logging.WARNING):
        results = [getattr(context, question)((0.0, 0.0, 0.0)) for _ in range(3)]
    assert results == [None, None, None]
    assert len(calls) == 1
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "kapot" in caplog.records[0].getMessage()


# (name, boxes as class, name, lowest and highest corner; tolerance; expected depth, bucket, severity). No depth: no
# clash. In the first rows the tree gives a longer ray than the overlap of the boxes; for box elements the real
# contact is that overlap, so the point has to lie in it.
WINDOW_IN_REVEAL = (("IfcWindow", (0.0, -0.05, 0.5), (3.002, 0.35, 2.0)), ("IfcWall", (3.0, 0.0, 0.0), (3.5, 0.3, 2.7)))
DUCT_15_MM_IN_BEAM = (
    ("IfcBeam", (0.0, 0.0, 0.0), (5.0, 1.0, 1.0)),
    ("IfcDuctSegment", (4.985, 0.25, -1.0), (9.0, 0.75, 4.0)),
)
BOXES = [
    ("long window 2 mm in a reveal", *WINDOW_IN_REVEAL, 0.0, 0.002, "contact", "klein"),
    (
        "window flush in a wall",
        ("IfcWindow", (1.0, 0.0, 0.9), (2.0, 0.1, 2.1)),
        ("IfcWall", (0.0, 0.0, 0.0), (5.0, 0.3, 2.7)),
        0.0,
        0.1,
        "beoordelen",
        "groot",
    ),
    (
        "duct 200 mm into a beam",
        ("IfcBeam", (0.0, 0.0, 0.0), (5.0, 1.0, 1.0)),
        ("IfcDuctSegment", (4.8, 0.25, -1.0), (9.0, 0.75, 4.0)),
        0.0,
        0.2,
        "beoordelen",
        "kritiek",
    ),
    ("duct 15 mm into a beam", *DUCT_15_MM_IN_BEAM, 0.0, 0.015, "beoordelen", "klein"),
    (
        "beam 30 mm into a column",
        ("IfcColumn", (0.0, 0.0, 0.0), (0.3, 0.3, 3.0)),
        ("IfcBeam", (0.27, -0.1, 2.5), (3.27, 0.4, 2.8)),
        0.0,
        0.03,
        "aangrenzend",
        "klein",
    ),
    (
        "duct straight through a wall",
        ("IfcWall", (0.0, 0.0, 0.0), (5.0, 0.2, 3.0)),
        ("IfcDuctSegment", (2.0, -0.5, 1.0), (2.3, 0.7, 1.3)),
        0.0,
        0.2,
        "beoordelen",
        "groot",
    ),
    (
        "duct 2 mm into a slab",
        ("IfcSlab", (0.0, 0.0, -0.2), (4.0, 4.0, 0.0)),
        ("IfcDuctSegment", (1.0, 1.0, -0.002), (3.0, 1.3, 0.298)),
        0.0,
        0.002,
        "contact",
        "klein",
    ),
    # A real passage through an element thinner than the contact depth counts as contact: the depth is the plate.
    (
        "duct straight through a 3 mm plate",
        ("IfcPlate", (0.0, 0.0, 0.0), (5.0, 0.003, 3.0)),
        ("IfcDuctSegment", (2.0, -0.5, 1.0), (2.3, 0.5, 1.3)),
        0.0,
        0.003,
        "contact",
        "klein",
    ),
    # The tree filters on its own ray, here 400 mm and 1 m: the depth has to meet the tolerance as well.
    ("long window 2 mm in a reveal, tolerance 50 mm", *WINDOW_IN_REVEAL, 0.05, None, None, None),
    ("duct 15 mm into a beam, tolerance 20 mm", *DUCT_15_MM_IN_BEAM, 0.02, None, None, None),
    ("duct 15 mm into a beam, tolerance 10 mm", *DUCT_15_MM_IN_BEAM, 0.01, 0.015, "beoordelen", "klein"),
    ("duct 15 mm into a beam, tolerance 15 mm", *DUCT_15_MM_IN_BEAM, 0.015, 0.015, "beoordelen", "klein"),
]


def distance_to_box(point, low, high):
    return math.dist(point, [min(max(v, lo), hi) for v, lo, hi in zip(point, low, high, strict=True)])


@pytest.mark.parametrize("name,one,other,tolerantie,depth,emmer,ernst", BOXES, ids=[b[0] for b in BOXES])
def test_a_hard_clash_is_as_deep_as_the_overlap_of_the_boxes(
    tmp_path, name, one, other, tolerantie, depth, emmer, ernst
):
    path = models.ifc_boxes(tmp_path / "boxes.ifc", [(one[0], "een", *one[1:]), (other[0], "ander", *other[1:])])
    m = ClashModel(sleutel="m", versie="1", pad=path)
    found = run_checks([ClashCheck(set_a=[m], set_b=[m], soort="hard", tolerantie=tolerantie)])
    if depth is None:
        assert found == []
        return
    (clash,) = found
    assert clash.afstand == pytest.approx(depth, abs=1e-3)
    assert (clash.emmer, clash.ernst) == (emmer, ernst)
    low = [max(p, q) for p, q in zip(one[1], other[1], strict=True)]
    high = [min(p, q) for p, q in zip(one[2], other[2], strict=True)]
    assert distance_to_box(clash.punt, low, high) <= 1e-3


# (name, model; expected depth, the box around the real contact, bucket, severity). Rotated and L-shaped elements: their
# boxes overlap over metres, while they only meet in a small piece. In the first the middle of that overlap lies 3.7 m
# from the contact, in the second 1.65 m and outside the wall.
SHAPES = [
    (
        "diagonal beam through a wall",
        models.ifc_diagonal_beam,
        0.2,
        ((0.57, 1.0, 1.0), (1.2, 1.2, 1.3)),
        "beoordelen",
        "groot",
    ),
    (
        "duct through an L-shaped wall",
        models.ifc_l_wall,
        0.2,
        ((0.5, 0.0, 1.0), (0.8, 0.2, 1.3)),
        "beoordelen",
        "groot",
    ),
]


@pytest.mark.parametrize("name,build,depth,contact,emmer,ernst", SHAPES, ids=[s[0] for s in SHAPES])
def test_the_point_of_a_hard_clash_stays_at_the_real_contact(tmp_path, name, build, depth, contact, emmer, ernst):
    path = build(tmp_path / "shape.ifc")
    m = ClashModel(sleutel="m", versie="1", pad=path)
    (clash,) = run_checks([ClashCheck(set_a=[m], set_b=[m], soort="hard")])
    assert clash.afstand == pytest.approx(depth, abs=1e-3)
    assert (clash.emmer, clash.ernst) == (emmer, ernst)
    assert distance_to_box(clash.punt, *contact) <= 0.01


def test_without_an_overlap_the_answer_of_the_tree_stays():
    scene = ClashScene([])
    scene.boxes = {"a": ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), "b": ((5.0, 5.0, 5.0), (6.0, 6.0, 6.0))}
    assert scene._penetration("a", "b", 0.3, (1.0, 2.0, 3.0)) == (0.3, (1.0, 2.0, 3.0))
    assert scene._penetration("a", "onbekend", 0.3, (1.0, 2.0, 3.0)) == (0.3, (1.0, 2.0, 3.0))


def test_a_point_outside_the_overlap_moves_into_it_per_axis():
    scene = ClashScene([])
    scene.boxes = {"a": ((0.0, 0.0, 0.0), (1.0, 0.1, 2.0)), "b": ((0.0, 0.0, 0.0), (1.0, 0.3, 1.0))}
    depth, point = scene._penetration("a", "b", 0.3, (0.5, 0.15, 1.5))
    assert depth == pytest.approx(0.1)
    assert point == pytest.approx((0.5, 0.1, 1.0))


def test_a_clearance_keeps_the_answer_of_the_tree(tmp_path):
    path = models.ifc_boxes(
        tmp_path / "boxes.ifc",
        [
            ("IfcWall", "een", (0.0, 0.0, 0.0), (5.0, 0.2, 3.0)),
            ("IfcDuctSegment", "ander", (1.0, 0.25, 1.0), (2.0, 1.0, 1.5)),
        ],
    )
    m = ClashModel(sleutel="m", versie="1", pad=path)
    (clash,) = run_checks([ClashCheck(set_a=[m], set_b=[m], soort="afstand", tolerantie=0.1)])
    assert clash.afstand == pytest.approx(0.05, abs=1e-3)
    assert clash.punt[1] == pytest.approx(0.225, abs=1e-3)


def test_the_overlap_of_two_boxes():
    a = ((0.0, 0.0, 0.0), (1.0, 2.0, 3.0))
    smallest, low, high = box_overlap(a, ((0.9, 1.0, -1.0), (5.0, 1.5, 5.0)))
    assert smallest == pytest.approx(0.1)
    assert low == pytest.approx((0.9, 1.0, 0.0))
    assert high == pytest.approx((1.0, 1.5, 3.0))
    # Boxes that just touch (also through rounding) have no depth; boxes further apart have no overlap at all.
    assert box_overlap(a, ((1.0, 0.0, 0.0), (2.0, 1.0, 1.0)))[0] == 0.0
    assert box_overlap(a, ((1.0001, 0.0, 0.0), (2.0, 1.0, 1.0)))[0] == 0.0
    assert box_overlap(a, ((1.5, 0.0, 0.0), (2.0, 1.0, 1.0))) is None


def arc_of(path):
    """The points of the curved axis C of `models.ifc_arc_grid`, in order."""
    import ifcopenshell

    u_axes, _ = ModelContext(ifcopenshell.open(str(path)), None)._read_grid()
    ((tag, segments),) = u_axes
    assert tag == "C"
    return [segments[0][0], *(end for _, end, _ in segments)]


QUARTER = [(10.0, 0.0), (7.0711, 7.0711), (0.0, 10.0)]


@pytest.mark.parametrize(
    "angle_unit,trims", [("DEGREE", (0.0, 90.0)), ("RADIAN", (0.0, math.pi / 2)), (None, (0.0, 90.0))]
)
def test_a_curved_grid_axis_follows_the_angle_unit_of_the_model(tmp_path, angle_unit, trims):
    # A model that declares no plane angle unit is read in degrees.
    points = arc_of(models.ifc_arc_grid(tmp_path / "boog.ifc", trims, angle_unit=angle_unit))
    assert [points[0], points[len(points) // 2], points[-1]] == [pytest.approx(p, abs=1e-3) for p in QUARTER]


def test_a_curved_grid_axis_against_the_sense_of_its_circle_runs_clockwise(tmp_path):
    # From 0 to 90 degrees the other way round: three quarters of the circle, through -135 degrees.
    points = arc_of(models.ifc_arc_grid(tmp_path / "boog.ifc", (0.0, 90.0), sense=False))
    middle = points[len(points) // 2]
    assert [points[0], middle, points[-1]] == [
        pytest.approx(p, abs=1e-3) for p in [(10.0, 0.0), (-7.0711, -7.0711), (0.0, 10.0)]
    ]
