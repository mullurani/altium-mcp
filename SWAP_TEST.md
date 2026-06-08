# MCU Swap Test — M031FB0AE → M031EB0AE

## Procedure

1. Complete a full `python build.py` run with `design/design.json` (M031FB0AE / TSSOP20).
2. Edit **only** these fields in `design/design.json`:
   - `"mcu": "M031EB0AE"`
   - `"mcu_package": "LQFP32"`
   - `"project_name": "isolated_io_v2"`
   - `"project_path": "C:/AltiumProjects/isolated_io_v2"`
3. Run `python build.py --config design/design.json --overwrite`.
4. Verify structural checks:
   - `get_sch_component_pin_count("U1")` → **32**
   - U1 footprint → **LQFP32**
   - `get_unconnected_pins` → **0**

## Expected pin mapping changes (logical interface unchanged)

| Signal   | Port | TSSOP20 pin name | LQFP32 pin name |
|----------|------|------------------|-----------------|
| IN1      | PA0  | PA0 (pin 20)     | PA0 (pin 30)    |
| IN2      | PA1  | PA1 (pin 19)     | PA1 (pin 29)    |
| OUT1     | PA2  | PA2 (pin 18)     | PA2 (pin 28)    |
| OUT2     | PA3  | PA3 (pin 17)     | PA3 (pin 27)    |
| ICE_CLK  | —    | ICE_CLK (pin 2)  | PB6 / ICE (pin 10) |
| ICE_DAT  | —    | ICE_DAT (pin 1)  | PB7 / ICE (pin 9)  |

Physical pin numbers change; net labels use **port names** (PA0, PA1, …) so connectivity is preserved without editing `inputs` / `outputs`.

## Live run results

| Check | M031FB0AE | M031EB0AE |
|-------|-----------|-----------|
| Build exit code | _pending live Altium run_ | _pending_ |
| U1 pin count | 20 | 32 |
| Footprint | TSSOP20 | LQFP32 |
| Unconnected pins | 0 | 0 |

> **Note:** Live Altium execution requires Altium Designer running with the MCP script project loaded. Run on a machine with Altium and record results in the table above.
