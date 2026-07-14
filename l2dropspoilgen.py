#!/usr/bin/env python3
"""
L2DropSpoilGen — Drop/Spoil on-hover target icons for Lineage 2 HighFive clients.

Point it to an L2J Mobius datapack (data/stats/npcs) and to your client's System
folder, and it generates the 3 patched client files:

    npcgrp.dat          - adds [skill_id, level] pairs to each monster's property_list
    SkillGrp.dat        - one entry per custom skill (defines the icon)
    SkillName-<lang>.dat- one entry per custom skill (tooltip text goes in the NAME field)

Result in game: targeting a monster shows a Drop icon (adena coin) and/or a Spoil
icon in the target window; hovering them shows that monster's full drop/spoil list.
100% client-side — the server is never touched.

Run without arguments for the GUI, or with --npcs/--system for CLI mode.

Client requirements: HighFive client, .dat crypto "Lineage2Ver413".
Datapack requirements: L2J Mobius-style NPC XMLs (<dropLists><drop>/<spoil>).
Item names are taken from the XML comments next to each <item> (Mobius has them).
"""

import os
import re
import sys
import json
import glob
import struct
import shutil
import tempfile
import subprocess
import argparse

APP = "L2DropSpoilGen"
VERSION = "1.3"

# Skill ids >= STRIP_FLOOR that use our icons are treated as leftovers from a
# previous run of this tool and are removed before regenerating (idempotent
# re-runs on already-patched files). Retail HF's highest skill id is 26073.
STRIP_FLOOR = 27000

DEFAULTS = dict(
    base_id=30001,
    max_chars=1500,
    max_line=0,          # 0 = unlimited; else truncate long item names
    max_items=0,         # 0 = unlimited; else cap items per list
    min_chance=0.0,      # 0 = keep all; else hide items below this chance (%)
    chance_decimals=4,
    drop_icon="icon.etc_adena_i00",
    spoil_icon="icon.skill0254",
    title_drop="Drop",
    title_spoil="Spoil",
    header_char="=",
    header_factor=1.0,   # scale of the header width vs the widest item line
    trunc_suffix="...(more)",
    template_skill="4460",
)

# Approximate glyph widths of the client tooltip font (proportional), in units
# of the '=' glyph. Used to size the header in PIXELS instead of characters —
# item lines are full of narrow chars (spaces, i, l, dots) so a char-count
# header renders much wider than the list.
_CHAR_W = {
    " ": 0.48, ".": 0.48, ",": 0.48, ":": 0.48, ";": 0.48, "!": 0.48,
    "'": 0.33, "(": 0.57, ")": 0.57, "[": 0.57, "]": 0.57, "-": 0.57,
    "/": 0.48, "%": 1.52, "+": 1.0, "=": 1.0, "*": 0.67, "_": 0.95,
    "i": 0.38, "j": 0.38, "l": 0.38, "t": 0.5, "f": 0.5, "r": 0.57,
    "m": 1.43, "w": 1.24, "I": 0.48, "J": 0.86, "M": 1.43, "W": 1.62,
}


def disp_width(s):
    """Estimated rendered width of s, in '=' glyph units."""
    return sum(_CHAR_W.get(c, 0.95 if not c.isupper() else 1.15) for c in s)


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- toolchain

def tools_dir():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(base, "tools")
    for f in ("l2encdec_old.exe", "l2asm.exe", "l2disasm.exe",
              os.path.join("ddf", "skillgrp.ddf"), os.path.join("ddf", "skillname-e.ddf")):
        if not os.path.isfile(os.path.join(d, f)):
            raise ToolError("Missing bundled tool: tools/%s" % f)
    return d


def run_tool(workdir, exe, args, expect_out=None):
    """Run a bundled tool with cwd=workdir. All file args must be relative
    names inside workdir (the old tools choke on paths with spaces)."""
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    p = subprocess.run([exe] + args, cwd=workdir, capture_output=True,
                       creationflags=flags)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    ok = p.returncode == 0
    if ok and expect_out is not None:
        f = os.path.join(workdir, expect_out)
        ok = os.path.isfile(f) and os.path.getsize(f) > 0
    if not ok:
        tail = "\n".join(out.strip().splitlines()[-8:])
        raise ToolError("%s %s failed (exit %d):\n%s"
                        % (os.path.basename(exe), " ".join(args), p.returncode, tail))
    return out


class Toolchain:
    def __init__(self, workdir):
        self.td = tools_dir()
        self.wd = workdir
        # ddf paths are passed to l2asm/l2disasm as arguments -> copy them into
        # the (space-free) workdir and reference them relatively.
        os.makedirs(os.path.join(workdir, "ddf"), exist_ok=True)
        for f in ("skillgrp.ddf", "skillname-e.ddf"):
            shutil.copy2(os.path.join(self.td, "ddf", f), os.path.join(workdir, "ddf", f))

    def decrypt(self, dat_rel, dec_rel):
        run_tool(self.wd, os.path.join(self.td, "l2encdec_old.exe"),
                 ["-s", dat_rel, dec_rel], expect_out=dec_rel)

    def encrypt(self, dec_rel, dat_rel):
        run_tool(self.wd, os.path.join(self.td, "l2encdec_old.exe"),
                 ["-h", "413", dec_rel, dat_rel], expect_out=dat_rel)

    def disasm(self, ddf, dec_rel, txt_rel):
        run_tool(self.wd, os.path.join(self.td, "l2disasm.exe"),
                 ["-d", "ddf/" + ddf, dec_rel, txt_rel], expect_out=txt_rel)

    def asm(self, ddf, txt_rel, dec_rel):
        run_tool(self.wd, os.path.join(self.td, "l2asm.exe"),
                 ["-d", "ddf/" + ddf, txt_rel, dec_rel], expect_out=dec_rel)


# ---------------------------------------------------------------- datapack extraction

ITEM_RE = re.compile(r'<item id="(\d+)"\s+min="(\d+)"\s+max="(\d+)"\s+chance="([\d.]+)"'
                     r'\s*[\\/]*>\s*(?:<!--\s*(.*?)\s*-->)?')
NPC_RE = re.compile(r'<npc id="(\d+)"([^>]*)>(.*?)</npc>', re.S)
GROUP_RE = re.compile(r'<group chance="([\d.]+)"\s*>(.*?)</group>', re.S)


def resolve_npcs_dir(path):
    """Accept either the npcs dir itself or a datapack root."""
    for cand in (path, os.path.join(path, "data", "stats", "npcs"),
                 os.path.join(path, "game", "data", "stats", "npcs"),
                 os.path.join(path, "dist", "game", "data", "stats", "npcs")):
        if os.path.isdir(cand) and glob.glob(os.path.join(cand, "*.xml")):
            return cand
    raise ToolError("No NPC XMLs found under: %s\n"
                    "Point --npcs to the datapack's data/stats/npcs folder." % path)


def _items_of(block):
    out = []
    for it in ITEM_RE.finditer(block):
        name = it.group(5) or ("item#" + it.group(1))
        out.append((name, int(it.group(2)), int(it.group(3)), float(it.group(4)),
                    int(it.group(1))))
    return out


