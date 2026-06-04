"""
JITX-like declarative netlist layer for the Altium MCP server.

This module is intentionally free of any Altium / MCP dependency so it can be
unit-tested without Altium running. It turns a plain-text ``.netlist`` source
file into:

  * a structured :class:`Netlist`              (``parse_netlist``)
  * a flat list of expanded nets               (``Netlist.expand``)
  * validation errors against the live design  (``validate``)
  * a list of placement :class:`Action`        (``plan`` -- the auto-mix planner)
  * a review report                            (``diff``)

``main.py`` is the only place that talks to Altium: it builds a ``pin_index``
from the ``get_pin_nets`` read-back, asks this module to ``plan`` / ``diff``,
and then dispatches each :class:`Action` to the existing primitive commands
(``place_net_labels``, ``connect_pins``, ``place_power_ports``,
``place_bus_labels``, ``place_diff_pair_labels``, ``create_net_class``).

Grammar (see ``netlist_rules.txt`` for the user-facing version)::

    # comment
    power GND 3V3 5V                       # nets to realize as power ports
    net   3V3 (U1.VCC, U2.VDD, C1.1)       # a net is an unordered set of pins
    net   UART (U1.PA9 -> U2.RX)           # '->' is a cosmetic separator == ','
    bus   DATA[0:7] (U1.D{i}, U3.D{i})     # {i} expands over the inclusive range
    diff  USB0 (U1.DP/DM, J1.DP/DN)        # NAME_P / NAME_N differential pair
    class HighSpeed { USB0_P USB0_N }      # net class -> pushed to the PCB
    net   I2C (U1.SCL, U2.SCL) style=label # per-net style override
    # capability / require:
    bundle i2c { scl, sda }
    component U1 supports i2c { scl=SCL, sda=SDA }
    component U2 supports i2c { scl=PB6, sda=PB7 }
    require U1.i2c <-> U2.i2c
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "PinRef", "Net", "Bus", "DiffPair", "Netlist", "Action",
    "NetlistError", "parse_netlist", "build_pin_index", "PinIndex",
    "validate", "plan", "diff", "format_netlist", "netlist_from_pin_nets",
    "is_power_net",
]

# Valid per-net style overrides.
STYLES = ("auto", "label", "wire", "power", "bus", "diff")

# Names that should be realized as power ports even without an explicit `power`
# declaration. Matches GND/VCC families and voltage-style names like 3V3, +12V.
_POWER_NAMES = {
    "GND", "GROUND", "VSS", "VSSA", "AGND", "DGND", "PGND", "EGND", "SGND",
    "VCC", "VDD", "VDDA", "VEE", "VBAT", "VBUS", "VIN", "VOUT", "VREF",
}
_POWER_VOLTAGE_RE = re.compile(r"^[+-]?\d+V\d*$", re.IGNORECASE)  # 5V 3V3 +12V -12V 1V8


def is_power_net(name: str, declared_power: Optional[set] = None) -> bool:
    """True if *name* should be realized as a power port under auto-mix."""
    n = name.strip()
    if declared_power and n in declared_power:
        return True
    u = n.upper()
    if u in _POWER_NAMES:
        return True
    return bool(_POWER_VOLTAGE_RE.match(n))


class NetlistError(ValueError):
    """Raised on a parse/semantic error. Carries a 1-based line number."""

    def __init__(self, message: str, line_no: Optional[int] = None):
        self.line_no = line_no
        if line_no is not None:
            message = f"line {line_no}: {message}"
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Structured model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PinRef:
    """A reference to one pin: ``designator.pin`` where pin is a name or number."""
    designator: str
    pin: str

    def __str__(self) -> str:
        return f"{self.designator}.{self.pin}"


@dataclass
class Net:
    name: str
    pins: List[PinRef]
    style: str = "auto"           # one of STYLES
    line_no: Optional[int] = None


@dataclass
class Bus:
    name: str
    low: int
    high: int
    templates: List[Tuple[str, str]]  # (designator, pin_template e.g. "D{i}")
    style: str = "auto"
    line_no: Optional[int] = None

    def bits(self) -> range:
        step = 1 if self.high >= self.low else -1
        return range(self.low, self.high + step, step)

    def expand(self) -> List[Net]:
        """One Net per bit: DATA0..DATA7 with the matching pins."""
        nets: List[Net] = []
        for i in self.bits():
            pins = [PinRef(des, tmpl.replace("{i}", str(i)))
                    for des, tmpl in self.templates]
            nets.append(Net(f"{self.name}{i}", pins, style="bus", line_no=self.line_no))
        return nets

    def assignment_templates(self) -> List[str]:
        """Templates for the existing place_bus_labels primitive."""
        return [f"{des}|{tmpl}|{self.name}{{i}}" for des, tmpl in self.templates]


@dataclass
class DiffPair:
    name: str
    # one (positive, negative) PinRef tuple per participating component
    pairs: List[Tuple[PinRef, PinRef]]
    line_no: Optional[int] = None

    @property
    def pos_net(self) -> str:
        return f"{self.name}_P"

    @property
    def neg_net(self) -> str:
        return f"{self.name}_N"

    def expand(self) -> List[Net]:
        pos = Net(self.pos_net, [p for p, _ in self.pairs], style="label", line_no=self.line_no)
        neg = Net(self.neg_net, [n for _, n in self.pairs], style="label", line_no=self.line_no)
        return [pos, neg]


@dataclass
class Netlist:
    nets: List[Net] = field(default_factory=list)
    buses: List[Bus] = field(default_factory=list)
    diffs: List[DiffPair] = field(default_factory=list)
    power_nets: set = field(default_factory=set)
    classes: Dict[str, List[str]] = field(default_factory=dict)
    # capability model
    bundles: Dict[str, List[str]] = field(default_factory=dict)            # name -> signals
    supports: Dict[Tuple[str, str], Dict[str, str]] = field(default_factory=dict)  # (des,bundle)->{sig:pin}
    requires: List[Tuple[str, str, str, str]] = field(default_factory=list)        # (desA,bundle,desB,bundle)

    def expand(self) -> List[Net]:
        """Flatten everything (nets, buses, diffs, requires) into plain nets."""
        out: List[Net] = list(self.nets)
        for bus in self.buses:
            out.extend(bus.expand())
        for d in self.diffs:
            out.extend(d.expand())
        out.extend(self._expand_requires())
        return out

    def _expand_requires(self) -> List[Net]:
        nets: List[Net] = []
        for desA, bunA, desB, bunB in self.requires:
            sigsA = self.bundles.get(bunA)
            mapA = self.supports.get((desA, bunA))
            mapB = self.supports.get((desB, bunB))
            if sigsA is None or mapA is None or mapB is None:
                continue  # validation reports the missing piece
            for sig in sigsA:
                if sig in mapA and sig in mapB:
                    name = f"{desA}_{desB}_{bunA}_{sig}"
                    nets.append(Net(
                        name,
                        [PinRef(desA, mapA[sig]), PinRef(desB, mapB[sig])],
                        line_no=None,
                    ))
        return nets


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
_BUS_HEADER_RE = re.compile(r"^(?P<name>[^\s(\[]+)\s*\[\s*(?P<lo>\d+)\s*:\s*(?P<hi>\d+)\s*\]$")


def _strip_comment(line: str) -> str:
    idx = line.find("#")
    return line if idx < 0 else line[:idx]


def _split_paren(line: str, line_no: int) -> Tuple[str, str, str]:
    """Split ``head (body) tail`` -> (head, body, tail). Raises if no parens."""
    lp = line.find("(")
    rp = line.rfind(")")
    if lp < 0 or rp < 0 or rp < lp:
        raise NetlistError("expected a '( ... )' pin list", line_no)
    return line[:lp].strip(), line[lp + 1:rp].strip(), line[rp + 1:].strip()


def _split_items(body: str) -> List[str]:
    """Split a pin list on ',' or '->' (the arrow is a cosmetic separator)."""
    body = body.replace("->", ",")
    return [tok.strip() for tok in body.split(",") if tok.strip()]


def _split_words(body: str) -> List[str]:
    """Split a ``{ ... }`` body on commas and/or whitespace, dropping empties."""
    return [w for w in re.split(r"[,\s]+", body.strip()) if w]


def _parse_pinref(token: str, line_no: int) -> PinRef:
    if "." not in token:
        raise NetlistError(f"pin '{token}' must be DESIGNATOR.PIN", line_no)
    des, pin = token.split(".", 1)
    des, pin = des.strip(), pin.strip()
    if not des or not pin:
        raise NetlistError(f"malformed pin reference '{token}'", line_no)
    return PinRef(des, pin)


def _parse_style(tail: str, line_no: int) -> str:
    tail = tail.strip()
    if not tail:
        return "auto"
    m = re.match(r"style\s*=\s*(\w+)$", tail)
    if not m:
        raise NetlistError(f"unexpected trailing text '{tail}'", line_no)
    style = m.group(1).lower()
    if style not in STYLES:
        raise NetlistError(f"unknown style '{style}' (one of {', '.join(STYLES)})", line_no)
    return style


def parse_netlist(text: str) -> Netlist:
    """Parse ``.netlist`` source text into a :class:`Netlist`. Raises NetlistError."""
    nl = Netlist()
    seen_net_names: Dict[str, int] = {}

    for raw_no, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        keyword, _, rest = line.partition(" ")
        keyword = keyword.lower()
        rest = rest.strip()

        if keyword == "power":
            for name in rest.split():
                nl.power_nets.add(name)

        elif keyword == "net":
            head, body, tail = _split_paren(rest, raw_no)
            name = head.strip()
            if not name:
                raise NetlistError("net is missing a name", raw_no)
            if name in seen_net_names:
                raise NetlistError(
                    f"net '{name}' already defined on line {seen_net_names[name]}", raw_no)
            seen_net_names[name] = raw_no
            pins = [_parse_pinref(t, raw_no) for t in _split_items(body)]
            if not pins:
                raise NetlistError(f"net '{name}' has no pins", raw_no)
            nl.nets.append(Net(name, pins, _parse_style(tail, raw_no), raw_no))

        elif keyword == "bus":
            head, body, tail = _split_paren(rest, raw_no)
            m = _BUS_HEADER_RE.match(head.strip())
            if not m:
                raise NetlistError("bus header must be NAME[lo:hi]", raw_no)
            templates: List[Tuple[str, str]] = []
            for tok in _split_items(body):
                if "." not in tok:
                    raise NetlistError(f"bus pin '{tok}' must be DESIGNATOR.PIN", raw_no)
                des, tmpl = tok.split(".", 1)
                if "{i}" not in tmpl:
                    raise NetlistError(f"bus pin '{tok}' must contain '{{i}}'", raw_no)
                templates.append((des.strip(), tmpl.strip()))
            if not templates:
                raise NetlistError("bus has no pins", raw_no)
            nl.buses.append(Bus(m.group("name"), int(m.group("lo")),
                                int(m.group("hi")), templates,
                                _parse_style(tail, raw_no), raw_no))

        elif keyword == "diff":
            head, body, tail = _split_paren(rest, raw_no)
            name = head.strip()
            if not name:
                raise NetlistError("diff is missing a name", raw_no)
            pairs: List[Tuple[PinRef, PinRef]] = []
            for tok in _split_items(body):
                if "." not in tok or "/" not in tok:
                    raise NetlistError(
                        f"diff pin '{tok}' must be DESIGNATOR.POS/NEG", raw_no)
                des, pins = tok.split(".", 1)
                pos, neg = pins.split("/", 1)
                des = des.strip()
                pairs.append((PinRef(des, pos.strip()), PinRef(des, neg.strip())))
            if not pairs:
                raise NetlistError("diff has no pins", raw_no)
            nl.diffs.append(DiffPair(name, pairs, raw_no))

        elif keyword == "class":
            m = re.match(r"(?P<name>\S+)\s*\{(?P<body>[^}]*)\}$", rest)
            if not m:
                raise NetlistError("class must be NAME { net net ... }", raw_no)
            nl.classes[m.group("name")] = _split_words(m.group("body"))

        elif keyword == "bundle":
            m = re.match(r"(?P<name>\S+)\s*\{(?P<body>[^}]*)\}$", rest)
            if not m:
                raise NetlistError("bundle must be NAME { signal signal ... }", raw_no)
            nl.bundles[m.group("name")] = _split_words(m.group("body"))

        elif keyword == "component":
            m = re.match(
                r"(?P<des>\S+)\s+supports\s+(?P<bundle>\S+)\s*\{(?P<body>[^}]*)\}$", rest)
            if not m:
                raise NetlistError(
                    "expected: component DES supports BUNDLE { sig=PIN, ... }", raw_no)
            mapping: Dict[str, str] = {}
            for assign in re.split(r"[,\s]+", m.group("body").strip()):
                if not assign:
                    continue
                if "=" not in assign:
                    raise NetlistError(f"capability '{assign}' must be sig=PIN", raw_no)
                sig, pin = assign.split("=", 1)
                mapping[sig.strip()] = pin.strip()
            nl.supports[(m.group("des"), m.group("bundle"))] = mapping

        elif keyword == "require":
            m = re.match(
                r"(?P<a>\S+)\.(?P<ba>\S+)\s*<->\s*(?P<b>\S+)\.(?P<bb>\S+)$", rest)
            if not m:
                raise NetlistError(
                    "expected: require DESA.BUNDLE <-> DESB.BUNDLE", raw_no)
            nl.requires.append(
                (m.group("a"), m.group("ba"), m.group("b"), m.group("bb")))

        else:
            raise NetlistError(f"unknown statement '{keyword}'", raw_no)

    return nl


# --------------------------------------------------------------------------- #
# Pin index (built from the get_pin_nets read-back)
# --------------------------------------------------------------------------- #
@dataclass
class _PinEntry:
    designator: str
    pin_name: str
    pin_number: str
    sheet: str
    net: str


class PinIndex:
    """Lookup of live schematic pins, built from get_pin_nets output."""

    def __init__(self, entries: List[_PinEntry]):
        self._by_des: Dict[str, List[_PinEntry]] = {}
        for e in entries:
            self._by_des.setdefault(e.designator, []).append(e)

    def has_designator(self, des: str) -> bool:
        return des in self._by_des

    def resolve(self, ref: PinRef) -> Optional[_PinEntry]:
        """Find the entry for *ref*, matching pin number first then name."""
        for e in self._by_des.get(ref.designator, []):
            if e.pin_number == ref.pin:
                return e
        low = ref.pin.lower()
        for e in self._by_des.get(ref.designator, []):
            if e.pin_name.lower() == low:
                return e
        return None

    def all_entries(self) -> List[_PinEntry]:
        return [e for lst in self._by_des.values() for e in lst]


def build_pin_index(pin_nets_data: List[dict]) -> PinIndex:
    """Build a :class:`PinIndex` from get_pin_nets JSON objects."""
    entries = [
        _PinEntry(
            designator=str(d.get("designator", "")),
            pin_name=str(d.get("pin_name", "")),
            pin_number=str(d.get("pin_number", "")),
            sheet=str(d.get("sheet", "")),
            net=str(d.get("net", "")),
        )
        for d in pin_nets_data
    ]
    return PinIndex(entries)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate(nl: Netlist, index: PinIndex) -> List[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    errors: List[str] = []

    # capability model references
    for desA, bunA, desB, bunB in nl.requires:
        for des, bun in ((desA, bunA), (desB, bunB)):
            if bun not in nl.bundles:
                errors.append(f"require references unknown bundle '{bun}'")
            if (des, bun) not in nl.supports:
                errors.append(f"'{des}' does not declare 'supports {bun}'")

    for net in nl.expand():
        for ref in net.pins:
            if not index.has_designator(ref.designator):
                errors.append(
                    f"net '{net.name}': component '{ref.designator}' not found "
                    f"on any schematic sheet")
            elif index.resolve(ref) is None:
                errors.append(
                    f"net '{net.name}': '{ref.designator}' has no pin "
                    f"'{ref.pin}' (checked pin name and number)")

    # net classes must reference declared nets
    known = {n.name for n in nl.expand()}
    for cls, members in nl.classes.items():
        for m in members:
            if m not in known:
                errors.append(f"class '{cls}' references undeclared net '{m}'")

    return errors


# --------------------------------------------------------------------------- #
# Planner (auto-mix)
# --------------------------------------------------------------------------- #
@dataclass
class Action:
    """One unit of work for main.py to dispatch to a primitive command."""
    method: str          # net_labels | power_ports | wire | bus_labels | diff_pairs | net_class
    payload: dict
    net: str = ""        # the originating net name (for reporting)


def _assignment(ref: PinRef, net_name: str) -> str:
    return f"{ref.designator}|{ref.pin}|{net_name}"


def plan(nl: Netlist, index: PinIndex) -> List[Action]:
    """Produce the auto-mix placement plan. Pure: does not touch Altium."""
    actions: List[Action] = []

    # Buses -> bus labels via the existing place_bus_labels primitive.
    for bus in nl.buses:
        actions.append(Action(
            "bus_labels",
            {
                "bus_name": bus.name,
                "bit_range": [bus.low, bus.high],
                "assignments": bus.assignment_templates(),
            },
            net=f"{bus.name}[{bus.low}:{bus.high}]",
        ))

    # Differential pairs -> one place_diff_pair_labels call per component pair.
    for d in nl.diffs:
        actions.append(Action(
            "diff_pairs",
            {
                "pairs": [
                    {
                        "pos_assignment": _assignment(pos, d.pos_net),
                        "neg_assignment": _assignment(neg, d.neg_net),
                    }
                    for pos, neg in d.pairs
                ],
            },
            net=d.name,
        ))

    # Plain nets (includes require-expanded nets) -> auto-mix.
    plain = list(nl.nets) + nl._expand_requires()
    for net in plain:
        style = net.style
        power = is_power_net(net.name, nl.power_nets)

        if style == "auto":
            chosen = "power" if power else None
            if chosen is None and len(net.pins) == 2 and _same_sheet(net.pins, index):
                chosen = "wire"
            if chosen is None:
                chosen = "label"
        else:
            chosen = style

        if chosen == "power":
            actions.append(Action(
                "power_ports",
                {"assignments": [_assignment(p, net.name) for p in net.pins]},
                net=net.name))
        elif chosen == "wire" and len(net.pins) == 2:
            a, b = net.pins
            actions.append(Action(
                "wire",
                {
                    "assignments": [f"{a.designator}|{a.pin}|{b.designator}|{b.pin}"],
                    # fall back to labels if the wire can't be drawn at runtime
                    "fallback_assignments": [_assignment(p, net.name) for p in net.pins],
                    "fallback_net": net.name,
                },
                net=net.name))
        else:  # label (also the fallback for a wire net that is not 2-pin)
            actions.append(Action(
                "net_labels",
                {"assignments": [_assignment(p, net.name) for p in net.pins]},
                net=net.name))

    # Net classes -> create_net_class (operates on the PCB).
    for cls, members in nl.classes.items():
        actions.append(Action(
            "net_class",
            {"class_name": cls, "net_names": list(members)},
            net=cls))

    return actions


def _same_sheet(pins: List[PinRef], index: PinIndex) -> bool:
    sheets = set()
    for ref in pins:
        e = index.resolve(ref)
        if e is None:
            return False
        sheets.add(e.sheet)
    return len(sheets) == 1


# --------------------------------------------------------------------------- #
# Diff / review
# --------------------------------------------------------------------------- #
@dataclass
class NetReport:
    name: str
    status: str          # OK | MISSING | CONFLICT
    actual_net: str = ""
    missing_pins: List[str] = field(default_factory=list)
    conflict_pins: List[str] = field(default_factory=list)  # "U1.5 on 'OTHER'"
    extra_pins: List[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class DiffReport:
    nets: List[NetReport]

    @property
    def ok(self) -> bool:
        return all(n.status == "OK" for n in self.nets)

    def to_dict(self) -> dict:
        counts = {"OK": 0, "MISSING": 0, "CONFLICT": 0}
        for n in self.nets:
            counts[n.status] = counts.get(n.status, 0) + 1
        return {
            "ok": self.ok,
            "summary": counts,
            "nets": [
                {k: v for k, v in {
                    "name": n.name,
                    "status": n.status,
                    "actual_net": n.actual_net,
                    "missing_pins": n.missing_pins,
                    "conflict_pins": n.conflict_pins,
                    "extra_pins": n.extra_pins,
                    "detail": n.detail,
                }.items() if v not in ("", [], None)}
                for n in self.nets
            ],
        }

    def to_text(self) -> str:
        lines = []
        for n in self.nets:
            if n.status == "OK":
                lines.append(f"OK    {n.name:<16} -> {n.actual_net}")
            elif n.status == "MISSING":
                lines.append(f"MISS  {n.name:<16} {n.detail}")
            else:
                lines.append(f"CONFL {n.name:<16} {n.detail}")
        c = self.to_dict()["summary"]
        lines.append(f"\n{c['OK']} ok, {c['MISSING']} missing, {c['CONFLICT']} conflict")
        return "\n".join(lines)


def diff(nl: Netlist, pin_nets_data: List[dict]) -> DiffReport:
    """Compare intended connectivity against the actual schematic read-back.

    Membership-based (name-agnostic) so wired nets with Altium-assigned names
    still verify: all of a net's pins must land on the *same* actual net.
    """
    index = build_pin_index(pin_nets_data)
    expanded = nl.expand()

    # actual_net -> set of "DES.NUM" keys, to compute EXTRA and merges
    actual_members: Dict[str, set] = {}
    for e in index.all_entries():
        if e.net:
            actual_members.setdefault(e.net, set()).add(f"{e.designator}.{e.pin_number}")

    actual_net_to_intent: Dict[str, set] = {}
    reports: List[NetReport] = []

    for net in expanded:
        rep = NetReport(name=net.name, status="OK")
        nets_seen: Dict[str, int] = {}
        intent_keys = set()

        for ref in net.pins:
            e = index.resolve(ref)
            if e is None:
                rep.missing_pins.append(f"{ref} (pin not found)")
                continue
            intent_keys.add(f"{e.designator}.{e.pin_number}")
            if not e.net:
                rep.missing_pins.append(str(ref))
            else:
                nets_seen[e.net] = nets_seen.get(e.net, 0) + 1
                actual_net_to_intent.setdefault(e.net, set()).add(net.name)

        if not nets_seen:
            rep.status = "MISSING"
            rep.detail = "no pin is connected to any net"
        elif len(nets_seen) > 1:
            rep.status = "CONFLICT"
            rep.detail = ("pins split across nets " +
                          ", ".join(sorted(nets_seen)))
        else:
            actual = next(iter(nets_seen))
            rep.actual_net = actual
            if rep.missing_pins:
                rep.status = "MISSING"
                rep.detail = (f"on '{actual}', but missing: " +
                              ", ".join(rep.missing_pins))
            else:
                # EXTRA pins present on the same actual net but not in intent
                extra = actual_members.get(actual, set()) - intent_keys
                rep.extra_pins = sorted(extra)

        reports.append(rep)

    # Detect merges: one actual net claimed by >1 intent net.
    for actual, intents in actual_net_to_intent.items():
        if len(intents) > 1:
            for rep in reports:
                if rep.name in intents and rep.status == "OK":
                    rep.status = "CONFLICT"
                    rep.detail = (f"merged with {', '.join(sorted(intents - {rep.name}))} "
                                  f"on actual net '{actual}'")

    return reports_to_report(reports)


def reports_to_report(reports: List[NetReport]) -> DiffReport:
    return DiffReport(nets=reports)


# --------------------------------------------------------------------------- #
# Export (reverse: actual connectivity -> .netlist text)
# --------------------------------------------------------------------------- #
def netlist_from_pin_nets(pin_nets_data: List[dict]) -> str:
    """Build a .netlist source string from a get_pin_nets read-back."""
    by_net: Dict[str, List[str]] = {}
    for d in pin_nets_data:
        net = str(d.get("net", ""))
        if not net:
            continue
        des = str(d.get("designator", ""))
        num = str(d.get("pin_number", ""))
        by_net.setdefault(net, []).append(f"{des}.{num}")

    power = sorted(n for n in by_net if is_power_net(n))
    signal = sorted(n for n in by_net if n not in set(power))

    lines: List[str] = ["# Exported from the current Altium schematic", ""]
    if power:
        lines.append("power " + " ".join(power))
        lines.append("")
    for name in power + signal:
        pins = ", ".join(sorted(by_net[name]))
        lines.append(f"net {name} ({pins})")
    return "\n".join(lines) + "\n"


def format_netlist(nets: List[Net], power_nets: Optional[set] = None) -> str:
    """Render a list of Nets back to .netlist text (used by tests/tools)."""
    lines: List[str] = []
    if power_nets:
        lines.append("power " + " ".join(sorted(power_nets)))
        lines.append("")
    for net in nets:
        pins = ", ".join(str(p) for p in net.pins)
        suffix = "" if net.style == "auto" else f" style={net.style}"
        lines.append(f"net {net.name} ({pins}){suffix}")
    return "\n".join(lines) + "\n"
