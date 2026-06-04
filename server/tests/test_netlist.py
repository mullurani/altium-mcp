"""Unit tests for the pure-Python netlist layer (no Altium required).

Run with:  pytest server/tests/test_netlist.py
       or:  python server/tests/test_netlist.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import netlist as nm  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def pin(des, num, name, sheet="A.SchDoc", net=""):
    return {"designator": des, "pin_number": num, "pin_name": name,
            "sheet": sheet, "net": net}


def sample_index_data():
    """A small 2-sheet design with U1, U2, C1, U3, J1."""
    return [
        pin("U1", "1", "VCC"), pin("U1", "2", "GND"),
        pin("U1", "9", "PA9"), pin("U1", "5", "PA5"),
        pin("U1", "20", "USB_DP"), pin("U1", "21", "USB_DM"),
        pin("U1", "30", "D0"), pin("U1", "31", "D1"),
        pin("U2", "1", "VDD", sheet="B.SchDoc"), pin("U2", "2", "VSS", sheet="B.SchDoc"),
        pin("U2", "8", "RX", sheet="B.SchDoc"), pin("U2", "7", "SCK", sheet="B.SchDoc"),
        pin("C1", "1", "1"), pin("C1", "2", "2"),
        pin("U3", "7", "SCK", sheet="B.SchDoc"),
        pin("U3", "30", "D0", sheet="B.SchDoc"), pin("U3", "31", "D1", sheet="B.SchDoc"),
        pin("J1", "1", "DP"), pin("J1", "2", "DN"),
    ]


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def test_parse_basic_net():
    nl = nm.parse_netlist("net 3V3 (U1.VCC, U2.VDD, C1.1)")
    assert len(nl.nets) == 1
    n = nl.nets[0]
    assert n.name == "3V3"
    assert [str(p) for p in n.pins] == ["U1.VCC", "U2.VDD", "C1.1"]
    assert n.style == "auto"


def test_parse_arrow_separator_and_comments():
    nl = nm.parse_netlist("# header\nnet UART (U1.PA9 -> U2.RX)  # inline\n")
    assert [str(p) for p in nl.nets[0].pins] == ["U1.PA9", "U2.RX"]


def test_parse_power_and_style():
    nl = nm.parse_netlist("power GND 3V3\nnet I2C (U1.PA5, U2.SCK) style=label")
    assert nl.power_nets == {"GND", "3V3"}
    assert nl.nets[0].style == "label"


def test_parse_bus_expansion():
    nl = nm.parse_netlist("bus DATA[0:3] (U1.D{i}, U3.D{i})")
    nets = nl.buses[0].expand()
    assert [n.name for n in nets] == ["DATA0", "DATA1", "DATA2", "DATA3"]
    assert [str(p) for p in nets[0].pins] == ["U1.D0", "U3.D0"]
    assert nl.buses[0].assignment_templates() == ["U1|D{i}|DATA{i}", "U3|D{i}|DATA{i}"]


def test_parse_diff():
    nl = nm.parse_netlist("diff USB0 (U1.USB_DP/USB_DM, J1.DP/DN)")
    d = nl.diffs[0]
    assert d.pos_net == "USB0_P" and d.neg_net == "USB0_N"
    pos, neg = d.expand()
    assert [str(p) for p in pos.pins] == ["U1.USB_DP", "J1.DP"]
    assert [str(p) for p in neg.pins] == ["U1.USB_DM", "J1.DN"]


def test_parse_errors():
    for bad in ["net (U1.1)", "net X U1.1", "net X (U1)",
                "bus X (U1.D{i})", "frobnicate Y", "net A (U1.1)\nnet A (U2.2)"]:
        try:
            nm.parse_netlist(bad)
            assert False, f"expected NetlistError for: {bad!r}"
        except nm.NetlistError:
            pass


def test_parse_capability_model():
    src = (
        "bundle i2c { scl, sda }\n"
        "component U1 supports i2c { scl=PA5, sda=PA6 }\n"
        "component U2 supports i2c { scl=SCK, sda=RX }\n"
        "require U1.i2c <-> U2.i2c\n"
    )
    nl = nm.parse_netlist(src)
    assert nl.bundles["i2c"] == ["scl", "sda"]
    assert nl.supports[("U1", "i2c")] == {"scl": "PA5", "sda": "PA6"}
    assert nl.requires == [("U1", "i2c", "U2", "i2c")]
    expanded = nl._expand_requires()
    assert {n.name for n in expanded} == {"U1_U2_i2c_scl", "U1_U2_i2c_sda"}


# --------------------------------------------------------------------------- #
# power detection
# --------------------------------------------------------------------------- #
def test_is_power_net():
    for name in ["GND", "VCC", "3V3", "5V", "+12V", "-12V", "1V8", "VDDA"]:
        assert nm.is_power_net(name), name
    for name in ["UART_TX", "SPI_CLK", "DATA0", "USB0_P"]:
        assert not nm.is_power_net(name), name


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_validate_ok():
    nl = nm.parse_netlist("net 3V3 (U1.VCC, C1.1)\nnet UART (U1.PA9, U2.RX)")
    idx = nm.build_pin_index(sample_index_data())
    assert nm.validate(nl, idx) == []


def test_validate_unknown_designator_and_pin():
    nl = nm.parse_netlist("net X (U9.1, U1.NOPE)")
    idx = nm.build_pin_index(sample_index_data())
    errs = nm.validate(nl, idx)
    assert any("U9" in e and "not found" in e for e in errs)
    assert any("NOPE" in e for e in errs)


def test_validate_class_unknown_net():
    nl = nm.parse_netlist("net A (U1.VCC, C1.1)\nclass P { A B }")
    idx = nm.build_pin_index(sample_index_data())
    errs = nm.validate(nl, idx)
    assert any("undeclared net 'B'" in e for e in errs)


# --------------------------------------------------------------------------- #
# planner (auto-mix)
# --------------------------------------------------------------------------- #
def methods(actions):
    return {a.net: a.method for a in actions}


def test_plan_auto_mix():
    src = (
        "power GND 3V3\n"
        "net GND (U1.GND, U2.VSS, C1.2)\n"     # power port (3 pins)
        "net 3V3 (U1.VCC, C1.1)\n"             # power port (declared)
        "net UART (U1.PA9, C1.1)\n"            # 2 pins, same sheet -> wire
        "net SPI (U1.PA5, U2.SCK, U3.SCK)\n"   # 3 pins -> label
        "net XSHEET (U1.PA9, U2.RX)\n"         # 2 pins, different sheet -> label
        "net FORCED (U1.PA9, C1.1) style=label\n"
        "bus DATA[0:1] (U1.D{i}, U3.D{i})\n"
        "diff USB0 (U1.USB_DP/USB_DM, J1.DP/DN)\n"
        "class HS { SPI }\n"
    )
    nl = nm.parse_netlist(src)
    idx = nm.build_pin_index(sample_index_data())
    m = methods(nm.plan(nl, idx))
    assert m["GND"] == "power_ports"
    assert m["3V3"] == "power_ports"
    assert m["UART"] == "wire"
    assert m["SPI"] == "net_labels"
    assert m["XSHEET"] == "net_labels"
    assert m["FORCED"] == "net_labels"
    assert m["DATA[0:1]"] == "bus_labels"
    assert m["USB0"] == "diff_pairs"
    assert m["HS"] == "net_class"


def test_plan_wire_has_fallback():
    nl = nm.parse_netlist("net UART (U1.PA9, C1.1)")
    idx = nm.build_pin_index(sample_index_data())
    wire = [a for a in nm.plan(nl, idx) if a.method == "wire"][0]
    assert wire.payload["assignments"] == ["U1|PA9|C1|1"]
    assert wire.payload["fallback_assignments"] == ["U1|PA9|UART", "C1|1|UART"]


# --------------------------------------------------------------------------- #
# diff / review
# --------------------------------------------------------------------------- #
def test_diff_ok_missing_conflict_extra():
    nl = nm.parse_netlist(
        "net 3V3 (U1.VCC, C1.1)\n"
        "net GND (U1.GND, C1.2)\n"
        "net SIG (U1.PA9, U2.RX)\n"
    )
    data = sample_index_data()
    actual = {(d["designator"], d["pin_number"]): d for d in data}
    # 3V3 fully connected, plus an EXTRA pin on the same net
    actual[("U1", "1")]["net"] = "3V3"
    actual[("C1", "1")]["net"] = "3V3"
    actual[("U1", "5")]["net"] = "3V3"       # extra pin not in intent
    # GND: one pin connected, one missing
    actual[("U1", "2")]["net"] = "GND"
    # SIG: pins on two different nets -> conflict
    actual[("U1", "9")]["net"] = "NETA"
    actual[("U2", "8")]["net"] = "NETB"

    rep = nm.diff(nl, list(actual.values()))
    by = {n.name: n for n in rep.nets}
    assert by["3V3"].status == "OK"
    assert by["3V3"].actual_net == "3V3"
    assert "U1.5" in by["3V3"].extra_pins
    assert by["GND"].status == "MISSING"
    assert by["SIG"].status == "CONFLICT"
    assert not rep.ok


def test_diff_merge_conflict():
    nl = nm.parse_netlist("net A (U1.VCC)\nnet B (C1.1)")
    data = sample_index_data()
    actual = {(d["designator"], d["pin_number"]): d for d in data}
    actual[("U1", "1")]["net"] = "MERGED"
    actual[("C1", "1")]["net"] = "MERGED"
    rep = nm.diff(nl, list(actual.values()))
    assert all(n.status == "CONFLICT" for n in rep.nets)


# --------------------------------------------------------------------------- #
# export round-trip
# --------------------------------------------------------------------------- #
def test_export_round_trip():
    data = sample_index_data()
    data[0]["net"] = "3V3"      # U1.1
    data[12]["net"] = "3V3"     # C1.1
    data[1]["net"] = "GND"      # U1.2
    text = nm.netlist_from_pin_nets(data)
    nl = nm.parse_netlist(text)
    names = {n.name for n in nl.nets}
    assert {"3V3", "GND"} <= names
    assert "GND" in nl.power_nets and "3V3" in nl.power_nets


# --------------------------------------------------------------------------- #
# manual runner
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
