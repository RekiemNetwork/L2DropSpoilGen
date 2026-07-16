# L2DropSpoilGen 1.4 — Drop/Spoil on-hover target icons (HighFive)

**English** · [Español](README.es.md) · [Português](README.pt.md)

**[⬇ Download the latest release](https://github.com/RekiemNetwork/L2DropSpoilGen/releases/latest)** · [VirusTotal 3/70](https://www.virustotal.com/gui/file/f81e29d7416db82dd7e4adbcf574e77615f929b7de4b39e8d6a9f03b88f75166) (PyInstaller generic false positive — full source included)

Adds a **Drop** icon (adena coin) and a **Spoil** icon to every monster's target
window. Hovering an icon shows that monster's **full drop / spoil list** with
amounts and chances, taken directly from your server's datapack.

**100% client-side** — your server is never touched, no core mods, no scripts.
The tool patches 3 files of the client's `System` folder:

| File | What is added |
|---|---|
| `npcgrp.dat` | one `[skill_id, level]` pair per icon in each monster's `property_list` |
| `SkillGrp.dat` | one entry per generated skill (defines the icon) |
| `SkillName-<lang>.dat` | one entry per generated skill (the tooltip text) |

## Requirements

- **Client:** Lineage 2 **High Five** (`.dat` crypto `Lineage2Ver413`).
- **Datapack:** L2J **Mobius**-style NPC XMLs (`data/stats/npcs/*.xml` with
  `<dropLists><drop>/<spoil>`). Item names are read from the XML comments next
  to each `<item>` (Mobius datapacks have them), so names come out in English.

## Usage

### GUI
Run `L2DropSpoilGen.exe` with no arguments. The interface is available in
**English, Español and Português** (auto-detected from your system, switchable
top-right) and every field has a **"?" hover tooltip** explaining what it does:

1. **Datapack NPCs folder** — your datapack's `data/stats/npcs` (the datapack
   root also works).
2. **Client System folder** — the `System` folder with the ORIGINAL
   `npcgrp.dat`, `SkillGrp.dat`, `SkillName-*.dat`. Detected languages appear
   as checkboxes.
3. **Output folder** — where the 3 patched `.dat` are written.
4. Press **Generate**, then **back up** the originals in `System` and copy the
   generated files over them. Done — enter the game and target any monster.

The GUI remembers your folders and options between runs, and opens the output
folder when generation finishes.

### CLI

```
L2DropSpoilGen.exe --npcs <datapack>\data\stats\npcs --system <client>\System --out patched
```

| Option | Default | Meaning |
|---|---|---|
| `--lang es,e` | all found | which `SkillName-<lang>.dat` to patch |
| `--rates-ini <path>` | off | your server's `Rates.ini` — shown chances/amounts get the **same multipliers the server applies** (per-item-id lists, herb/raid/normal cascade, spoil rates; chance-0 items are hidden) |
| `--hide-herbs` | off | remove herbs from drop lists (mobs that drop herbs drop them all) |
| `--min-chance 0.01` | 0 (off) | hide items below this chance % |
| `--max-items 30` | 0 (off) | cap items per list (adds `+N more...`) |
| `--max-line 70` | 0 (off) | cap line width (long item names are shortened) |
| `--max-chars 1500` | 1500 | max tooltip length |
| `--chance-decimals 2` | 4 | decimals shown in chances |
| `--title-drop` / `--title-spoil` | Drop / Spoil | header titles |
| `--header-factor 0.95` | 1.0 | header width vs the widest line (pixel-estimated) |
| `--trunc-suffix` | `...(more)` | text shown when a list is cut |
| `--base-id 30001` | 30001 | first generated skill id (change on collision) |
| `--drop-icon` / `--spoil-icon` | adena / spoil | any `icon.*` from the client |

Re-running the tool on already-patched files is safe: it detects and removes
the previous generation first (same ids/icons), so you can iterate on the
format options freely.

## Notes

- **Server rates** (`--rates-ini`, or the "Server Rates.ini" field in the GUI):
  the tool clones L2J Mobius' exact drop-rate cascade from
  `NpcTemplate.calculateDrops` — `DropChance/AmountMultiplierByItemId` first,
  then herb (`ex_immediate_effect` items, detected from `data/stats/items`),
  then raid (`type="RaidBoss|GrandBoss"`), then the normal Death multipliers;
  spoil uses the flat Spoil multipliers. Per-player factors (premium, champion,
  level-gap, drop buffs) are runtime-only and cannot be shown statically.
- Generated skill ids `30001+` are far above retail HighFive's maximum (26073).
  If your server already uses client skills in that range, change `--base-id`.
- The tooltip text lives in the skill **name** field on purpose: the
  description field has a hard width cap in the HF client and wraps lines.
- The tool self-checks every step (decrypt → disassemble → reassemble must be
  byte-identical before anything is modified) and preserves the `npcgrp.dat`
  footer, so a "File was corrupted" client error cannot slip through.
- **Antivirus:** the exe is packed with PyInstaller, which some AVs flag as a
  generic false positive. The full Python source (`l2dropspoilgen.py`) is
  included — you can audit it and run it directly (`python l2dropspoilgen.py`,
  Python 3.8+, no extra packages needed).

## Credits

- Bundled `.dat` toolchain: **l2encdec** and **l2asm/l2disasm** by
  **M.Soltys (DStuff)**, ddf definitions by the community (czardadius et al.).
- `npcgrp.dat` structure reference: **L2ClientDat** editor.
- Tool by **Rekiem Games Network** (rekiemgames.com). Free for the
  community; do not sell.
