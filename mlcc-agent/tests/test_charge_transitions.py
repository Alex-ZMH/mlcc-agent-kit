"""Hand-calculated software fixtures, not material energies or qualifications."""
from copy import deepcopy

import pytest

from mlcc.charge_transitions import charge_transition_envelope
from mlcc.defect_thermodynamics import formation_energy_terms


def record(q, intercept):
    return formation_energy_terms(
        Edef=intercept, Ehost=0.0, deltaN={}, mu={}, q=q,
        vbm=None if q == 0 else 0.0, ef_grid=[-7.0],
        correction_terms={"other_eV": 0.0, "total_eV": 0.0,
                          "method": "hand-calculated software fixture only"},
    )


def envelope(records, interval):
    return charge_transition_envelope(
        records, interval,
        source_refs={key: f"software-test-fixture:{key}#/formation" for key in records},
    )


def by_id(result):
    return {item["record_id"]: item for item in result["records"]}


def test_original_terms_determine_intercepts_without_curve_fitting():
    # b+ = 7 - 2 - 0.5 + 0.25 = 4.75; b- = 8 - 2 + 0.5 + 0.25 = 6.75.
    # Their true transition is EF=1 and energy=5.75, absent from the sparse grids.
    records = {
        name: formation_energy_terms(
            Edef=energy, Ehost=3.0, deltaN={"O": -1}, mu={"O": -2.0},
            q=q, vbm=-0.5, ef_grid=[-7.0],
            correction_terms={"other_eV": 0.25, "total_eV": 0.25,
                              "method": "hand-calculated software fixture only"},
        )
        for name, energy, q in (("plus", 10.0, 1), ("minus", 11.0, -1))
    }
    original = deepcopy(records)
    sources = {name: f"original-records/{name}.json#/formation" for name in records}
    result = charge_transition_envelope(records, [0.0, 2.0], source_refs=sources)
    assert result["schema"] == "mlcc.charge-transitions.v1"
    assert result["ef_interval_eV"] == [0.0, 2.0]
    assert result["source_refs"] == sources
    assert by_id(result)["plus"]["intercept_eV"] == 4.75
    assert by_id(result)["minus"]["intercept_eV"] == 6.75
    assert by_id(result)["plus"]["source_ref"] == sources["plus"]
    assert len(result["transitions"]) == 1
    assert result["transitions"][0]["ef_eV"] == 1.0
    assert result["transitions"][0]["formation_energy_eV"] == 5.75
    assert result["transitions"][0]["left_charges"] == [1]
    assert result["transitions"][0]["right_charges"] == [-1]
    assert result["scientific_status"] == "mathematical_postprocess_unqualified"
    assert result["production_qualification"] is False
    assert records == original


def test_crossings_above_envelope_are_not_stable_transitions():
    # +1/0 cross at 2, 0/-1 at 0, but q=0 is always above min(EF, 2-EF).
    result = envelope({"plus": record(1, 0), "neutral": record(0, 2),
                       "minus": record(-1, 2)}, [0, 3])
    assert [(t["ef_eV"], t["left_charges"], t["right_charges"])
            for t in result["transitions"]] == [(1.0, [1], [-1])]
    assert [s["ef_interval_eV"] for s in result["stable_intervals"]] == [[0.0, 1.0], [1.0, 3.0]]
    assert [s["record_ids"] for s in result["stable_intervals"]] == [["plus"], ["minus"]]
    assert by_id(result)["neutral"]["stability"] == "unstable"
    assert by_id(result)["neutral"]["stability_interval_eV"] is None


def test_three_way_crossing_retains_point_only_state():
    # 2*EF, 1+EF, 2 coincide at 1; the middle line is never an open segment.
    result = envelope({"double": record(2, 0), "single": record(1, 1),
                       "neutral": record(0, 2)}, [0, 2])
    assert len(result["transitions"]) == 1
    transition = result["transitions"][0]
    assert transition["ef_eV"] == 1.0
    assert transition["degenerate_record_ids"] == ["double", "single", "neutral"]
    assert transition["degenerate_charges"] == [2, 1, 0]
    assert transition["left_record_ids"] == ["double"]
    assert transition["right_record_ids"] == ["neutral"]
    assert by_id(result)["single"]["stability"] == "point_only"
    assert by_id(result)["single"]["stability_interval_eV"] == [1.0, 1.0]


