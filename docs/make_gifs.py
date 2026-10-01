"""Render the flow GIFs used in the README and the post.  python docs/make_gifs.py [a] [b] [c]

Three visual treatments of the same story:
  A  pipeline map     - boxes and arrows, a card travels the route
  B  sequence diagram - lifelines with a scrolling message log
  C  gate stream      - cards pass a gate that stamps a verdict, plus a kill switch

Story: the caseworker asks for a draft. The agent reads the case file (allowed), a hijacked
step tries approve_payout (denied), then the draft needs a human before it runs (approved).
Pure Pillow, no network. Frames are drawn 2x and downsampled for smooth edges.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S, W, H, FPS = 2, 800, 450, 12
OUT = Path(__file__).parent / "options"

BG = (250, 250, 247)
INK = (28, 32, 38)
MUTED = (100, 106, 116)
LINE = (196, 200, 206)
BOX = (255, 255, 255)
SLAB = (236, 238, 241)
GREEN, RED, AMBER, BLUE = (26, 122, 56), (186, 36, 36), (170, 100, 0), (36, 84, 168)
T_GREEN, T_RED, T_AMBER, T_BLUE = (224, 243, 230), (250, 226, 226), (252, 239, 210), (224, 235, 250)
TINT = {GREEN: T_GREEN, RED: T_RED, AMBER: T_AMBER, BLUE: T_BLUE, INK: SLAB, MUTED: SLAB}
NAMED = [BG, INK, MUTED, LINE, BOX, SLAB, GREEN, RED, AMBER, BLUE, T_GREEN, T_RED, T_AMBER, T_BLUE]

_fonts = {}


def font(size, bold=False, mono=False):
    key = (size, bold, mono)
    if key not in _fonts:
        name = "DejaVuSansMono" if mono else "DejaVuSans"
        if bold:
            name += "-Bold"
        _fonts[key] = ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}.ttf", int(size * S))
    return _fonts[key]


def lerp(a, b, p):
    return a + (b - a) * p


def ease(p):
    return p * p * (3 - 2 * p)


class Canvas:
    def __init__(self):
        self.img = Image.new("RGB", (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.img)

    def rect(self, x0, y0, x1, y1, fill=BOX, outline=LINE, r=8, width=2):
        self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], r * S, fill=fill,
                                 outline=outline, width=width * S if outline else 0)

    def text(self, x, y, s, size=15, fill=INK, bold=False, mono=False, anchor="lm", bg=None):
        if bg is not None:
            w = self.width(s, size, bold, mono)
            left = x - w / 2 if anchor[0] == "m" else x
            self.d.rectangle([(left - 4) * S, (y - size * 0.7) * S, (left + w + 4) * S, (y + size * 0.7) * S], fill=bg)
        self.d.text((x * S, y * S), s, font=font(size, bold, mono), fill=fill, anchor=anchor)

    def width(self, s, size=15, bold=False, mono=False):
        return font(size, bold, mono).getlength(s) / S

    def line(self, pts, fill=LINE, width=2, dashed=False):
        pts = [(x * S, y * S) for x, y in pts]
        if not dashed:
            self.d.line(pts, fill=fill, width=width * S, joint="curve")
            return
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            n = max(1, int(length / (7 * S)))
            for i in range(0, n, 2):
                a, b = i / n, min((i + 1) / n, 1)
                self.d.line([(lerp(x0, x1, a), lerp(y0, y1, a)), (lerp(x0, x1, b), lerp(y0, y1, b))],
                            fill=fill, width=width * S)

    def arrowhead(self, x, y, direction, fill, size=8):
        x, y, s = x * S, y * S, size * S
        pts = {"r": [(x, y), (x - s, y - s * 0.6), (x - s, y + s * 0.6)],
               "l": [(x, y), (x + s, y - s * 0.6), (x + s, y + s * 0.6)],
               "d": [(x, y), (x - s * 0.6, y - s), (x + s * 0.6, y - s)],
               "u": [(x, y), (x - s * 0.6, y + s), (x + s * 0.6, y + s)]}[direction]
        self.d.polygon(pts, fill=fill)

    def circle(self, x, y, r, fill, outline=None, width=2):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill,
                       outline=outline, width=width * S if outline else 0)

    def pill(self, cx, cy, s, color, size=14):
        w = self.width(s, size, bold=True) + 18
        self.rect(cx - w / 2, cy - 12, cx + w / 2, cy + 12, fill=color, outline=color, r=12, width=2)
        self.text(cx, cy, s, size, fill=BOX, bold=True, anchor="mm")

    def person(self, cx, cy, color=INK):
        self.circle(cx, cy - 8, 7, color)
        self.d.pieslice([(cx - 13) * S, (cy + 1) * S, (cx + 13) * S, (cy + 27) * S], 180, 360, fill=color)

    def done(self):
        return self.img.resize((W, H), Image.LANCZOS)


def run(steps, state, draw, fps=FPS):
    frames = []
    for dur, fn in steps:
        n = round(dur * fps)
        if n == 0:
            fn(1.0, state)
            continue
        for i in range(n):
            fn((i + 1) / n, state)
            frames.append(draw(state))
    return frames


def save(frames, path):
    """One shared palette for all frames: no colour flicker, small files. The named UI colours
    are forced into the palette so flat fills stay exact instead of drifting muddy."""
    sample = frames[:: max(1, len(frames) // 16)]
    sheet = Image.new("RGB", (W, H * len(sample)))
    for i, f in enumerate(sample):
        sheet.paste(f, (0, i * H))
    pal_img = sheet.quantize(colors=200, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = pal_img.getpalette()
    for i, rgb in enumerate(NAMED):
        pal[i * 3:i * 3 + 3] = list(rgb)
    pal_img.putpalette(pal)
    q = [f.quantize(palette=pal_img, dither=Image.Dither.NONE) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=int(1000 / FPS), loop=0, optimize=True, disposal=1)
    print(f"{path.name}: {len(frames)} frames, {path.stat().st_size / 1024:.0f} KB")


def hold(d, **kw):
    return (d, lambda p, s: s.update(kw))


def once(**kw):
    return (0, lambda p, s: s.update(kw))


def path_pos(pts, p):
    segs = [((x0, y0), (x1, y1), ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5) for (x0, y0), (x1, y1) in zip(pts, pts[1:])]
    d = ease(p) * sum(g[2] for g in segs)
    for (x0, y0), (x1, y1), L in segs:
        if d <= L or (x1, y1) == segs[-1][1]:
            t = 0 if L == 0 else min(d / L, 1)
            return lerp(x0, x1, t), lerp(y0, y1, t)
        d -= L


# =============================== A: pipeline map ===============================

A_CASE, A_AGENT, A_GATE, A_TOOLS = (20, 148), (190, 320), (390, 530), (600, 760)
A_ROW = 194
A_RET = [(680, 212), (680, 240), (255, 240), (255, 216)]


def draw_a(s):
    c = Canvas()
    c.text(24, 26, "Every proposal goes through the gate", 21, bold=True)
    lit = s["lit"]

    def node(box, title, sub, key):
        col = lit.get(key)
        c.rect(box[0], 122, box[1], 212, fill=TINT[col] if col else BOX, outline=col or LINE, width=3 if col else 2)
        c.text((box[0] + box[1]) / 2, 142, title, 17, bold=True, anchor="mm")
        c.text((box[0] + box[1]) / 2, 164, sub, 14, fill=MUTED, anchor="mm")

    node(A_CASE, "Caseworker", "asks for a draft", "case")
    node(A_AGENT, "Agent", "model proposes", "agent")
    node(A_TOOLS, "Tools", "read / calc / draft", "tools")

    g = lit.get("gate")
    c.rect(A_GATE[0], 118, A_GATE[1], 214, fill=TINT[g] if g else SLAB, outline=g or INK, width=3)
    c.text(460, 138, "Gate", 19, bold=True, anchor="mm")
    if s["badge"]:
        c.pill(460, 164, s["badge"][0], s["badge"][1], 15)
    else:
        c.text(460, 164, "no model in here", 14, fill=MUTED, anchor="mm")

    for x0, x1 in ((A_CASE[1], A_AGENT[0]), (A_AGENT[1], A_GATE[0]), (A_GATE[1], A_TOOLS[0])):
        c.line([(x0, A_ROW), (x1 - 8, A_ROW)])
        c.arrowhead(x1 - 1, A_ROW, "r", LINE)
    c.line(A_RET, dashed=True)
    c.arrowhead(255, 214, "u", LINE)
    c.text(340, 254, "result back to the agent", 13, fill=MUTED, anchor="mm")

    ac = s["approval"]
    col = {None: LINE, "wait": AMBER, "ok": GREEN}[ac]
    c.rect(372, 44, 548, 98, fill=TINT[col] if ac else BOX, outline=col, width=3 if ac else 2)
    c.person(404, 62, INK)
    c.text(478, 62, "Caseworker", 15, bold=True, anchor="mm")
    c.text(478, 83, {None: "approval station", "wait": "reviewing...", "ok": "approved"}[ac], 14,
           fill=col if ac else MUTED, anchor="mm", bold=bool(ac))
    c.line([(460, 98), (460, 118)], dashed=True)

    bl = lit.get("bin")
    c.rect(390, 274, 530, 314, fill=TINT[bl] if bl else BOX, outline=bl or LINE, width=3 if bl else 2)
    c.text(460, 294, f"Blocked   x {s['denied']}", 16, bold=True, fill=RED if s["denied"] else MUTED, anchor="mm")
    c.line([(460, 214), (460, 274)], dashed=True)

    c.text(400, 338, s["caption"], 17, anchor="mm")

    c.rect(24, 354, 776, 448, fill=BOX)
    c.text(38, 368, "Audit log (records the why, not just the what)", 14, bold=True, fill=MUTED)
    for i, (tool, verdict, why, col) in enumerate(s["audit"]):
        y = 389 + i * 16
        c.text(38, y, f"{i + 1}", 13, fill=MUTED, mono=True)
        c.text(62, y, tool, 13, mono=True)
        c.text(330, y, verdict, 13, fill=col, bold=True, mono=True)
        c.text(450, y, why, 13, fill=MUTED, mono=True)

    if s["packet"]:
        x, y, label, col = s["packet"]
        w = c.width(label, 13, mono=True) + 22
        c.rect(x - w / 2, y - 14, x + w / 2, y + 14, fill=BOX, outline=col, width=3, r=10)
        c.text(x, y, label, 13, mono=True, anchor="mm")
    if s["dot"]:
        c.circle(*s["dot"], 8, GREEN)
    return c.done()


def a_steps():
    steps = []
    add = steps.append

    def move(pts, label, col=INK):
        add((0.7, lambda p, s: s.update(packet=(*path_pos(pts, p), label, col))))

    def verdict(kind):
        col = {"ALLOW": GREEN, "DENY": RED, "HOLD": AMBER}[kind]
        add(once(badge=(kind, col), lit={"gate": col}))
        add(hold(0.9))

    def log(tool, kind, why):
        col = {"ALLOW": GREEN, "DENY": RED, "HOLD": AMBER, "APPROVED": GREEN}[kind]
        add((0, lambda p, s: s["audit"].append((tool, kind.lower(), why, col))))

    def ret():
        add(once(packet=None, lit={"tools": GREEN}))
        add((0.9, lambda p, s: s.update(dot=path_pos(A_RET, p))))
        add(once(dot=None, lit={"agent": BLUE}))

    to_gate = [(322, A_ROW), (388, A_ROW)]
    to_tools = [(534, A_ROW), (598, A_ROW)]

    add(once(caption="Caseworker: draft an eligibility summary for case C-1003", lit={"case": BLUE}))
    add(hold(1.3))
    add((0.6, lambda p, s: s.update(packet=(lerp(148, 190, ease(p)), A_ROW, "C-1003", BLUE))))
    add(once(packet=None, lit={"agent": BLUE}))

    add(once(caption="Agent proposes: read_client_file"))
    move(to_gate, "read_client_file")
    add(once(caption="Gate: declared tool, correct case. Allow."))
    verdict("ALLOW")
    log("read_client_file(C-1003)", "ALLOW", "needs intake notes first")
    add(once(badge=None, lit={}, caption="Tool runs. Result goes back to the agent."))
    move(to_tools, "read_client_file", GREEN)
    ret()
    add(once(lit={}))

    add(once(caption="A hijacked step: the case notes said to approve a payout", lit={"agent": RED}))
    add(hold(0.7))
    move(to_gate, "approve_payout", RED)
    add(once(caption="Gate: not in this agent's action space. Deny."))
    verdict("DENY")
    log("approve_payout", "DENY", "not in action_space (default-deny)")
    add((0.6, lambda p, s: s.update(packet=(460, lerp(A_ROW, 294, ease(p)), "approve_payout", RED))))
    add(once(packet=None, denied=1, lit={"bin": RED}, caption="Blocked. Nothing ran. It is in the log."))
    add(hold(1.3))
    add(once(badge=None, lit={}))

    add(once(caption="Agent proposes: draft_determination_letter"))
    move(to_gate, "draft_determination_letter")
    add(once(caption="Gate: this tool needs a human. Hold."))
    verdict("HOLD")
    log("draft_determination_letter", "HOLD", "approval required by agent file")
    add(once(caption="Caseworker sees the proposed action and decides"))
    add((0.6, lambda p, s: s.update(packet=(460, lerp(A_ROW, 71, ease(p)), "draft_determination_letter", AMBER))))
    add(once(packet=None, approval="wait"))
    add(hold(1.4))
    add(once(approval="ok", caption="Approved by the caseworker. Now it may run."))
    add(hold(1.1))
    log("draft_determination_letter", "APPROVED", "human approved, then it ran")
    add(once(badge=("ALLOW", GREEN), lit={"gate": GREEN}))
    move(to_tools, "draft_determination_letter", GREEN)
    ret()
    add(once(lit={"case": BLUE}, badge=None, approval=None, caption="Draft ready for the caseworker. Nothing was sent."))
    add(hold(2.6))
    add(once(lit={}))
    return steps


def make_a():
    s = dict(caption="", packet=None, badge=None, approval=None, lit={}, audit=[], denied=0, dot=None)
    return run(a_steps(), s, draw_a)


# =============================== B: sequence diagram ===============================

B_COLS = {"case": 70, "agent": 250, "gate": 470, "tools": 630, "audit": 745}
B_HEAD = {"case": "Caseworker", "agent": "Agent", "gate": "Gate", "tools": "Tools", "audit": "Audit"}
B_W = {"case": 116, "agent": 96, "gate": 96, "tools": 96, "audit": 84}
B_ROW = 34
MID_AG = (B_COLS["agent"] + B_COLS["gate"]) / 2

# src, dst, label, colour, dashed, label_x (None = midpoint)
B_ROWS = [
    ("case", "agent", "draft summary, C-1001", BLUE, False, None),
    ("agent", "gate", "read_client_file(C-1001)", INK, False, None),
    ("gate", "tools", "ALLOW", GREEN, False, None),
    ("tools", "agent", "result", MUTED, True, MID_AG),
    ("gate", "audit", "log: allow", BLUE, False, None),
    ("agent", "gate", "approve_payout", INK, False, None),
    ("gate", "agent", "DENY: not declared", RED, False, None),
    ("gate", "audit", "log: deny", BLUE, False, None),
    ("agent", "gate", "draft_determination_letter", INK, False, None),
    ("gate", "case", "HOLD: human must approve", AMBER, False, MID_AG),
    ("case", "gate", "approved", GREEN, False, MID_AG),
    ("gate", "tools", "ALLOW", GREEN, False, None),
    ("tools", "agent", "draft text", MUTED, True, MID_AG),
    ("gate", "audit", "log: approved by human", BLUE, False, None),
    ("agent", "case", "draft ready, nothing sent", BLUE, False, None),
]


def draw_b(s):
    c = Canvas()
    for k, x in B_COLS.items():
        c.line([(x, 56), (x, 448)], fill=INK if k == "gate" else LINE, width=3 if k == "gate" else 2, dashed=True)
    for i, prog in enumerate(s["rows"]):
        if prog <= 0:
            continue
        src, dst, label, col, dashed, lx = B_ROWS[i]
        y = 90 + i * B_ROW - s["cam"]
        x0, x1 = B_COLS[src], B_COLS[dst]
        sign = 1 if x1 > x0 else -1
        tip = lerp(x0, x1, ease(min(prog, 1)))
        c.line([(x0, y), (tip - sign * 6, y)], fill=col, width=3, dashed=dashed)
        c.circle(x0, y, 4, col)
        if prog >= 0.95:
            c.arrowhead(x1, y, "r" if sign > 0 else "l", col, 9)
            c.text(lx or (x0 + x1) / 2, y - 13, label, 14, fill=col, bold=col != MUTED, anchor="mm", bg=BG)
    c.d.rectangle([0, 0, W * S, 54 * S], fill=BG)
    c.line([(0, 54), (W, 54)], fill=LINE, width=2)
    for k, x in B_COLS.items():
        w, gate = B_W[k], k == "gate"
        c.rect(x - w / 2, 8, x + w / 2, 44, fill=SLAB if gate else BOX, outline=INK if gate else LINE, width=3 if gate else 2)
        c.text(x, 26, B_HEAD[k], 16, bold=True, anchor="mm")
    if s["note"]:
        c.rect(24, 400, 776, 440, fill=BOX, outline=LINE)
        c.text(400, 420, s["note"], 16, anchor="mm")
    return c.done()


def b_steps():
    steps = []
    notes = {0: "Caseworker asks for a draft.",
             1: "Agent proposes a tool call. Nothing runs yet.",
             2: "The gate checks it in plain code and allows it.",
             5: "A hijacked step: the case notes told the model to approve a payout.",
             6: "Denied. That tool was never declared for this agent.",
             8: "Back on task: draft the letter.",
             9: "This tool needs a human, so the gate holds the call.",
             10: "Caseworker approves the proposed action.",
             13: "Every decision is logged with the agent's reason.",
             14: "Done. A draft exists. Nothing was sent."}
    for i in range(len(B_ROWS)):
        def grow(p, s, i=i):
            s["rows"][i] = p
            s["cam"] = lerp(s["cam"], max(0, 90 + i * B_ROW - 300), 0.5)
            if i in notes:
                s["note"] = notes[i]
        steps.append((0.6, grow))
        steps.append(hold(0.85 if i in notes else 0.25))
    steps.append(hold(2.4))
    return steps


def make_b():
    s = dict(rows=[0] * len(B_ROWS), cam=0.0, note="")
    return run(b_steps(), s, draw_b)


# =============================== C: gate stream ===============================

C_LANE, C_X = 228, 360
C_CARDS = [
    ("read_client_file", "ALLOW", "declared, right case"),
    ("calculate_income_threshold", "ALLOW", "declared, deterministic"),
    ("approve_payout", "DENY", "not in action_space"),
    ("read_client_file(C-2000)", "DENY", "outside this case"),
    ("draft_determination_letter", "HOLD", "human must approve"),
]
VC = {"ALLOW": GREEN, "DENY": RED, "HOLD": AMBER, "APPROVED": GREEN}


def draw_c(s):
    c = Canvas()
    c.text(24, 26, s["caption"], 18, bold=True)
    kill = s["killed"]
    c.rect(650, 10, 780, 42, fill=RED if kill else BOX, outline=RED, width=2)
    c.text(715, 26, "Kill switch", 15, bold=True, fill=BOX if kill else RED, anchor="mm")

    c.rect(20, 140, 150, 260, fill=SLAB if kill else T_BLUE, outline=MUTED if kill else BLUE, width=3)
    c.text(85, 174, "Agent", 18, bold=True, anchor="mm")
    c.text(85, 196, "HALTED" if kill else "model proposes", 14, fill=RED if kill else MUTED, bold=kill, anchor="mm")

    c.rect(600, 140, 780, 260, fill=T_GREEN if s["tools_lit"] else BOX,
           outline=GREEN if s["tools_lit"] else LINE, width=3 if s["tools_lit"] else 2)
    c.text(690, 174, "Tools", 18, bold=True, anchor="mm")
    c.text(690, 196, "read / calc / draft", 14, fill=MUTED, anchor="mm")

    hs = s["human"]
    col = {None: LINE, "wait": AMBER, "ok": GREEN}[hs]
    c.line([(408, 130), (424, 130), (424, 83), (440, 83)], fill=col, width=3 if hs else 2, dashed=True)
    c.rect(440, 54, 620, 112, fill=TINT[col] if hs else BOX, outline=col, width=3 if hs else 2)
    c.person(474, 72, INK)
    c.text(550, 72, "Caseworker", 15, bold=True, anchor="mm")
    c.text(550, 94, {None: "approval station", "wait": "reviewing...", "ok": "approved"}[hs], 14,
           fill=col if hs else MUTED, bold=bool(hs), anchor="mm")

    for x0, x1 in ((150, 312), (408, 598)):
        c.line([(x0, C_LANE), (x1 - 8, C_LANE)], dashed=True)
        c.arrowhead(x1 - 1, C_LANE, "r", LINE)
    c.rect(C_X - 48, 100, C_X + 48, 296, fill=SLAB, outline=INK, width=3, r=6)
    c.text(C_X, 124, "Gate", 18, bold=True, anchor="mm")
    c.text(C_X, 144, "no model", 13, fill=MUTED, anchor="mm")

    c.rect(270, 318, 450, 358, fill=T_RED if s["denied"] else BOX, outline=RED if s["denied"] else LINE, width=2)
    c.text(360, 338, f"Blocked   x {s['denied']}", 16, bold=True, fill=RED if s["denied"] else MUTED, anchor="mm")

    x = 24
    for label, n, colr in (("Allowed", s["allowed"], GREEN), ("Denied", s["denied"], RED), ("Needed a human", s["held"], AMBER)):
        t = f"{label}  {n}"
        w = c.width(t, 15, bold=True) + 22
        c.rect(x, 370, x + w, 400, fill=TINT[colr] if n else BOX, outline=colr if n else LINE, width=2, r=15)
        c.text(x + w / 2, 385, t, 15, bold=True, fill=colr if n else MUTED, anchor="mm")
        x += w + 8
    c.text(24, 426, s["ticker"] or "last decision: none yet", 14, fill=MUTED, mono=True)

    for cx, cy, label, colr, badge in s["cards"]:
        w = c.width(label, 13, mono=True) + 24
        c.rect(cx - w / 2, cy - 15, cx + w / 2, cy + 15, fill=BOX, outline=colr, width=3, r=10)
        c.text(cx, cy, label, 13, mono=True, anchor="mm")
        if badge:
            c.pill(cx, cy - 30, badge, VC[badge], 13)
    return c.done()


def c_steps():
    steps = []
    add = steps.append

    def travel(label, pts, col, dur):
        def fn(p, s):
            x, y = path_pos(pts, p)
            s["cards"] = [(x, y, label, col, None)]
        add((dur, fn))

    def tick(label, kind, why):
        return f"{label:<28}{kind:<9}{why}"

    add(once(caption="Each proposal is a card. The gate stamps it."))
    add(hold(1.2))
    for label, kind, why in C_CARDS:
        col = VC[kind]
        add(once(caption=f"Agent proposes: {label.split('(')[0]}", cards=[]))
        travel(label, [(240, C_LANE), (C_X, C_LANE)], INK, 0.8)
        add(once(cards=[(C_X, C_LANE, label, col, kind)],
                 caption={"ALLOW": "Allowed by the rules. Passing through.",
                          "DENY": "Denied. It never reaches the tools.",
                          "HOLD": "Held. This one needs a human."}[kind]))
        add(hold(0.8))
        if kind == "ALLOW":
            add((0, lambda p, s, w=why, l=label: s.update(allowed=s["allowed"] + 1, ticker=tick(l, "allow", w))))
            travel(label, [(C_X, C_LANE), (485, C_LANE)], GREEN, 0.8)
            add(once(cards=[], tools_lit=True))
            add(hold(0.5))
            add(once(tools_lit=False))
        elif kind == "DENY":
            add((0, lambda p, s, w=why, l=label: s.update(denied=s["denied"] + 1, ticker=tick(l, "deny", w))))
            travel(label, [(C_X, C_LANE), (C_X, 338)], RED, 0.6)
            add(hold(0.7))
            add(once(cards=[]))
        else:
            add((0, lambda p, s, w=why, l=label: s.update(held=s["held"] + 1, ticker=tick(l, "hold", w))))
            add(once(human="wait", caption="Caseworker reviews the proposed action."))
            add(hold(1.5))
            add(once(human="ok", caption="Approved. Now the call may run.",
                     cards=[(C_X, C_LANE, label, GREEN, "APPROVED")]))
            add(hold(1.0))
            travel(label, [(C_X, C_LANE), (485, C_LANE)], GREEN, 0.8)
            add(once(cards=[], tools_lit=True))
            add((0, lambda p, s: s.update(allowed=s["allowed"] + 1, ticker=tick("draft_determination_letter", "ran", "after human approval"))))
            add(hold(0.6))
            add(once(tools_lit=False, caption="Draft ready. Nothing was sent."))
            add(hold(1.6))
    add(once(caption="And an operator can stop everything, any time."))
    add(hold(1.2))
    add(once(killed=True, caption="Kill switch pulled. Nothing else can run.", ticker=tick("(all tool calls)", "halt", "kill switch")))
    add(hold(2.8))
    return steps


def make_c():
    s = dict(caption="", cards=[], allowed=0, denied=0, held=0, human=None, tools_lit=False, killed=False, ticker="")
    return run(c_steps(), s, draw_c)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    which = sys.argv[1:] or ["a", "b", "c"]
    for key, fn, name in (("a", make_a, "option-a-pipeline.gif"), ("b", make_b, "option-b-sequence.gif"),
                          ("c", make_c, "option-c-gate-stream.gif")):
        if key in which:
            save(fn(), OUT / name)