def extract_npcs(npcs_dir, log):
    """-> {npc_id: {"drop": [(name, min, max, chance%), ...], "spoil": [...]}}"""
    res = {}
    files = glob.glob(os.path.join(npcs_dir, "*.xml"))
    for f in files:
        data = open(f, encoding="utf-8", errors="replace").read()
        for m in NPC_RE.finditer(data):
            block = m.group(3)
            dl = re.search(r'<dropLists>(.*?)</dropLists>', block, re.S)
            if not dl:
                continue
            dl = dl.group(1)
            drop, spoil = [], []
            dm = re.search(r'<drop>(.*?)</drop>', dl, re.S)
            if dm:
                inner = dm.group(1)
                # items inside <group chance=..>: effective chance = group * item / 100
                for g in GROUP_RE.finditer(inner):
                    gc = float(g.group(1))
                    for name, mn, mx, ch, iid in _items_of(g.group(2)):
                        drop.append((name, mn, mx, gc * ch / 100.0, iid))
                # loose items directly in <drop> (no group): chance as-is
                for item in _items_of(re.sub(r'<group.*?</group>', '', inner, flags=re.S)):
                    drop.append(item)
            sm = re.search(r'<spoil>(.*?)</spoil>', dl, re.S)
            if sm:
                spoil = _items_of(sm.group(1))
            if drop or spoil:
                t = re.search(r'type="([^"]*)"', m.group(2))
                res[int(m.group(1))] = {"drop": drop, "spoil": spoil,
                                        "raid": bool(t) and t.group(1) in ("RaidBoss", "GrandBoss")}
    nd = sum(1 for v in res.values() if v["drop"])
    ns = sum(1 for v in res.values() if v["spoil"])
    log("Datapack: %d XML files, %d NPCs with lists (%d drop, %d spoil)"
        % (len(files), len(res), nd, ns))
    if not res:
        raise ToolError("No <dropLists> found — is this an L2J Mobius datapack?")
    return res


# ---------------------------------------------------------------- server rates

class Rates:
    """Multipliers from the server's Rates.ini, mirroring the exact cascade of
    L2J Mobius NpcTemplate.calculateDrops (per-item-id list -> herb -> raid ->
    normal; spoil uses its own flat multipliers)."""

    def __init__(self):
        self.death_chance = self.death_amount = 1.0
        self.spoil_chance = self.spoil_amount = 1.0
        self.herb_chance = self.herb_amount = 1.0
        self.raid_chance = self.raid_amount = 1.0
        self.chance_by_id = {}
        self.amount_by_id = {}

    @property
    def active(self):
        return (any(v != 1.0 for v in (
            self.death_chance, self.death_amount, self.spoil_chance,
            self.spoil_amount, self.herb_chance, self.herb_amount,
            self.raid_chance, self.raid_amount))
            or self.chance_by_id or self.amount_by_id)


def parse_rates_ini(path, log):
    """Minimal java.util.Properties reader (#/! comments, backslash line
    continuation, key = value) — same behavior as the server's config loader."""
    if not os.path.isfile(path):
        raise ToolError("Rates.ini not found: %s" % path)
    kv, buf = {}, ""
    for line in open(path, encoding="utf-8", errors="replace").read().splitlines():
        s = line.strip()
        if buf == "" and (not s or s[0] in "#!"):
            continue
        if s.endswith("\\"):
            buf += s[:-1]
            continue
        buf += s
        if "=" in buf:
            k, v = buf.split("=", 1)
            kv[k.strip()] = v.strip()
        buf = ""

    r = Rates()

    def num(key, cur):
        try:
            return float(kv[key])
        except (KeyError, ValueError):
            return cur

    def idmap(key):
        out = {}
        for part in kv.get(key, "").split(";"):
            bits = part.split(",")
            if len(bits) == 2:
                try:
                    out[int(bits[0])] = float(bits[1])
                except ValueError:
                    pass
        return out

    r.death_chance = num("DeathDropChanceMultiplier", 1.0)
    r.death_amount = num("DeathDropAmountMultiplier", 1.0)
    r.spoil_chance = num("SpoilDropChanceMultiplier", 1.0)
    r.spoil_amount = num("SpoilDropAmountMultiplier", 1.0)
    r.herb_chance = num("HerbDropChanceMultiplier", 1.0)
    r.herb_amount = num("HerbDropAmountMultiplier", 1.0)
    r.raid_chance = num("RaidDropChanceMultiplier", 1.0)
    r.raid_amount = num("RaidDropAmountMultiplier", 1.0)
    r.chance_by_id = idmap("DropChanceMultiplierByItemId")
    r.amount_by_id = idmap("DropAmountMultiplierByItemId")

    parts = []
    for label, c, a in (("death", r.death_chance, r.death_amount),
                        ("spoil", r.spoil_chance, r.spoil_amount),
                        ("herb", r.herb_chance, r.herb_amount),
                        ("raid", r.raid_chance, r.raid_amount)):
        if c != 1.0 or a != 1.0:
            parts.append("%s chance x%g amount x%g" % (label, c, a))
    special = {k: v for k, v in r.chance_by_id.items() if v != 1.0}
    if special or r.amount_by_id:
        parts.append("%d per-item multipliers" % len(set(r.amount_by_id) | set(special)))
    log("Rates.ini: %s" % ("; ".join(parts) if parts else "all multipliers are 1 (retail)"))
    return r


def load_herb_ids(npcs_dir, log):
    """Item ids with ex_immediate_effect=true (herbs) from data/stats/items —
    the server routes those through the Herb multipliers."""
    items_dir = os.path.join(os.path.dirname(npcs_dir), "items")
    if not os.path.isdir(items_dir):
        log("WARNING: items folder not found next to npcs — herbs will use "
            "normal drop multipliers in the generated text")
        return frozenset()
    herbs = set()
    for f in glob.glob(os.path.join(items_dir, "*.xml")):
        data = open(f, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r'<item id="(\d+)"(.*?)</item>', data, re.S):
            if re.search(r'name="ex_immediate_effect"\s+val="true"', m.group(2)):
                herbs.add(int(m.group(1)))
    return frozenset(herbs)


def apply_rates(items, kind, raid, rates, herbs):
    """Same math the server applies on kill, minus per-player factors
    (premium/champion/level gap). Amounts floor like the server's (long) cast;
    chance-0 items are removed; display chance is capped at 100%."""
    out = []
    for name, mn, mx, ch, iid in items:
        if kind == "spoil":
            rc, ra = rates.spoil_chance, rates.spoil_amount
        else:
            if iid in rates.chance_by_id:
                rc = rates.chance_by_id[iid]
                if iid == 57 and rc > 100:
                    rc = 100.0
            elif iid in herbs:
                rc = rates.herb_chance
            elif raid:
                rc = rates.raid_chance
            else:
                rc = rates.death_chance
            if iid in rates.amount_by_id:
                ra = rates.amount_by_id[iid]
            elif iid in herbs:
                ra = rates.herb_amount
            elif raid:
                ra = rates.raid_amount
            else:
                ra = rates.death_amount
        ch = min(ch * rc, 100.0)
        if ch <= 0:
            continue
        out.append((name, int(mn * ra), int(mx * ra), ch, iid))
    return out


