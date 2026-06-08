"""
Screenshot-based visual rules for schematic layout quality (best-effort).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("build.visual")

_rule4_moved: set[str] = set()


@dataclass
class Correction:
    command: str
    params: dict[str, Any]


@dataclass
class Violation:
    rule_name: str
    issue: str
    affected: list[str] = field(default_factory=list)


@dataclass
class VisualRule:
    name: str
    prompt: str
    correction_fn: Callable[[list[str]], list[Correction]]


RULE_1_PROMPT = """
Look at this Altium schematic screenshot. Are there visible component symbols
(rectangular boxes with pins)? Answer pass=false if the image is mostly blank white.
"""

RULE_2_PROMPT = """
Look at this Altium schematic screenshot. Do any component symbols overlap or touch?
Answer pass=false if any two component bodies overlap. List designators in 'affected'.
"""

RULE_3_PROMPT = """
Are all component designator labels (U1, R1, etc.) readable and not hidden inside bodies?
"""

RULE_4_PROMPT = """
Is there clear white space separating field-side components (left) from MCU-side (center)?
"""

RULE_5_PROMPT = """
Are power port symbols oriented correctly (VCC up, GND down)?
"""

RULE_6_PROMPT = """
Are net labels like IN1, IN2, RELAY1_DRV visible as text near the MCU?
"""

RULE_7_PROMPT = """
Are any components clipped at the edges of the image?
"""


def _correction_overlap(affected: list[str]) -> list[Correction]:
    out = []
    for des in affected:
        out.append(Correction("move_component", {"designator": des, "dx_mils": 400, "dy_mils": 0}))
    return out


def _correction_designator(affected: list[str]) -> list[Correction]:
    return [
        Correction("move_component", {"designator": des, "dx_mils": 0, "dy_mils": 200})
        for des in affected
    ]


def _correction_isolation(affected: list[str]) -> list[Correction]:
    global _rule4_moved
    out = []
    for des in affected:
        if des in _rule4_moved:
            logger.info(
                "Rule 4: %s already corrected this run — skipping (Rule 7 conflict guard)",
                des,
            )
            continue
        _rule4_moved.add(des)
        out.append(
            Correction("move_component", {"designator": des, "dx_mils": -600, "dy_mils": 0})
        )
    return out


def _correction_power(affected: list[str]) -> list[Correction]:
    return [
        Correction("rotate_component", {"designator": des, "angle_degrees": 90})
        for des in affected
    ]


def _correction_labels(affected: list[str]) -> list[Correction]:
    return [
        Correction("move_component", {"designator": des, "dx_mils": 100, "dy_mils": 0})
        for des in affected
    ]


def _correction_edge(affected: list[str]) -> list[Correction]:
    return [
        Correction("move_component", {"designator": des, "dx_mils": 1000, "dy_mils": 0})
        for des in affected
    ]


def get_visual_rules() -> list[VisualRule]:
    return [
        VisualRule("rule1_canvas", RULE_1_PROMPT, lambda a: []),
        VisualRule("rule2_overlap", RULE_2_PROMPT, _correction_overlap),
        VisualRule("rule3_designator", RULE_3_PROMPT, _correction_designator),
        VisualRule("rule4_isolation", RULE_4_PROMPT, _correction_isolation),
        VisualRule("rule5_power", RULE_5_PROMPT, _correction_power),
        VisualRule("rule6_labels", RULE_6_PROMPT, _correction_labels),
        VisualRule("rule7_edge", RULE_7_PROMPT, _correction_edge),
    ]


def reset_rule4_state() -> None:
    global _rule4_moved
    _rule4_moved = set()


def _pixel_blank_check(image_b64: str) -> bool:
    """Return True if canvas likely blank (Rule 1 structural escalation)."""
    try:
        from PIL import Image
    except ImportError:
        return False
    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw)).convert("L")
    w, h = img.size
    cx0, cy0 = int(w * 0.2), int(h * 0.2)
    cx1, cy1 = int(w * 0.8), int(h * 0.8)
    region = img.crop((cx0, cy0, cx1, cy1))
    pixels = list(region.getdata())
    non_white = sum(1 for p in pixels if p < 240)
    return non_white < len(pixels) * 0.01


def check_rule_with_vision(rule: VisualRule, image_b64: str) -> dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"pass": True, "issue": "", "affected": []}

    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": rule.prompt
                            + '\n\nReply with JSON only: {"pass": true/false, '
                            '"issue": "description or empty", "affected": []}',
                        },
                    ],
                }
            ],
        )
        text = response.content[0].text
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as exc:
        logger.warning("Vision API failed for %s: %s", rule.name, exc)
    return {"pass": True, "issue": "", "affected": []}


def evaluate_visual_rules(
    rules: list[VisualRule], screenshot: dict[str, Any]
) -> list[Violation]:
    image_b64 = screenshot.get("image_base64") or screenshot.get("result", "")
    if isinstance(image_b64, dict):
        image_b64 = image_b64.get("image_base64", "")
    if not image_b64:
        return []

    violations: list[Violation] = []
    for rule in rules:
        if rule.name == "rule1_canvas" and _pixel_blank_check(str(image_b64)):
            violations.append(
                Violation(rule.name, "Canvas appears blank", [])
            )
            continue
        result = check_rule_with_vision(rule, str(image_b64))
        if not result.get("pass", True):
            violations.append(
                Violation(
                    rule.name,
                    result.get("issue", "visual check failed"),
                    result.get("affected") or [],
                )
            )
    return violations


def build_corrections(violations: list[Violation], rules: list[VisualRule]) -> list[Correction]:
    rule_map = {r.name: r for r in rules}
    corrections: list[Correction] = []
    for v in violations:
        rule = rule_map.get(v.rule_name)
        if rule:
            corrections.extend(rule.correction_fn(v.affected))
    return corrections