def test_parallel_higher_and_coincident_lines_remain_explicit():
    result = envelope({"plus_a": record(1, 0), "plus_b": record(1, 0),
                       "high_a": record(1, 0.5), "high_b": record(1, 0.5),
                       "minus": record(-1, 2)}, [0, 2])
    assert result["stable_intervals"][0]["record_ids"] == ["plus_a", "plus_b"]
    assert result["stable_intervals"][0]["charges"] == [1]
    assert by_id(result)["high_a"]["stability"] == "unstable"
    assert by_id(result)["high_b"]["stability"] == "unstable"
    group = result["same_charge_groups"][0]
    assert group["q"] == 1
    assert group["minimum_intercept_record_ids"] == ["plus_a", "plus_b"]
    assert group["higher_intercept_record_ids"] == ["high_a", "high_b"]
    assert [g["record_ids"] for g in result["coincident_line_groups"]] == [
        ["plus_a", "plus_b"], ["high_a", "high_b"]]
    assert result["transitions"][0]["degenerate_record_ids"] == ["plus_a", "plus_b", "minus"]


def test_endpoint_ties_are_not_interior_transitions():
    # 2*EF ties EF only at left endpoint; constant 2 ties EF at right endpoint.
    result = envelope({"left": record(2, 0), "middle": record(1, 0),
                       "right": record(0, 2)}, [0, 2])
    assert result["transitions"] == []
    assert result["stable_intervals"] == [
        {"ef_interval_eV": [0.0, 2.0], "record_ids": ["middle"], "charges": [1]}]
    assert result["boundaries"][0]["record_ids"] == ["left", "middle"]
    assert result["boundaries"][1]["record_ids"] == ["middle", "right"]
    assert by_id(result)["left"]["stability"] == "point_only"
    assert by_id(result)["right"]["stability"] == "point_only"


def test_single_neutral_and_external_crossing_use_explicit_interval():
    result = envelope({"neutral": record(0, 0)}, [-3, 1])
    assert result["stable_intervals"][0]["ef_interval_eV"] == [-3.0, 1.0]
    assert result["transitions"] == []
    with_external = envelope({"neutral": record(0, 0), "high": record(1, 10)}, [-3, 1])
    assert with_external["transitions"] == []
    assert by_id(with_external)["high"]["stability"] == "unstable"


def test_fully_coincident_records_stay_stable_across_the_whole_domain():
    records = {"copy_a": record(1, 2), "copy_b": record(1, 2)}
    result = envelope(records, [-1, 3])
    assert result["transitions"] == []
    assert result["stable_intervals"] == [
        {"ef_interval_eV": [-1.0, 3.0], "record_ids": ["copy_a", "copy_b"], "charges": [1]}]
    assert all(item["stability"] == "interval" for item in result["records"])
    with pytest.raises(TypeError):
        charge_transition_envelope(records, [-1, 3], {"copy_a": "a", "copy_b": "b"})


def test_small_but_positive_stability_interval_is_not_merged():
    width = 2.0 ** -40
    result = envelope({"plus": record(1, 0), "neutral": record(0, 1),
                       "minus": record(-1, 2 + width)}, [0, 2])
    assert [t["ef_eV"] for t in result["transitions"]] == [1.0, 1.0 + width]
    assert by_id(result)["neutral"]["stability"] == "interval"
    assert by_id(result)["neutral"]["stability_interval_eV"] == [1.0, 1.0 + width]


@pytest.mark.parametrize("interval", [[1, 1], [2, 0], [0, float("inf")]])
def test_rejects_invalid_explicit_interval(interval):
    with pytest.raises(ValueError):
        envelope({"neutral": record(0, 0)}, interval)


@pytest.mark.parametrize("field,value", [("q", 0.5), ("q", True),
                                        ("energy_difference_eV", float("nan")),
                                        ("schema", "other-schema")])
def test_rejects_non_affine_record_parameters(field, value):
    invalid = record(1, 0)
    invalid[field] = value
    with pytest.raises(ValueError):
        envelope({"invalid": invalid}, [0, 2])


def test_missing_correction_or_charged_vbm_is_not_inferred():
    missing_correction = record(1, 0)
    del missing_correction["correction"]["total_eV"]
    with pytest.raises((KeyError, ValueError)):
        envelope({"missing": missing_correction}, [0, 2])
    missing_vbm = record(1, 0)
    missing_vbm["vbm_eV"] = None
    with pytest.raises(ValueError):
        envelope({"missing": missing_vbm}, [0, 2])


def test_requires_records_and_matching_original_source_references():
    with pytest.raises(ValueError):
        charge_transition_envelope({}, [0, 2], source_refs={})
    with pytest.raises(ValueError):
        charge_transition_envelope({"neutral": record(0, 0)}, [0, 2], source_refs={"other": "source.json"})
