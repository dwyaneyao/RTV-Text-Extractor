# RTV Text Extractor

[![Companion repo: RTV-Mod-Localizer](https://img.shields.io/badge/Companion%20repo-RTV--Mod--Localizer-blue?style=for-the-badge&logo=github)](https://github.com/dwyaneyao/RTV-Mod-Localizer)

An external Python tool for translators who want to produce translation packs for [RTV-Mod-Localizer](https://github.com/dwyaneyao/RTV-Mod-Localizer). It reads `.vmz` mods (which are plain ZIP archives containing `.gd`, `.tscn`, `.tres`, and `.cfg` files), pulls out UI / MCM text that is safe to translate, and writes ready-to-fill JSON pack files.

The tool is **read-only**. It never modifies any `.vmz` file, never touches your game install, and never fills in translations — every `to:` field in the output is left empty. Filling them in by hand (or pipeline) is your job.

---

## Scope and Limitations — Please Read First

Godot mod development is free-form. There is no community-wide localization standard for how mod authors expose user-facing strings, which properties they assign them to, or how they compose them at runtime. As long as that remains true, **no purely automated extractor can cover 100% of the translatable text in every mod**. This tool is not an exception.

What this tool is designed to do:

- **Cut translation time** by extracting the strings it *can* recognize with high confidence, so translators can focus their effort on the text instead of on digging through `.vmz` internals.
- **Make mod updates cheap.** When a mod author ships a new version, re-running the extractor and diffing against your previous pack surfaces the added / removed / reworded strings quickly, so already-translated text can be reimported without redoing the whole mod.
- **Stay conservative.** The extractor prefers to miss a string over mistranslating a non-display identifier. Entries it is unsure about are skipped, not guessed.

What this tool cannot do:

- It cannot find every translatable string. Strings assembled at runtime, stored in non-standard properties, built from enums, or hidden behind custom helpers will not appear in the generated pack.
- It cannot judge quality. Filling in the `to` fields is still a human job, and at least one manual pass — ideally an in-game verification — is currently unavoidable.
- It cannot replace community conventions. The only path to truly complete coverage is mod authors adopting a shared localization convention; until that exists, expect to hand-author a small tail of entries per mod.

Treat the generated pack as a **strong starting point**, not a finished product.

---

## Requirements

- **Python 3.10+** — standard library only, no `pip install` needed
- **Tk** — included with the standard Windows Python installer; on Linux install with `sudo apt install python3-tk`
- A local copy of Road to Vostok with the mods you want to translate

Developed and tested on Windows 11, but the code is pure Python and platform-agnostic.

---

## What's in the Folder

| File | Purpose |
|---|---|
| `rtv_text_extractor.py` | Main extraction tool (GUI + CLI) |
| `README.md` | This file |

One file, one tool. No hidden dependencies.

---

## Typical Workflow

End-to-end, translating one mod looks like:

1. **Run the extractor** on the `.vmz` mod → get a pack JSON with empty `to` fields
2. **Fill in the `to` fields** in a text editor, spreadsheet, or any JSON-aware workflow you like
3. **Copy the filled-in pack** into `…/Road to Vostok/mods/RTV-mod-Localizer/Packs/<mod_id>/<locale>.json`
4. **Launch the game once** — `RTV-mod-Localizer` will detect the pack, rebuild the affected `.vmz`, back up the original as `.vmz.rtvsrc`, and deploy the translated version; restart the game when it asks you to

Shipping partial packs is fine. Entries with an empty `to` are simply ignored by the Localizer, so you can iterate mod by mod or even line by line.

---

## 1. GUI Mode (Recommended)

From the folder that contains `rtv_text_extractor.py`:

```powershell
python rtv_text_extractor.py
```

The GUI lets you:

- switch its own interface language between **简体中文**, **English**, and **日本語**
- pick a single `.vmz` file **or** a whole `mods` folder as the input
- pick an output directory
- choose the target locale from a dropdown:
  - `Arabic (ar_ar)`
  - `Deutsch (de_de)`
  - `Espanol (es_es)`
  - `Italiano (it_it)`
  - `Japanese (ja_jp)`
  - `Korean (ko_kr)`
  - `Portugues (pt_br)`
  - `Russian (ru_ru)`
  - `English (US) (us_us)`
  - `Chinese Simplified (zh_cn)`
  - `Chinese Traditional (zh_tw)`
- press **Start** and watch the log panel

When the run finishes, each mod becomes a sub-folder under your chosen output directory, each containing one `<locale>.json` pack file.

---

## 2. CLI Mode

For scripting or batch runs, pass `--no-gui`:

**Single `.vmz`:**

```powershell
python rtv_text_extractor.py --no-gui --mode file ^
  --input  "D:\Games\Steam\steamapps\common\Road to Vostok\mods\XP-Skills-System 2.vmz" ^
  --output "D:\Temp\rtv-packs" ^
  --locale zh_cn
```

**Whole mods folder:**

```powershell
python rtv_text_extractor.py --no-gui --mode folder ^
  --input  "D:\Games\Steam\steamapps\common\Road to Vostok\mods" ^
  --output "D:\Temp\rtv-packs" ^
  --locale zh_cn
```

| Flag       | Required              | Notes                                               |
|------------|-----------------------|-----------------------------------------------------|
| `--no-gui` | Yes (for CLI)         | Skips the Tk window                                 |
| `--mode`   | Yes                   | `file` or `folder`                                  |
| `--input`  | Yes                   | Path to a `.vmz` file or a folder containing them   |
| `--output` | Yes                   | Root directory for generated packs                  |
| `--locale` | No (default `us_us`)  | Any of the locale IDs listed above                  |

Exit code is `0` when every mod was processed without failure, `1` otherwise. A summary line `processed=N skipped=N failures=N` is printed at the end.

If the tool finds a `.vmz.rtvsrc` backup next to a `.vmz` (left by `RTV-mod-Localizer` after localization), it prefers the backup — that's the pristine source, not the post-patch version — so results stay stable across localizer runs.

---

## Output Shape

For a mod whose internal `mod.txt` declares `id = xp-skills-system`, the extractor writes:

```
<output>/
  xp-skills-system/
    zh_cn.json
```

Example `zh_cn.json`:

```json
{
  "pack_version": 1,
  "mod_id": "xp-skills-system",
  "mcm_mod_ids": ["XPSkillsSystem"],
  "entries": [
    {
      "match": "exact",
      "from": "Skills",
      "to": "",
      "where": {
        "script_path_contains": "mods/XPSkillsSystem/Interface.gd"
      }
    },
    {
      "match": "exact",
      "from": "XP & Skills System",
      "to": "",
      "where": {
        "script_path_contains": "mods/XPSkillsSystem/Main.gd",
        "is_mcm": true,
        "mcm_mod_id": "XPSkillsSystem",
        "property": "friendlyName"
      }
    }
  ]
}
```

Field guide:

- `match` — always `exact` (the extractor never emits `regex` or `contains`)
- `from` — the exact source text as it appears in the decoded `.vmz`
- `to` — your translated text; leave as `""` until you fill it in
- `where` — context constraints that `RTV-mod-Localizer` uses to distinguish multiple occurrences of the same string. Supported fields:
  - `script_path_contains`
  - `scene_path_contains`
  - `owner_script_path_contains`
  - `is_mcm`
  - `mcm_mod_id`
  - `property`

When the same `from` string appears in two genuinely different contexts (e.g. once as an MCM label and once as a scene text), the extractor emits two entries with different `where` blocks. **Do not merge them** — that distinction is what keeps `RTV-mod-Localizer` from over-translating identifiers that happen to share a label's spelling.

After you've filled in the `to` fields, drop the file into:

```
…\Road to Vostok\mods\RTV-mod-Localizer\Packs\<mod_id>\<locale>.json
```

On the next game launch, `RTV-mod-Localizer` will detect the pack, rebuild the affected `.vmz`, back up the original as `.vmz.rtvsrc`, and deploy the translated version. Restart the game when the Localizer asks you to.

---

## What the Extractor Covers

**GDScript (`.gd`):**

- assignments to recognized display properties: `.text = ...`, `.title = ...`, `.label = ...`, `.tooltip_text = ...`, `.placeholder_text = ...`, and similar
- MCM configuration dictionaries using both `=` and `:` styles
- multi-line `options` arrays inside MCM config blocks
- `_mcm_helpers.RegisterConfiguration(MOD_ID, MOD_NAME, CONFIG_DIR, "description")`-style calls, including **identifier arguments backed by `const` declarations** such as `const MOD_NAME := "My Mod Title"`
- `MOD_ID` and `MCM_MOD_ID` constants (both `=` and `:=` forms)
- format-string payloads like `"Enemies Killed: %s/%s"` where translatable text surrounds the placeholders

**Scene / resource / config files (`.tscn`, `.tres`, `.cfg`):**

- display-property assignments (`text`, `title`, `placeholder_text`, …)
- `[resource]` / `[node]` text properties

---

## What the Extractor Avoids (By Design)

- does **not** edit any `.vmz` file, and does not touch the game folder unless you explicitly target it as an input
- skips resource paths (`res://…`, `user://…`), node names, gameplay / logic identifiers, file paths, config keys, enum-like identifiers, and other non-display strings
- skips a literal entirely if the **same** literal appears as both UI text and a logic identifier in the same source file — this prevents over-translating cases like `"Skills"` being both a button label and a dictionary key
- skips fully commented-out GDScript lines and commented MCM config blocks
- skips pure-placeholder format strings like `"%d/%d"` that have no translatable surrounding text
- never auto-generates `regex` or `contains` matches — only `exact`

If a mod relies heavily on dynamic string building (format strings assembled at runtime, translations driven by enum values, text hard-coded into non-display properties, etc.), those parts fall outside automatic coverage. You can always hand-author extra entries with the correct `where` block and add them to the pack — the Localizer treats extractor output and hand-written entries identically.

---

## Tips for Translators

- **Work on one mod at a time.** The output folders are independent, so you can ship one pack at a time and leave unfinished ones empty.
- **Never edit `match`, `from`, or `where`.** Those are what lets the Localizer find and replace the right string without corrupting unrelated text. Touch only `to`.
- **If two entries look identical but have different `where` blocks, translate them independently.** They really are two different occurrences with different contexts.
- **Keep placeholders and escapes intact.** A `from` value of `"Enemies: %s"` must have a matching `%s` in the `to` value; likewise for `\n`, `\t`, and quoted characters.
- **Empty `to` fields are ignored by the Localizer.** Shipping a partially filled pack is safe — untranslated entries stay in the original language.
- **Re-run the extractor after the mod author updates.** Diff the new pack against your previous one to spot added / removed / reworded strings quickly.

---

## License

Provided as-is under the MIT License unless noted otherwise. The extractor is a standalone offline tool — it does not phone home, log telemetry, or require any online account.
