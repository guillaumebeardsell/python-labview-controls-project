# Confirming the ControlSettings contract with a Flatten-To-JSON diff

Goal: verify the Python `ControlSettings` model (docs/monarch-control-settings.md)
matches the real LabVIEW cluster — field names, types, array lengths, and
boolean polarity — by capturing one `Flatten To JSON` of the actual cluster and
diffing it with an automated tool.

**Almost all of this is automated.** Your only manual job is the ~5-node
LabVIEW capture in step 1. The tool does the comparison and tells you exactly
what (if anything) disagrees.

## Step 1 — capture the cluster as JSON (LabVIEW, one-time throwaway)

Build a tiny scratch VI (or drop these on an existing free block-diagram area):

1. Get an `APC_ControlSettings` value to flatten. **Best:** branch a *live*
   `PC_ControlSettings` wire where it already exists (e.g. in the UI or where
   the StateMachine is called) — a real value captures true polarity, array
   sizes, and defaults. **Simplest:** right-click the `APC_ControlSettings.ctl`
   typedef → *Create » Constant* to flatten a default value (still confirms
   names/types/lengths, but not live polarity).
2. Wire that value into **`Flatten To JSON`** (Programming » Cluster, Class &
   Variant » JSON). Leave inputs at default.
   - If you have the **JSONtext** toolkit installed, its `Serialize` works too;
     either is fine.
3. Wire the JSON string into **`Write to Text File`** (Programming » File I/O).
   Set the path to, say, `C:\temp\control_settings_flatten.json`.
4. Run the VI once. You now have the file. Delete the scratch VI afterward.

Notes:
- The `Requested mode` enum may flatten as a **number** (0..3, what the model
  expects) or as its **string** name — the tool reports which, so either is
  fine to start.
- Don't worry about pretty-printing or key order; the tool is order-insensitive.

## Step 2 — run the diff

Put the captured file anywhere and run:

```bat
python tools\compare_flatten.py C:\temp\control_settings_flatten.json
```

Or commit it to the repo (e.g. `original-labview-codebase/control_settings_flatten.json`)
and I'll run the diff and interpret it for you.

## Step 3 — read the report

The tool prints, and exits non-zero if any of the first four are non-empty:

- **LabVIEW fields not in the model** — a real field the model is missing, or a
  label I guessed wrong (I'll fix the mapping/model).
- **Model fields absent from the capture** — a field the model has but LabVIEW
  didn't emit (e.g. the removed `PFI advance`), or a label mismatch.
- **Type mismatches** — e.g. a bool the model treats as a number, or the
  enum-as-string case above.
- **Array length mismatches** — `activate_cylinder`, `mtr_modbus_floats`,
  `mtr_modbus_u16`.
- **Booleans observed** — every boolean and its captured value. This is how we
  settle **polarity**: with a live capture in a known plant state, we can read
  off whether e.g. `Intake vent = true` means closed (the diagram says vents are
  `1 = closed, 0 = open`) and whether NG/Ar/O2 feed valves match.
- **Arrays observed** — lengths, to confirm the three array sizes.

`RESULT: AGREE` means the structure is locked in. Any disagreements: send me the
report (or the JSON) and I'll reconcile the model and mapping, then we re-run
until it's clean.

## What this unblocks

A confirmed contract lets the gateway VI use the same `LABEL_TO_PATH` mapping
(`supervisory/monarch/labview_mapping.py`) to build the real telemetry JSON, and
lets the first state-machine port trust the field it reads. It closes all four
open questions in docs/monarch-control-settings.md in one shot.