# ---------------------------------------------------------------- text generation

def fmt_chance(x, decimals):
    return ("%.*f" % (decimals, x)).rstrip("0").rstrip(".")


def format_item(it, o):
    name, mn, mx, ch = it[0], it[1], it[2], it[3]
    amt = "" if (mn == mx == 1) else (" %d" % mn if mn == mx else " %d-%d" % (mn, mx))
    tail = "%s (%s%%)" % (amt, fmt_chance(ch, o["chance_decimals"]))
    line = name + tail
    if o["max_line"] and len(line) > o["max_line"]:
        keep = max(o["max_line"] - len(tail) - 3, 8)
        line = name[:keep] + "..." + tail
    return line


def make_lines(items, o):
    if o["min_chance"]:
        items = [it for it in items if it[3] >= o["min_chance"]]
    hidden = 0
    if o["max_items"] and len(items) > o["max_items"]:
        hidden = len(items) - o["max_items"]
        items = items[:o["max_items"]]
    lines = [format_item(it, o) for it in items]
    if hidden:
        lines.append("+%d more..." % hidden)
    return lines


def make_body(lines, title, o):
    target = max(disp_width(r) for r in lines) * o["header_factor"]
    t = " %s " % title
    pad = max(int(round(target - disp_width(t))), 4)
    header = o["header_char"] * (pad // 2) + t + o["header_char"] * (pad - pad // 2)
    body = header + "\\n" + "\\n".join(lines)
    if len(body) > o["max_chars"]:
        body = body[:o["max_chars"]].rsplit("\\n", 1)[0] + "\\n" + o["trunc_suffix"]
    return body


# ---------------------------------------------------------------- SkillGrp / SkillName rows

def load_rows(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    if "�" in txt:
        raise ToolError("Non-UTF8 bytes in %s — unexpected disasm output" % os.path.basename(path))
    return [l for l in txt.split("\n") if l.strip() != ""]


def save_rows(path, rows):
    open(path, "w", encoding="utf-8", newline="").write("\n".join(rows) + "\n")


def row_id(row):
    f = row.split("\t", 1)
    try:
        return int(f[0])
    except ValueError:
        return None


def clean_skillgrp(rows, o, log):
    """Remove rows generated by a previous run (id>=STRIP_FLOOR with our icons).
    -> (kept_rows, strip_ids)"""
    kept, strip_ids = [], set()
    for r in rows:
        i = row_id(r)
        if i is not None and i >= STRIP_FLOOR:
            f = r.split("\t")
            if o["drop_icon"] in f or o["spoil_icon"] in f:
                strip_ids.add(i)
                continue
        kept.append(r)
    if strip_ids:
        log("SkillGrp: removed %d entries from a previous run (ids %d..%d)"
            % (len(strip_ids), min(strip_ids), max(strip_ids)))
    return kept, strip_ids


def find_template(rows, o):
    tmpl = None
    for r in rows:
        f = r.split("\t")
        if len(f) >= 2 and f[0] == o["template_skill"] and f[1] == "1":
            tmpl = f
            break
    if tmpl is None:  # fallback: any real skill row with an icon
        for r in rows:
            f = r.split("\t")
            if row_id(r) is not None and any(c.startswith("icon.skill") for c in f):
                tmpl = f
                break
    if tmpl is None:
        raise ToolError("Could not find a template row in SkillGrp — unexpected format")
    for idx, c in enumerate(tmpl):
        if c.startswith("icon."):
            return tmpl, idx
    raise ToolError("Template SkillGrp row has no icon column")


def generate(drops, sg_rows, o, log, rates=None, herbs=frozenset()):
    """-> (new_sg_rows, new_sn_rows, skmap {npc_id: [sid, lvl, ...]})"""
    tmpl, icon_col = find_template(sg_rows, o)
    existing = set(i for i in (row_id(r) for r in sg_rows) if i is not None and i >= o["base_id"])

    new_sg, new_sn, skmap = [], [], {}
    nid = o["base_id"]
    for npc in sorted(drops):
        pairs = []
        for kind, icon, title in (("drop", o["drop_icon"], o["title_drop"]),
                                  ("spoil", o["spoil_icon"], o["title_spoil"])):
            items = drops[npc][kind]
            if rates is not None and rates.active:
                items = apply_rates(items, kind, drops[npc].get("raid", False),
                                    rates, herbs)
            lines = make_lines(items, o)
            if not lines:
                continue
            sid = nid
            nid += 1
            g = tmpl[:]
            g[0] = str(sid)
            g[icon_col] = icon
            new_sg.append("\t".join(g))
            # Everything goes in the NAME field: it has no width cap, unlike
            # description (which hard-wraps). Empty description avoids "none".
            body = make_body(lines, title, o)
            new_sn.append("%d\t1\ta,%s\\0\ta,\ta,none\\0\ta,none\\0" % (sid, body))
            pairs += [sid, 1]
        if pairs:
            skmap[npc] = pairs

    used = set(range(o["base_id"], nid))
    clash = existing & used
    if clash:
        raise ToolError("SkillGrp already has %d foreign entries in id range %d..%d "
                        "(e.g. %d). Use a different --base-id or clean client files."
                        % (len(clash), o["base_id"], nid - 1, min(clash)))
    log("Generated %d custom skills (ids %d..%d) for %d NPCs"
        % (nid - o["base_id"], o["base_id"], nid - 1, len(skmap)))
    return new_sg, new_sn, skmap


def clean_skillname(rows, strip_ids, planned, log, fname):
    kept, removed = [], 0
    for r in rows:
        i = row_id(r)
        if i is not None and i in strip_ids:
            removed += 1
            continue
        kept.append(r)
    if removed:
        log("%s: removed %d entries from a previous run" % (fname, removed))
    clash = set(i for i in (row_id(r) for r in kept) if i in planned)
    if clash:
        raise ToolError("%s already has %d foreign entries in the target id range "
                        "(e.g. %d). Use a different --base-id or clean client files."
                        % (fname, len(clash), min(clash)))
    return kept


# ---------------------------------------------------------------- npcgrp.dat (own parser)

class NpcGrp:
    """HighFive npcgrp.dec walker. Strings are [u32 byte-len][UTF-16LE] (not
    null-terminated), CNTR is an Unreal compact index. The trailing footer
    (~13 bytes after the last record) MUST be preserved or the client reports
    'File was corrupted'."""

    def __init__(self, data):
        self.data = data

    def rebuild(self, strip_ids, add_map, force_rewrite=False):
        """-> (bytes, npcs_patched, pairs_stripped). Rewrites each record's
        property_list, dropping [id, lvl] pairs whose id is in strip_ids and
        appending add_map[npc_id] pairs."""
        data = self.data
        pos = [0]

        def u32():
            v = struct.unpack_from("<I", data, pos[0])[0]
            pos[0] += 4
            return v

        def f32():
            pos[0] += 4

        def uni():
            n = struct.unpack_from("<I", data, pos[0])[0]
            pos[0] += 4 + n

        def cntr_read():
            b0 = data[pos[0]]
            pos[0] += 1
            val = b0 & 0x3F
            sh = 6
            if b0 & 0x80:
                while True:
                    bx = data[pos[0]]
                    pos[0] += 1
                    val |= (bx & 0x7F) << sh
                    sh += 7
                    if not (bx & 0x80):
                        break
            return val

        def cntr_encode(v):
            out = bytearray()
            b0 = v & 0x3F
            v >>= 6
            if v:
                b0 |= 0x80
            out.append(b0)
            while v:
                b = v & 0x7F
                v >>= 7
                if v:
                    b |= 0x80
                out.append(b)
            return bytes(out)

        count = u32()
        out = bytearray(struct.pack("<I", count))
        patched = stripped = 0
        odd_props = 0
        for _ in range(count):
            rec_start = pos[0]
            npc_id = u32()
            uni(); uni()                                   # class, mesh
            for _ in range(u32()): uni()                   # tex1[]
            for _ in range(u32()): uni()                   # tex2[]
            prop_off = pos[0]
            pcount = cntr_read()
            arr = [u32() for _ in range(pcount)]
            prop_end = pos[0]
            f32()                                          # speed
            for _ in range(u32()): uni()                   # sounds 1
            for _ in range(u32()): uni()                   # sounds 2
            for _ in range(u32()): uni()                   # sounds 3
            for _ in range(u32()): uni()                   # sounds 4
            for _ in range(u32()): (uni(), f32())          # (string, float) pairs
            for _ in range(cntr_read()): u32()
            for _ in range(cntr_read()): u32()
            uni()                                          # attack_effect
            u32(); f32(); f32(); f32()
            u32(); u32()
            for _ in range(u32()):                         # null-terminated cstrings
                while data[pos[0]] != 0:
                    pos[0] += 1
                pos[0] += 1
            u32()
            rec_end = pos[0]

            # Retail lists are [skill_id, level] pairs, EXCEPT a lone [0] used as
            # an "empty" sentinel (1299 retail records). Legacy runs of this tool
            # appended pairs after that 0 ([0, sid, 1]) — understand both shapes.
            if len(arr) % 2 == 0:
                head, pairs = [], arr
            elif arr and arr[0] == 0:
                head, pairs = [0], arr[1:]
            else:
                head, pairs = None, None

            new_arr = arr
            add = add_map.get(npc_id)
            if head is None:
                if add or (strip_ids and any(x in strip_ids for x in arr)):
                    odd_props += 1
            else:
                changed = False
                if strip_ids and pairs:
                    kept = []
                    for i in range(0, len(pairs), 2):
                        if pairs[i] in strip_ids:
                            stripped += 1
                            changed = True
                        else:
                            kept += [pairs[i], pairs[i + 1]]
                    pairs = kept
                if add:
                    pairs = pairs + add
                    patched += 1
                    changed = True
                if changed:
                    # when real pairs exist the [0] sentinel is dropped — retail
                    # never mixes it with pairs; restore it if the list empties.
                    new_arr = pairs if pairs else head
            if force_rewrite or new_arr != arr:
                out += data[rec_start:prop_off]
                out += cntr_encode(len(new_arr))
                out += b"".join(struct.pack("<I", x) for x in new_arr)
                out += data[prop_end:rec_end]
            else:
                out += data[rec_start:rec_end]
        out += data[pos[0]:]                               # preserve footer/tail
        if odd_props:
            raise ToolError("npcgrp: %d records need patching but have an "
                            "unrecognized property_list shape" % odd_props)
        return bytes(out), patched, stripped

    def selfcheck(self):
        """Full parse + active rewrite of every property_list with no changes
        must reproduce the input byte-for-byte."""
        try:
            out, _, _ = self.rebuild(set(), {}, force_rewrite=True)
        except (struct.error, IndexError) as e:
            raise ToolError("npcgrp structure walk failed (%s) — this does not "
                            "look like a HighFive npcgrp.dat" % e)
        if out != self.data:
            raise ToolError("npcgrp round-trip self-check failed — this does not "
                            "look like a HighFive npcgrp.dat")


# ---------------------------------------------------------------- pipeline

def find_file_ci(d, name):
    for f in os.listdir(d):
        if f.lower() == name.lower():
            return os.path.join(d, f)
    return None


def detect_langs(system_dir):
    langs = []
    for f in sorted(os.listdir(system_dir)):
        m = re.match(r"skillname-(\w+)\.dat$", f, re.I)
        if m:
            langs.append(m.group(1).lower())
    return langs


def run_pipeline(opts, log):
    o = dict(DEFAULTS)
    o.update({k: v for k, v in opts.items() if v is not None})

    npcs_dir = resolve_npcs_dir(o["npcs"])
    sysdir = o["system"]
    if not os.path.isdir(sysdir):
        raise ToolError("System folder not found: %s" % sysdir)

    ng_src = find_file_ci(sysdir, "npcgrp.dat")
    sg_src = find_file_ci(sysdir, "skillgrp.dat")
    if not ng_src or not sg_src:
        raise ToolError("npcgrp.dat / SkillGrp.dat not found in %s" % sysdir)

    langs = o.get("langs") or detect_langs(sysdir)
    if not langs:
        raise ToolError("No SkillName-<lang>.dat found in %s" % sysdir)
    sn_srcs = {}
    for lang in langs:
        p = find_file_ci(sysdir, "skillname-%s.dat" % lang)
        if not p:
            raise ToolError("SkillName-%s.dat not found in %s" % (lang, sysdir))
        sn_srcs[lang] = p
    log("Input:  %s" % npcs_dir)
    log("Client: %s  (languages: %s)" % (sysdir, ", ".join(langs)))

    outdir = o["out"]
    os.makedirs(outdir, exist_ok=True)

    workdir = tempfile.mkdtemp(prefix="l2dsg_")
    try:
        tc = Toolchain(workdir)

        # 1) decrypt + disassemble client files
        log("Decrypting client .dat files (ver 413)...")
        shutil.copy2(ng_src, os.path.join(workdir, "ng.dat"))
        shutil.copy2(sg_src, os.path.join(workdir, "sg.dat"))
        tc.decrypt("ng.dat", "ng.dec")
        tc.decrypt("sg.dat", "sg.dec")
        tc.disasm("skillgrp.ddf", "sg.dec", "sg.txt")
        tc.asm("skillgrp.ddf", "sg.txt", "sg_chk.dec")
        if open(os.path.join(workdir, "sg.dec"), "rb").read() != \
           open(os.path.join(workdir, "sg_chk.dec"), "rb").read():
            raise ToolError("SkillGrp round-trip self-check failed — "
                            "client is not HighFive-compatible")
        sn_rows = {}
        for lang in langs:
            shutil.copy2(sn_srcs[lang], os.path.join(workdir, "sn_%s.dat" % lang))
            tc.decrypt("sn_%s.dat" % lang, "sn_%s.dec" % lang)
            tc.disasm("skillname-e.ddf", "sn_%s.dec" % lang, "sn_%s.txt" % lang)
            tc.asm("skillname-e.ddf", "sn_%s.txt" % lang, "sn_%s_chk.dec" % lang)
            if open(os.path.join(workdir, "sn_%s.dec" % lang), "rb").read() != \
               open(os.path.join(workdir, "sn_%s_chk.dec" % lang), "rb").read():
                raise ToolError("SkillName-%s round-trip self-check failed" % lang)
            sn_rows[lang] = load_rows(os.path.join(workdir, "sn_%s.txt" % lang))
        log("Client files decrypted and verified (round-trip OK)")

        # 2) extract drop/spoil from the datapack
        drops = extract_npcs(npcs_dir, log)

        # 2b) optional server rates
        rates, herbs = None, frozenset()
        if o.get("rates_ini"):
            rates = parse_rates_ini(o["rates_ini"], log)
            if rates.active:
                herbs = load_herb_ids(npcs_dir, log)

        # 3) generate skills (cleaning any previous run first)
        sg_rows = load_rows(os.path.join(workdir, "sg.txt"))
        sg_rows, strip_ids = clean_skillgrp(sg_rows, o, log)
        new_sg, new_sn, skmap = generate(drops, sg_rows, o, log, rates, herbs)
        planned = set()
        for pairs in skmap.values():
            planned.update(pairs[0::2])

        # 4) npcgrp: self-check, then strip old pairs + add new ones
        ng = NpcGrp(open(os.path.join(workdir, "ng.dec"), "rb").read())
        ng.selfcheck()
        ng_out, patched, stripped = ng.rebuild(strip_ids, skmap)
        if stripped:
            log("npcgrp: removed %d icon pairs from a previous run" % stripped)
        log("npcgrp: %d NPCs patched (round-trip self-check OK)" % patched)
        open(os.path.join(workdir, "ng_out.dec"), "wb").write(ng_out)

        # 5) assemble + encrypt
        log("Assembling and encrypting output .dat files...")
        save_rows(os.path.join(workdir, "sg_out.txt"), sg_rows + new_sg)
        tc.asm("skillgrp.ddf", "sg_out.txt", "sg_out.dec")
        tc.encrypt("sg_out.dec", "SkillGrp.out")
        tc.encrypt("ng_out.dec", "npcgrp.out")
        outputs = [("npcgrp.out", "npcgrp.dat"), ("SkillGrp.out", "SkillGrp.dat")]
        for lang in langs:
            rows = clean_skillname(sn_rows[lang], strip_ids, planned, log,
                                   "SkillName-%s" % lang)
            save_rows(os.path.join(workdir, "sn_%s_out.txt" % lang), rows + new_sn)
            tc.asm("skillname-e.ddf", "sn_%s_out.txt" % lang, "sn_%s_out.dec" % lang)
            tc.encrypt("sn_%s_out.dec" % lang, "SkillName-%s.out" % lang)
            outputs.append(("SkillName-%s.out" % lang, "SkillName-%s.dat" % lang))

        if o.get("dump_json"):
            js = {str(k): {kk: [list(i) for i in vv] for kk, vv in v.items()}
                  for k, v in drops.items()}
            json.dump(js, open(os.path.join(outdir, "drops.json"), "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)
            json.dump({str(k): v for k, v in skmap.items()},
                      open(os.path.join(outdir, "skillmap.json"), "w"), indent=1)

        for src, dst in outputs:
            shutil.copy2(os.path.join(workdir, src), os.path.join(outdir, dst))
        log("")
        log("DONE — files written to: %s" % os.path.abspath(outdir))
        for _, dst in outputs:
            log("   %s  (%d KB)" % (dst, os.path.getsize(os.path.join(outdir, dst)) // 1024))
        log("")
        log("BACK UP the originals in your client's System folder, then copy")
        log("these files over them. The server needs no changes.")
        return 0
    finally:
        if o.get("keep_temp"):
            log("(temp files kept in %s)" % workdir)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        prog=APP, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="%s %s" % (APP, VERSION))
    p.add_argument("--npcs", help="datapack NPC folder (data/stats/npcs) or datapack root")
    p.add_argument("--system", help="client System folder (source .dat files)")
    p.add_argument("--out", default="output", help="output folder (default: ./output)")
    p.add_argument("--lang", help="SkillName language(s), comma separated "
                                  "(default: all SkillName-*.dat found)")
    p.add_argument("--rates-ini", help="server Rates.ini — shown chances/amounts "
                                       "get the same multipliers the server applies")
    g = p.add_argument_group("format options")
    g.add_argument("--base-id", type=int, help="first custom skill id (default 30001)")
    g.add_argument("--max-chars", type=int, help="max tooltip length in chars (default 1500)")
    g.add_argument("--max-line", type=int, help="max item line width, 0=off (default 0)")
    g.add_argument("--max-items", type=int, help="max items per list, 0=off (default 0)")
    g.add_argument("--min-chance", type=float, help="hide items below this chance %% (default 0)")
    g.add_argument("--chance-decimals", type=int, help="chance decimals (default 4)")
    g.add_argument("--title-drop", help='drop header title (default "Drop")')
    g.add_argument("--title-spoil", help='spoil header title (default "Spoil")')
    g.add_argument("--header-char", help='header padding char (default "=")')
    g.add_argument("--header-factor", type=float,
                   help="header width vs widest line, 1.0=equal (default 1.0)")
    g.add_argument("--trunc-suffix", help='text appended when capped (default "...(more)")')
    g.add_argument("--drop-icon", help="default icon.etc_adena_i00")
    g.add_argument("--spoil-icon", help="default icon.skill0254")
    p.add_argument("--dump-json", action="store_true", help="also write drops/skillmap json")
    p.add_argument("--keep-temp", action="store_true", help="keep the temp work folder")
    return p


def cli(argv):
    args = build_parser().parse_args(argv)
    if not args.npcs or not args.system:
        build_parser().error("--npcs and --system are required in CLI mode")
    opts = dict(
        npcs=args.npcs, system=args.system, out=args.out, rates_ini=args.rates_ini,
        langs=[l.strip().lower() for l in args.lang.split(",")] if args.lang else None,
        base_id=args.base_id, max_chars=args.max_chars, max_line=args.max_line,
        max_items=args.max_items, min_chance=args.min_chance,
        chance_decimals=args.chance_decimals, title_drop=args.title_drop,
        title_spoil=args.title_spoil, header_char=args.header_char,
        header_factor=args.header_factor,
        trunc_suffix=args.trunc_suffix, drop_icon=args.drop_icon,
        spoil_icon=args.spoil_icon, dump_json=args.dump_json or None,
        keep_temp=args.keep_temp or None,
    )
    try:
        return run_pipeline(opts, lambda s: print(s, flush=True))
    except ToolError as e:
        print("\nERROR: %s" % e, file=sys.stderr)
        return 1


# ---------------------------------------------------------------- GUI

CFG_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "L2DropSpoilGen", "config.json")


def load_cfg():
    try:
        return json.load(open(CFG_PATH, encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(d):
    try:
        os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
        json.dump(d, open(CFG_PATH, "w", encoding="utf-8"), indent=1)
    except Exception:
        pass  # settings persistence is best-effort


L10N = {
    "en": dict(
        subtitle="Drop/Spoil target icons — L2J Mobius datapacks · High Five clients",
        footer="Created by Rekiem Games Network — free community tool",
        npcs="Datapack NPCs folder", sys="Client System folder", out="Output folder",
        rates="Server Rates.ini (optional)", sn="SkillName languages",
        fmt="Format options", adv="Advanced (defaults are fine)", generate="Generate",
        no_sn="(no SkillName-*.dat found)",
        err_paths="Select the datapack NPCs folder and the client System folder",
        err_langs="Select at least one SkillName language",
        min_chance="Min chance %", max_items="Max items (0=all)",
        max_line="Max line width (0=off)", chance_decimals="Chance decimals",
        title_drop="Drop title", title_spoil="Spoil title",
        max_chars="Max tooltip chars", base_id="Base skill id",
        trunc_suffix="Truncation text", header_char="Header pad char",
        header_factor="Header width factor",
        h_npcs="Your L2J Mobius datapack's data/stats/npcs folder (the datapack root also works). Drop and spoil lists are read from these XMLs.",
        h_sys="The High Five client's System folder with the ORIGINAL npcgrp.dat, SkillGrp.dat and SkillName-*.dat.",
        h_out="Where the 3 patched .dat files are written. Nothing is written into the client directly — back up your originals and copy these over them.",
        h_rates="Optional: your server's Rates.ini. Shown chances/amounts then include the same multipliers the server applies (per-item ids, herb, raid, spoil). Leave empty to show raw datapack values.",
        h_sn="Which SkillName-<lang>.dat files to patch — pick the language(s) your client uses.",
        h_min_chance="Hide items whose final chance is below this % (0 = show everything).",
        h_max_items="Show at most this many items per list; the rest becomes '+N more...' (0 = no limit).",
        h_max_line="Maximum line width; longer item names are shortened with '...' (0 = no limit).",
        h_chance_decimals="Decimals shown in chances: 4 shows 0.0237%, 2 shows 0.02%.",
        h_title_drop="Header title shown above the drop list.",
        h_title_spoil="Header title shown above the spoil list.",
        h_max_chars="Hard cap for the whole tooltip text; very long lists (bosses) get cut.",
        h_base_id="First generated skill id (30001 is above retail's max 26073). Change only if your server already uses these client skill ids.",
        h_trunc_suffix="Text appended when a list is cut by the tooltip cap.",
        h_header_char="Padding character used to build the header line.",
        h_header_factor="Header width relative to the widest line (1.0 = equal, 0.95 = slightly shorter).",
    ),
    "es": dict(
        subtitle="Iconos de Drop/Spoil en el target — datapacks L2J Mobius · clientes High Five",
        footer="Creado por Rekiem Games Network — herramienta gratuita para la comunidad",
        npcs="Carpeta NPCs del datapack", sys="Carpeta System del cliente", out="Carpeta de salida",
        rates="Rates.ini del servidor (opcional)", sn="Idiomas SkillName",
        fmt="Opciones de formato", adv="Avanzado (los valores por defecto van bien)", generate="Generar",
        no_sn="(no se encontró SkillName-*.dat)",
        err_paths="Selecciona la carpeta NPCs del datapack y la carpeta System del cliente",
        err_langs="Selecciona al menos un idioma de SkillName",
        min_chance="Chance mínima %", max_items="Máx. items (0=todos)",
        max_line="Ancho máx. línea (0=off)", chance_decimals="Decimales del %",
        title_drop="Título Drop", title_spoil="Título Spoil",
        max_chars="Máx. caracteres tooltip", base_id="Id base de skill",
        trunc_suffix="Texto de recorte", header_char="Carácter de cabecera",
        header_factor="Factor ancho cabecera",
        h_npcs="Carpeta data/stats/npcs de tu datapack L2J Mobius (también vale la raíz del datapack). De estos XML se leen las listas de drop y spoil.",
        h_sys="Carpeta System del cliente High Five con los npcgrp.dat, SkillGrp.dat y SkillName-*.dat ORIGINALES.",
        h_out="Dónde se escriben los 3 .dat generados. No se escribe nada en el cliente directamente — haz backup de los originales y cópialos tú encima.",
        h_rates="Opcional: el Rates.ini de tu servidor. Los números mostrados incluirán los mismos multiplicadores que aplica el servidor (per-item, herbs, raid, spoil). Vacío = valores del datapack tal cual.",
        h_sn="Qué SkillName-<idioma>.dat parchear — marca el idioma que usa tu cliente.",
        h_min_chance="Oculta items cuyo chance final sea menor que este % (0 = mostrar todo).",
        h_max_items="Muestra como máximo estos items por lista; el resto sale como '+N more...' (0 = sin límite).",
        h_max_line="Ancho máximo de línea; los nombres largos se acortan con '...' (0 = sin límite).",
        h_chance_decimals="Decimales del porcentaje: 4 muestra 0.0237%, 2 muestra 0.02%.",
        h_title_drop="Título de la cabecera sobre la lista de drop.",
        h_title_spoil="Título de la cabecera sobre la lista de spoil.",
        h_max_chars="Tope duro del texto del tooltip; las listas muy largas (bosses) se recortan.",
        h_base_id="Primer id de skill generado (30001, por encima del máximo retail 26073). Cámbialo solo si tu servidor ya usa esos ids en el cliente.",
        h_trunc_suffix="Texto que se añade cuando la lista se recorta por el tope.",
        h_header_char="Carácter de relleno con el que se construye la cabecera.",
        h_header_factor="Ancho de la cabecera respecto a la línea más larga (1.0 = igualar, 0.95 = un poco más corta).",
    ),
    "pt": dict(
        subtitle="Ícones de Drop/Spoil no alvo — datapacks L2J Mobius · clientes High Five",
        footer="Criado por Rekiem Games Network — ferramenta gratuita para a comunidade",
        npcs="Pasta NPCs do datapack", sys="Pasta System do cliente", out="Pasta de saída",
        rates="Rates.ini do servidor (opcional)", sn="Idiomas SkillName",
        fmt="Opções de formato", adv="Avançado (os padrões funcionam bem)", generate="Gerar",
        no_sn="(nenhum SkillName-*.dat encontrado)",
        err_paths="Selecione a pasta NPCs do datapack e a pasta System do cliente",
        err_langs="Selecione pelo menos um idioma de SkillName",
        min_chance="Chance mínima %", max_items="Máx. itens (0=todos)",
        max_line="Largura máx. linha (0=off)", chance_decimals="Decimais do %",
        title_drop="Título Drop", title_spoil="Título Spoil",
        max_chars="Máx. caracteres tooltip", base_id="Id base da skill",
        trunc_suffix="Texto de corte", header_char="Caractere do cabeçalho",
        header_factor="Fator largura cabeçalho",
        h_npcs="Pasta data/stats/npcs do seu datapack L2J Mobius (a raiz do datapack também funciona). As listas de drop e spoil são lidas desses XMLs.",
        h_sys="Pasta System do cliente High Five com os npcgrp.dat, SkillGrp.dat e SkillName-*.dat ORIGINAIS.",
        h_out="Onde os 3 .dat gerados são escritos. Nada é escrito direto no cliente — faça backup dos originais e copie por cima você mesmo.",
        h_rates="Opcional: o Rates.ini do seu servidor. Os números mostrados incluirão os mesmos multiplicadores que o servidor aplica (per-item, herbs, raid, spoil). Vazio = valores do datapack.",
        h_sn="Quais SkillName-<idioma>.dat corrigir — marque o idioma que o seu cliente usa.",
        h_min_chance="Esconde itens com chance final abaixo deste % (0 = mostrar tudo).",
        h_max_items="Mostra no máximo esta quantidade de itens por lista; o resto vira '+N more...' (0 = sem limite).",
        h_max_line="Largura máxima da linha; nomes longos são encurtados com '...' (0 = sem limite).",
        h_chance_decimals="Decimais da chance: 4 mostra 0.0237%, 2 mostra 0.02%.",
        h_title_drop="Título do cabeçalho acima da lista de drop.",
        h_title_spoil="Título do cabeçalho acima da lista de spoil.",
        h_max_chars="Limite do texto do tooltip; listas muito longas (bosses) são cortadas.",
        h_base_id="Primeiro id de skill gerado (30001, acima do máximo retail 26073). Mude apenas se o seu servidor já usa esses ids no cliente.",
        h_trunc_suffix="Texto adicionado quando a lista é cortada pelo limite.",
        h_header_char="Caractere de preenchimento do cabeçalho.",
        h_header_factor="Largura do cabeçalho em relação à linha mais larga (1.0 = igual, 0.95 = um pouco mais curto).",
    ),
}

LANG_NAMES = {"en": "English", "es": "Español", "pt": "Português"}


def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    import threading
    import queue as _queue
    import locale

    root = tk.Tk()
    root.title("%s %s — Rekiem Games Network" % (APP, VERSION))
    root.minsize(660, 600)
    try:
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        root.iconbitmap(os.path.join(base, "icon.ico"))
    except Exception:
        pass  # icon is cosmetic — never block the GUI over it

    q = _queue.Queue()

    cfg = load_cfg()

    # UI language: saved preference, else auto-detect; switchable at runtime
    loc = ""
    try:
        loc = (locale.getlocale()[0] or "").lower()
    except Exception:
        pass
    auto = ("es" if loc.startswith(("es", "spanish")) else
            "pt" if loc.startswith(("pt", "portug")) else "en")
    cur = {"lang": cfg.get("lang") if cfg.get("lang") in L10N else auto}

    # state that survives language switches (preloaded from the saved config)
    v_npcs = tk.StringVar(value=cfg.get("npcs", ""))
    v_sys = tk.StringVar(value=cfg.get("system", ""))
    v_out = tk.StringVar(value=cfg.get("out") or os.path.abspath("output"))
    v_rates = tk.StringVar(value=cfg.get("rates", ""))
    saved_opts = cfg.get("opts", {})
    opt_vars = {k: tk.StringVar(value=str(saved_opts.get(k, DEFAULTS[k]))) for k in
                ("min_chance", "max_items", "max_line", "chance_decimals",
                 "title_drop", "title_spoil", "max_chars", "base_id",
                 "trunc_suffix", "header_char", "header_factor")}
    lang_vars, lang_state = {}, dict(cfg.get("sn", {}))
    ui = {"running": False, "logtext": []}

    def on_close():
        if not os.environ.get("L2DSG_SMOKE"):
            for l, v in lang_vars.items():
                lang_state[l] = v.get()
            save_cfg(dict(lang=cur["lang"], npcs=v_npcs.get(), system=v_sys.get(),
                          out=v_out.get(), rates=v_rates.get(),
                          opts={k: v.get() for k, v in opt_vars.items()},
                          sn=lang_state))
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    class Tip:
        def __init__(self, widget, text):
            self.w, self.text, self.tip = widget, text, None
            widget.bind("<Enter>", self.show)
            widget.bind("<Leave>", self.hide)

        def show(self, _e):
            if self.tip:
                return
            self.tip = tk.Toplevel(self.w)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry("+%d+%d" % (self.w.winfo_rootx() + 14,
                                             self.w.winfo_rooty() + self.w.winfo_height() + 6))
            tk.Label(self.tip, text=self.text, justify="left", wraplength=360,
                     background="#ffffe0", relief="solid", borderwidth=1,
                     padx=6, pady=4).pack()

        def hide(self, _e):
            if self.tip:
                self.tip.destroy()
                self.tip = None

    def help_mark(parent, text):
        lbl = ttk.Label(parent, text="?", foreground="#1a6fc4",
                        cursor="question_arrow", font=(None, 9, "bold"))
        Tip(lbl, text)
        return lbl

    def refresh_langs():
        lf = ui.get("lang_frame")
        if not lf:
            return
        T = L10N[cur["lang"]]
        for l, v in lang_vars.items():
            lang_state[l] = v.get()
        for w in lf.winfo_children():
            w.destroy()
        lang_vars.clear()
        d = v_sys.get()
        if os.path.isdir(d):
            for lang in detect_langs(d):
                var = tk.BooleanVar(value=lang_state.get(lang, True))
                lang_vars[lang] = var
                ttk.Checkbutton(lf, text="SkillName-%s" % lang,
                                variable=var).pack(side="left", padx=2)
            if not lang_vars:
                ttk.Label(lf, text=T["no_sn"]).pack(side="left")

    v_sys.trace_add("write", lambda *a: refresh_langs())

    def build():
        T = L10N[cur["lang"]]
        if ui.get("frame"):
            ui["frame"].destroy()
        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)
        ui["frame"] = frm

        # top bar: subtitle + UI language selector
        top = ttk.Frame(frm)
        top.grid(row=0, column=0, columnspan=4, sticky="we", pady=(0, 8))
        ttk.Label(top, text=T["subtitle"], font=(None, 9, "bold")).pack(side="left")
        combo = ttk.Combobox(top, values=[LANG_NAMES[c] for c in ("en", "es", "pt")],
                             width=10, state="readonly")
        combo.set(LANG_NAMES[cur["lang"]])
        combo.pack(side="right")
        ttk.Label(top, text="🌐").pack(side="right", padx=(0, 3))

        def on_lang(_e):
            cur["lang"] = {v: k for k, v in LANG_NAMES.items()}[combo.get()]
            build()
        combo.bind("<<ComboboxSelected>>", on_lang)

        def pick_row(row, label, help_text, var, isdir=True):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(frm, textvariable=var, width=58).grid(row=row, column=1,
                                                            sticky="we", padx=4)

            def browse():
                d = filedialog.askdirectory() if isdir else filedialog.askopenfilename(
                    filetypes=[("Rates.ini", "*.ini"), ("*", "*.*")])
                if d:
                    var.set(d)
            ttk.Button(frm, text="...", width=3, command=browse).grid(row=row, column=2)
            help_mark(frm, help_text).grid(row=row, column=3, padx=(4, 0))

        pick_row(1, T["npcs"], T["h_npcs"], v_npcs)
        pick_row(2, T["sys"], T["h_sys"], v_sys)
        pick_row(3, T["out"], T["h_out"], v_out)
        pick_row(4, T["rates"], T["h_rates"], v_rates, isdir=False)

        ttk.Label(frm, text=T["sn"]).grid(row=5, column=0, sticky="w", pady=2)
        ui["lang_frame"] = ttk.Frame(frm)
        ui["lang_frame"].grid(row=5, column=1, sticky="w")
        help_mark(frm, T["h_sn"]).grid(row=5, column=3, padx=(4, 0))
        refresh_langs()

        optf = ttk.LabelFrame(frm, text=T["fmt"], padding=6)
        optf.grid(row=6, column=0, columnspan=4, sticky="we", pady=(6, 2))
        advf = ttk.LabelFrame(frm, text=T["adv"], padding=6)
        advf.grid(row=7, column=0, columnspan=4, sticky="we", pady=(2, 6))

        def opt(parent, rowcol, key, width=8):
            r, c = rowcol
            ttk.Label(parent, text=T[key]).grid(row=r, column=c * 3, sticky="w",
                                                padx=(0, 3), pady=2)
            ttk.Entry(parent, textvariable=opt_vars[key], width=width).grid(
                row=r, column=c * 3 + 1, sticky="w")
            help_mark(parent, T["h_" + key]).grid(row=r, column=c * 3 + 2,
                                                  sticky="w", padx=(2, 12))

        opt(optf, (0, 0), "min_chance")
        opt(optf, (0, 1), "max_items")
        opt(optf, (0, 2), "max_line")
        opt(optf, (1, 0), "chance_decimals")
        opt(optf, (1, 1), "title_drop", 12)
        opt(optf, (1, 2), "title_spoil", 12)
        opt(advf, (0, 0), "max_chars")
        opt(advf, (0, 1), "base_id")
        opt(advf, (0, 2), "trunc_suffix", 12)
        opt(advf, (1, 0), "header_char")
        opt(advf, (1, 1), "header_factor")

        btn = ttk.Button(frm, text=T["generate"], command=start)
        btn.grid(row=8, column=0, columnspan=4, pady=6)
        if ui["running"]:
            btn.configure(state="disabled")
        ui["btn"] = btn

        logbox = scrolledtext.ScrolledText(frm, height=14, state="disabled",
                                           font=("Consolas", 9))
        logbox.grid(row=9, column=0, columnspan=4, sticky="nsew", pady=(6, 0))
        if ui["logtext"]:
            logbox.configure(state="normal")
            logbox.insert("end", "\n".join(ui["logtext"]) + "\n")
            logbox.see("end")
            logbox.configure(state="disabled")
        ui["logbox"] = logbox
        frm.rowconfigure(9, weight=1)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text=T["footer"], foreground="#777777",
                  font=(None, 8)).grid(row=10, column=0, columnspan=4, pady=(6, 0))

    def log(s):
        q.put(s)

    def poll():
        try:
            while True:
                s = q.get_nowait()
                if s is StopIteration:
                    ui["running"] = False
                    if ui.get("btn"):
                        ui["btn"].configure(state="normal")
                else:
                    ui["logtext"].append(str(s))
                    lb = ui.get("logbox")
                    if lb:
                        lb.configure(state="normal")
                        lb.insert("end", str(s) + "\n")
                        lb.see("end")
                        lb.configure(state="disabled")
        except _queue.Empty:
            pass
        except tk.TclError:
            pass
        root.after(100, poll)

    def num(key, cast):
        try:
            return cast(opt_vars[key].get())
        except ValueError:
            raise ToolError("Invalid value for %s: %r" % (key, opt_vars[key].get()))

    def work(opts):
        ok = False
        try:
            run_pipeline(opts, log)
            ok = True
        except ToolError as e:
            log("\nERROR: %s" % e)
        except Exception:
            log("\nUNEXPECTED ERROR:\n" + traceback.format_exc())
        finally:
            q.put(StopIteration)
        if ok:  # show the generated files to the user
            try:
                os.startfile(os.path.abspath(opts["out"]))
            except Exception:
                pass

    def start():
        T = L10N[cur["lang"]]
        try:
            langs = [l for l, v in lang_vars.items() if v.get()]
            if not v_npcs.get() or not v_sys.get():
                raise ToolError(T["err_paths"])
            if not langs:
                raise ToolError(T["err_langs"])
            opts = dict(
                npcs=v_npcs.get(), system=v_sys.get(), out=v_out.get(), langs=langs,
                rates_ini=v_rates.get().strip() or None,
                base_id=num("base_id", int), max_chars=num("max_chars", int),
                max_line=num("max_line", int), max_items=num("max_items", int),
                min_chance=num("min_chance", float),
                chance_decimals=num("chance_decimals", int),
                title_drop=opt_vars["title_drop"].get(),
                title_spoil=opt_vars["title_spoil"].get(),
                trunc_suffix=opt_vars["trunc_suffix"].get(),
                header_char=opt_vars["header_char"].get() or "=",
                header_factor=num("header_factor", float),
            )
        except ToolError as e:
            messagebox.showerror(APP, str(e))
            return
        ui["running"] = True
        ui["logtext"] = []
        ui["btn"].configure(state="disabled")
        lb = ui["logbox"]
        lb.configure(state="normal")
        lb.delete("1.0", "end")
        lb.configure(state="disabled")
        threading.Thread(target=work, args=(opts,), daemon=True).start()

    build()
    poll()
    if os.environ.get("L2DSG_SMOKE"):  # automated smoke test: open + close
        root.after(1500, root.destroy)
    root.mainloop()
    return 0


# ---------------------------------------------------------------- entry

def _attach_console():
    """Windowed (no-console) exe launched with CLI args from a terminal:
    attach to the parent console so prints are visible; otherwise open one."""
    if sys.platform == "win32" and getattr(sys, "frozen", False) and sys.stdout is None:
        import ctypes
        k = ctypes.windll.kernel32
        if not k.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            k.AllocConsole()
        sys.stdout = open("CONOUT$", "w", buffering=1)
        sys.stderr = open("CONOUT$", "w", buffering=1)


def main():
    if len(sys.argv) > 1:
        _attach_console()
        return cli(sys.argv[1:])
    try:
        return gui()
    except Exception:
        print("GUI unavailable, use CLI mode:\n")
        build_parser().print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
