"""Figures of docs/mark_formulas.tex. Every plotted value is read from a local result file; nothing is typed in and no
simulation is run here (the charts of the proposal's mark score the raw outputs of the final run, data/scen/final, with the
formulas of sim/final/score_final.py). One function per figure; each docstring names the files and columns it reads. A missing
file or column stops that figure with an error (no approximation).

Each figure is drawn at the width docs/paper_core.tex places it (or should place it: see the widths below), so its type is the same size on every page. Share of the
text width (W = 6.6 in): adl_timeline, crash_mark 1.00 | skhx_0727 0.94 | cutback_how 0.92 | closed_attacks 0.87 |
cutback, normal_days 0.80 | eligibility, six_markets 0.70 | capital, mark_changes 0.68 | feed_age 0.66 | attacks, headline_crash 0.60 |
headline 0.55.
If a width changes in the .tex, change the figure's figsize here (the note beside it) and redraw.

Usage: python sim/figs.py            all figures -> docs/figs/NAME.pdf (vector)
       python sim/figs.py NAME ...   only these
       PNG=DIR python sim/figs.py    also a 200 dpi PNG preview of each in DIR
       TITLES=0                      leave the bold in-figure title out (when the LaTeX caption carries the message)
Needs polars and matplotlib.

Style: sans-serif, bold left-aligned title that states the message, light horizontal grid, value labels on the marks, legend in
one row on top. One meaning per color:
  where a chart compares today's rules with the proposal: orange = today, blue (hatched or dashed) = the proposal, and those
  two colors mean nothing else in that chart; orange is also the highlight color (ADL; what exceeds the vault);
  green = the vault; purple (dotted) = a mixed case, the proposal's mark with today's sizing; teal and gold = the two
  groups of a chart that compares neither; gray = context only (xyz's order book line, shaded windows, markets shown for
  reference), never the main data of a chart.
The proposal's marks are also hatched or drawn as points, so every figure reads in grayscale.
"""
import calendar, datetime, decimal, glob, json, os, sys, zoneinfo
import numpy as np
import polars as pl
import matplotlib
matplotlib.use("pdf")
import matplotlib.pyplot as plt
import matplotlib.legend_handler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SC = f"{ROOT}/data/scen"
OUT = f"{ROOT}/docs/figs"
W = 6.6  # text width of the paper, inches (A4, 2.1 cm margins)
TODAY, LEAD, VAULT, GREY, DARK, INK, MUTE = "#E8683A", "#2F74D0", "#1FAF7A", "#A6A69E", "#77776F", "#1A1A1A", "#6B6B6B"
ADL = TODAY
TEAL, PURPLE, GOLD = "#2A8C9A", "#8A5FB0", "#C9952B"
MIX = PURPLE   # a mixed case that is neither today's rules nor the proposal (the proposal's mark with today's sizing); drawn dotted

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "mathtext.fontset": "custom", "mathtext.rm": "Arial", "mathtext.it": "Arial:italic", "mathtext.bf": "Arial:bold",
    "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "text.color": INK, "axes.labelcolor": MUTE, "xtick.color": MUTE, "ytick.color": MUTE, "axes.edgecolor": "#B5B5B0",
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False, "axes.linewidth": 0.7,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#E9E7E2", "grid.linewidth": 0.7, "axes.axisbelow": True,
    "ytick.major.size": 0, "xtick.major.size": 3, "xtick.major.width": 0.7,
    "lines.linewidth": 1.4, "lines.solid_capstyle": "round", "pdf.fonttype": 42, "savefig.bbox": "tight", "savefig.pad_inches": 0.04,
    "legend.frameon": False, "legend.fontsize": 7.5, "hatch.linewidth": 0.6,
})


def need(path, cols=()):
    """Read a CSV; stop if it or an expected column is missing."""
    if not os.path.exists(path):
        raise SystemExit(f"figs: missing file {path}")
    d = pl.read_csv(path, infer_schema_length=None)
    miss = [c for c in cols if c not in d.columns]
    if miss:
        raise SystemExit(f"figs: {path} lacks columns {miss} (has {d.columns})")
    return d


# plain names for the tickers that appear as labels (a ticker without an entry is shown as it is)
NAMES = {"BRENTOIL": "Brent oil", "CL": "Crude oil", "SILVER": "Silver", "GOLD": "Gold", "SKHX": "SK Hynix", "EWZ": "Brazil fund (EWZ)",
         "UNITREE": "Unitree", "GOOGL": "Alphabet", "INTC": "Intel", "AMZN": "Amazon", "SNDK": "SanDisk", "HOOD": "Robinhood",
         "MSTR": "MicroStrategy", "NBIS": "Nebius", "EWY": "Korea fund (EWY)", "SMSN": "Samsung"}
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
name = lambda c: NAMES.get(c, c)
mdate = lambda mmdd, short=False: f"{(calendar.month_abbr if short else calendar.month_name)[int(mmdd[:2])]} {int(mmdd[2:4])}"   # US order: October 28
pct2 = lambda v: f"{v:.2f}%"
n0 = "{:.0f}".format


def usd(v):
    """Dollar label from a value in $M."""
    if v == 0: return r"\$0"
    if v < 1e-3: return rf"\${v * 1e6:.0f}"
    if v >= 100: return rf"\${v:.0f}M"
    if v >= 1: return rf"\${v:.1f}M"
    return rf"\${v * 1e3:.0f}k"


def title(ax, text, sub=None, y=8):
    """Bold message above the panel, left-aligned on the axis labels; optional gray second line."""
    if os.environ.get("TITLES") == "0": return
    ax.annotate(text, (0, 1), xytext=(0, y + (11 if sub else 0)), xycoords="axes fraction", textcoords="offset points", fontsize=9.5, fontweight="bold", va="bottom", ha="left", annotation_clip=False)
    if sub: ax.annotate(sub, (0, 1), xytext=(0, y), xycoords="axes fraction", textcoords="offset points", fontsize=8, color=MUTE, va="bottom", ha="left", annotation_clip=False)


def panel(ax, text):
    """Small bold heading of one panel; always drawn (it says what the panel measures)."""
    ax.annotate(text, (0, 1), xytext=(0, 6), xycoords="axes fraction", textcoords="offset points", fontsize=8, fontweight="bold", va="bottom", ha="left", annotation_clip=False, linespacing=1.2)


def top_legend(ax, y=1.0, **kw):
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, y), ncol=kw.pop("ncol", 4), handlelength=1.4, handletextpad=0.5, columnspacing=1.4, borderaxespad=0.2, **kw)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(f"{OUT}/{name}.pdf")
    if os.environ.get("PNG"):
        os.makedirs(os.environ["PNG"], exist_ok=True)
        fig.savefig(f"{os.environ['PNG']}/{name}.png", dpi=200)
    plt.close(fig)
    print(f"figs: wrote docs/figs/{name}.pdf")


def pairs(ax, labels, a, b, fmt, lab_a="Today", lab_b="Proposal", fs=7.5, lift=0.0):
    """Grouped vertical bars, today (solid orange) next to the proposal (hatched blue), a value label on each.
    lift (share of the tallest bar): when the two bars of a pair are closer than that, today's label is raised above the proposal's."""
    n = len(labels)
    ha, hb = a, b
    top = max(max(ha), max(hb))
    ax.bar([i - 0.2 for i in range(n)], ha, width=0.36, color=TODAY, label=lab_a)
    ax.bar([i + 0.2 for i in range(n)], hb, width=0.36, color=LEAD, hatch="////", edgecolor="white", lw=0, label=lab_b)
    for i in range(n):
        f = fmt[i] if isinstance(fmt, list) else fmt
        ya = max(ha[i], hb[i] + top * lift) if lift and ha[i] - hb[i] < top * lift else ha[i]   # lift > 0: today's label goes one line up when the two would touch
        ax.text(i - 0.2, ya + top * 0.02, f(a[i]), ha="center", va="bottom", fontsize=fs, color=INK)
        ax.text(i + 0.2, hb[i] + top * 0.02, f(b[i]), ha="center", va="bottom", fontsize=fs, color=LEAD, fontweight="bold")
    ax.set_xticks(range(n)); ax.set_xticklabels(labels, color=INK, linespacing=1.2, fontsize=fs)
    ax.tick_params(axis="x", length=0); ax.set_xlim(-0.6, n - 0.4); ax.set_ylim(0, top * 1.13)


def hpairs(groups, width, per=0.42, norm="today", lab_a="Today", lab_b="Proposal", xlabel=None, height=None, fs=7.5, xaxis=True, h=0.3, msg=None, note=None):
    """Horizontal today / proposal pairs under optional group headings: groups = [(heading or None, [(label, a, b, fmt), ...])].
    Bar length is a share of today's value (norm='today') or of the larger value of the pair (norm='max'); the label at the
    end of each bar is the measured value. Returns (fig, ax); the figure is drawn at `width` inches, labels included
    (height: 0.55 + per inch a pair, or `height`). fs = size of the labels; h = bar thickness (a pair has 1). A heading starts
    at the figure's left edge and may have two lines. xaxis=False leaves the percent axis and its gridlines out (note = a line
    under the bars in its place); msg = bold message above, kept inside the drawn width."""
    y, ticks, labs, first, heads = 0.0, [], [], True, []
    units = sum(len(r) for _, r in groups) + sum(0.95 + 0.42 * g.count("\n") for g, _ in groups if g)
    fig, ax = plt.subplots(figsize=(width, height or 0.55 + units * per), layout="constrained")
    ax.grid(False)
    if xaxis: ax.grid(axis="x")
    # every label sits about half a row from the next one, within a pair and between pairs alike; the lower one a little
    # lower, so a label beside an empty bar does not touch the bar above it
    lab = lambda x, yy, t, dy, **kw: ax.annotate(t, (x, yy), xytext=(5, dy), textcoords="offset points", ha="left", va="center", fontsize=fs, zorder=4, **kw)
    for head, rows in groups:
        if head:
            y += (0.42 if first else 0.95) + 0.42 * head.count("\n")
            heads.append((y - 0.1, head))
        for label, a, b, fmt in rows:
            ref = a if norm == "today" else max(a, b)
            if ref <= 0:
                raise SystemExit(f"figs: no positive value to scale the pair '{label}' (today {a}, proposal {b})")
            y += 0.5
            ax.barh(y - h / 2, 100 * a / ref, height=h, color=TODAY, label=lab_a if first else None)
            ax.barh(y + h / 2, 100 * b / ref, height=h, color=LEAD, hatch="////", edgecolor="white", lw=0, label=lab_b if first else None)
            lab(100 * a / ref, y - 0.24, fmt(a), 0, color=INK); lab(100 * b / ref, y + (0.33 if b == 0 else 0.29), fmt(b), 0, color=LEAD, fontweight="bold")   # a label beside an empty bar sits lower, clear of the bar above
            ticks.append(y); labs.append(label); y += 0.5; first = False
    ax.set_ylim(y + 0.05, 0)
    ax.set_yticks(ticks); ax.set_yticklabels(labs, color=INK, linespacing=1.15, fontsize=fs)
    ax.set_xlim(0, 114); ax.set_xticks([0, 25, 50, 75, 100]); ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel(xlabel or ("Share of today's value" if norm == "today" else "Share of the larger value of each pair"))
    ax.spines["bottom"].set_visible(False); ax.tick_params(axis="x", length=0)
    if not xaxis: ax.set_xticklabels([]); ax.set_xlabel(note or "", fontsize=fs, color=MUTE)
    tr = matplotlib.transforms.blended_transform_factory(fig.transFigure, ax.transData)
    for yy, head in heads:
        ax.text(0.005, yy, head, transform=tr, fontsize=fs + 0.5, fontweight="bold", color=INK, ha="left", va="bottom", linespacing=1.15, clip_on=False)
    if any(g for g, _ in groups): fig.legend(*ax.get_legend_handles_labels(), loc="lower left", bbox_to_anchor=(0.0, 0.0), ncol=2, handlelength=1.4, handletextpad=0.5, columnspacing=1.2, borderaxespad=0.2, fontsize=fs)
    else: top_legend(ax, y=1.0, fontsize=fs)
    if msg and os.environ.get("TITLES") != "0": fig.suptitle(msg, x=0.0, ha="left", fontsize=9.5, fontweight="bold")
    return fig, ax


# ---------------------------------------------------------------------------------------------------------------------
# The final run (sim/final/run_final.sh -> data/scen/final, one folder per test): raw engine outputs per run,
#   orc_{run}.csv  h, ms, ext (external price), m1, m2 (the two published mark inputs; under the proposal the feed's vote and
#                  the anchor), bid, ask, last (xyz's book), prices x 1e6
#   tk_{run}.csv   u, h, q, px: positions the vault took over | log_{run}.csv h, buy, px, sz: the vault's fills
#   rd_{run}.csv   u, sim_h1, sim_rounds, sim_filled: liquidations in the order book
# scored here with the same formulas as sim/final/score_final.py (its columns 'today' and 'proposal').
FIN = f"{SC}/final"
RUN = {"today": ("today", "today"), "prop": ("pkgm3q1800", "lead3q1800")}   # (mark tag, design tag) used in the run file names
ATT = 4294967286   # account of the injected attacker: never counted as a liquidated trader
ORC = ("h", "ms", "m1", "m2", "ext", "bid", "ask", "last")


def fmarks(T, n):
    """Votes and mark at every update of run n in folder T: book = median(bid, ask, last), or the lone quote when one side is
    empty; mark = median(m1, m2, book), moved at most 1% per update (Hyperliquid's rule). Prices in USD."""
    o = need(f"{T}/orc_{n}.csv", ORC).sort("h")
    bid, ask, last = (o[c].cast(pl.Float64).to_numpy() for c in ("bid", "ask", "last"))   # nulls -> nan
    full = ~(np.isnan(bid) | np.isnan(ask) | np.isnan(last))
    bk = np.where(full, np.median(np.stack([bid, ask, last]), axis=0), np.where(np.isnan(bid), ask, bid))
    m1, m2 = o["m1"].cast(pl.Float64).to_numpy(), o["m2"].cast(pl.Float64).to_numpy()
    raw = np.median(np.stack([m1, m2, np.where(np.isnan(bk), m1, bk)]), axis=0) / 1e6
    m, prev = raw.copy(), None
    for i in range(len(m)):
        if np.isnan(bk[i]): m[i] = prev if prev is not None else raw[i]
        elif prev is not None: m[i] = min(max(raw[i], prev * 0.99), prev * 1.01)
        prev = m[i]
    return o.select("h", "ms", "bid", E=pl.col("ext") / 1e6, V=pl.col("m1") / 1e6, A=pl.col("m2") / 1e6).with_columns(B=pl.Series(bk / 1e6), mk=pl.Series(m))


def ftk(T, n):
    """Takeovers of run n (empty file = none): u, h, q, px and ntl = |q| px, as sim/final/score_final.py values them:
    a position whose bankruptcy price is negative is handed over at a negative price, and is counted at the mark."""
    f = f"{T}/tk_{n}.csv"
    if not os.path.exists(f):
        raise SystemExit(f"figs: missing file {f}")
    if os.path.getsize(f) == 0: return None
    return pl.read_csv(f, schema_overrides={"q": pl.Float64, "px": pl.Float64, "mark": pl.Float64}).with_columns(ntl=pl.col("q").abs() * pl.when(pl.col("px") > 0).then(pl.col("px")).otherwise(pl.col("mark")))


def fvault(T, n, L):
    """The vault in run n: tk = takeovers, ntl = notional inherited ($), need = capital need = max(maintenance margin of its
    position - its value), adl = money needed to avoid ADL = max(-value); value = cash + position at the mark. L = max leverage."""
    t = ftk(T, n)
    r = dict(tk=t.height if t is not None else 0, ntl=float(t["ntl"].sum()) if t is not None and t.height else 0.0, need=0.0, adl=0.0)
    f = f"{T}/log_{n}.csv"
    if os.path.exists(f) and os.path.getsize(f) > 0:
        lg = pl.read_csv(f)
        if lg.height:
            o = fmarks(T, n).select("h", "ms", "mk")
            g = (lg.join(o.select("h", "ms"), on="h", how="left").with_columns(pl.col("ms").forward_fill().backward_fill())
                 .with_columns(q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz"))).sort("ms")
                 .with_columns(cq=pl.col("q").cum_sum(), cash=(-pl.col("q") * pl.col("px")).cum_sum()))
            g = o.sort("ms").join_asof(g.select("ms", "cq", "cash"), on="ms").with_columns(pl.col("cq").fill_null(0.0), pl.col("cash").fill_null(0.0))
            val = (g["cash"] + g["cq"] * g["mk"]).to_numpy(); mm = (g["cq"].abs() * g["mk"] / (2 * L)).to_numpy()
            r.update(need=max(0.0, float((mm - val).max())), adl=max(0.0, float((-val).max())))
    return r


def flift(T, a, b):
    """Mark of run a against run b (the same replay without the attack), update by update: g = mark_a / mark_b - 1 in %,
    and t0 = time of the first update where the two books differ (the start of a push), None if they never do."""
    j = fmarks(T, a).join(fmarks(T, b).select("h", mk_b="mk", bid_b="bid"), on="h").with_columns(g=(pl.col("mk") / pl.col("mk_b") - 1) * 100)
    d = j.filter(pl.col("bid").fill_null(0) != pl.col("bid_b").fill_null(0))
    return j, (d["ms"][0] if d.height else None)


def fliq(T, n, w0, secs=300):
    """Positions liquidated (order book + vault, attacker left out) in the `secs` seconds from w0, $: takeovers at their price
    plus book-liquidated size at the run's average takeover price (the average external price when there is no takeover)."""
    o = need(f"{T}/orc_{n}.csv", ORC).select("h", "ms", "ext").sort("h")
    win = (pl.col("ms") >= w0) & (pl.col("ms") < w0 + secs * 1000)
    t = pl.read_csv(f"{T}/tk_{n}.csv", schema_overrides={"q": pl.Float64, "px": pl.Float64, "mark": pl.Float64}).sort("h").join_asof(o, on="h").filter(win & (pl.col("u") != ATT))
    r = (need(f"{T}/rd_{n}.csv", ("u", "sim_h1", "sim_filled")).filter((pl.col("sim_h1") > 0) & (pl.col("u") != ATT)).sort("sim_h1")
         .join_asof(o.rename({"h": "sim_h1"}), on="sim_h1").filter(win))
    pos = t.filter(pl.col("px") > 0)["px"].mean()   # negative transfer prices are not a market price
    px = float(pos) if pos is not None else float(o["ext"].mean()) / 1e6
    return float((t["q"].abs() * t["px"]).sum()) + float(r["sim_filled"].sum()) * px


def fall_start(m, n=20):
    """Start of the external price's fastest fall over n updates (about 60 s): the time of the update that fall starts from."""
    return m.with_columns(r=pl.col("E") / pl.col("E").shift(n) - 1, ms0=pl.col("ms").shift(n)).drop_nulls("r").sort("r").head(1)["ms0"][0]


def maxlev():
    p = f"{ROOT}/data/xyzmeta.json"
    if not os.path.exists(p):
        raise SystemExit(f"figs: missing file {p}")
    return {u["name"][4:]: u["maxLeverage"] for u in json.load(open(p))[0]["universe"]}


# the tests of the final run, as listed in sim/final/run_final.sh and score_final.py (market, day)
ISO = (("NOW", "1028"), ("LITE", "1028"), ("MRVL", "1028"), ("RDDT", "1029"), ("NET", "1105"))            # vault not allowed in
OOS = (("GOOGL", "1022"), ("META", "1022"), ("SILVER", "1022"), ("GOLD", "1030"), ("SPCX", "1030"), ("BRENTOIL", "0910"), ("CL", "0910"))
WALK = {"night": ("GOOGL_night_dn", 1793163600000, "c1e6_f-0.10"), "day": ("GOOGL_day_dn", 1793226600000, "c5e6_f-0.10")}   # folder, walk start, push tag ("day" is the run's name: that walk starts after the US close)


def f_iso(k): return sum(fvault(f"{FIN}/iso", f"{c}_{d}_{RUN[k][1]}", 10)["ntl"] for c, d in ISO) / 1e6
def f_print(k, tag="q30s"):
    """Wrong price from the feed: takeover notional the print adds, Alphabet + Amazon, $M."""
    T = f"{FIN}/spike"
    return sum(ftk(T, f"{c}_{RUN[k][0]}_{tag}")["ntl"].sum() - ftk(T, f"{c}_{RUN[k][0]}_base")["ntl"].sum() for c in ("GOOGL", "AMZN")) / 1e6
def f_walk(k, slot, push=None):
    """External price walked: liquidated within five minutes, $M; push = seconds of the book push that follows (None: walk alone)."""
    d, w0, tag = WALK[slot]
    return fliq(f"{FIN}/adapt/{d}", f"GOOGL_{RUN[k][0]}_{'base' if push is None else f'{tag}_d{push}'}", w0) / 1e6
def f_closed(k, c):
    """Book pushed while the market is closed: largest mark lift (%) of each push tested, a list."""
    T = f"{FIN}/closed_{c}"
    fs = sorted(glob.glob(f"{T}/orc_{c}_{RUN[k][0]}_c*.csv"))
    if not fs:
        raise SystemExit(f"figs: no push runs in {T}")
    return [float(flift(T, os.path.basename(f)[4:-4], f"{c}_{RUN[k][0]}_base")[0]["g"].max()) for f in fs]
def f_quiet(k, secs=None):
    """Quiet feed, a bid above the market held 2.5 h: (minutes from the start of the push, mark lift %) or the lift after `secs`."""
    T = f"{FIN}/quiet_up"
    j, t0 = flift(T, f"GOOGL_{RUN[k][0]}_c5e6_f0.06_d9000", f"GOOGL_{RUN[k][0]}_base")
    if t0 is None:
        raise SystemExit("figs: quiet-feed push: the pushed book never differs from the base run")
    t0 = t0 // 60000 * 60000   # the push starts on the minute; the first changed update comes a few seconds later
    if secs is None: return j.with_columns(x=(pl.col("ms") - t0) / 60e3)
    return float(j.filter(pl.col("ms") <= t0 + secs * 1000)["g"][-1])


# ---------------------------------------------------------------------------------------------------------------------
def adl_timeline():
    """Where ADL came from over the whole tape, and that it stops once the vault backstops a market.
    Reads data/scen/tape/out/t{YYYYMMDD}_markets.csv (sim/study/tape_backstop.py), one file per day: coin, mode, to_vault
    (backstop events the vault took), adl_ntl (ADL notional, $). One row per market with at least $1M of ADL in total, the
    rest pooled; circle area = that day's ADL notional. Each market-day falls in one of four cases, shown in the bar on
    top and by the circles' color: before the vault's first takeover in that market, a market where the vault never took a
    position, the largest single day of the rest, and what is left. A row is shaded from the vault's first takeover in that market (the pooled row is not)."""
    fs = sorted(glob.glob(f"{SC}/tape/out/t*_markets.csv"))
    if not fs:
        raise SystemExit(f"figs: no files in {SC}/tape/out/")
    parts = []
    for f in fs:
        if os.path.getsize(f) == 0: continue
        d = need(f, ("coin", "mode", "to_vault", "adl_ntl"))
        parts.append(d.select("coin", "mode", pl.col("to_vault").cast(pl.Float64, strict=False).fill_null(0),
                              pl.col("adl_ntl").cast(pl.Float64, strict=False).fill_null(0))
                     .with_columns(day=pl.lit(os.path.basename(f)[1:9]).str.to_date("%Y%m%d")))
    M = pl.concat(parts).with_columns(pl.col("coin").str.replace("xyz:", ""))
    tot = M.group_by("coin").agg(adl=pl.col("adl_ntl").sum()).sort("adl", descending=True)
    big = tot.filter(pl.col("adl") >= 1e6)["coin"].to_list()
    other = f"{tot.filter((pl.col('adl') > 0) & (pl.col('adl') < 1e6)).height} other markets"
    M = M.with_columns(row=pl.when(pl.col("coin").is_in(big)).then(pl.col("coin")).otherwise(pl.lit(other)))
    rows = big + [other]
    total, days = M["adl_ntl"].sum(), len(fs)

    # four cases, from the same file: ADL on a market-day before the vault's first takeover in that market; ADL on a market
    # where the vault never took a position; the largest single day among the rest; what is left
    fv = M.filter(pl.col("to_vault") > 0).group_by("coin").agg(first=pl.col("day").min())
    M = M.join(fv, on="coin", how="left").with_columns(inn=pl.col("first").is_not_null() & (pl.col("day") >= pl.col("first")))
    big_day = M.filter(pl.col("inn")).group_by("day").agg(pl.col("adl_ntl").sum()).sort("adl_ntl", descending=True)["day"][0]
    M = M.with_columns(case=pl.when(pl.col("first").is_null()).then(1).when(~pl.col("inn")).then(0).when(pl.col("day") == big_day).then(2).otherwise(3))
    CASE = [(TODAY, "before the vault entered the market"), ("#F2A27F", "markets the vault never entered"),
            ("#8E2B3C", f"{calendar.month_name[big_day.month]} {big_day.day}, vault in"), (TEAL, "other days, vault in")]
    part = [float(M.filter(pl.col("case") == c)["adl_ntl"].sum()) for c in range(len(CASE))]
    D = M.filter(pl.col("adl_ntl") > 0).group_by("row", "day", "case").agg(adl=pl.col("adl_ntl").sum())

    fig, (t, ax) = plt.subplots(2, 1, figsize=(W + 0.1, 2.72), height_ratios=[0.26, 2.3], gridspec_kw=dict(hspace=0.3))
    # top: the total split into the four cases
    t.axis("off"); t.set_xlim(0, total); t.set_ylim(0, 1); left = 0.0
    for c, (col, lab) in enumerate(CASE):
        t.barh(0.5, part[c], left=left, height=1.0, color=col, lw=0)
        txt = f"{usd(part[c] / 1e6)} ({100 * part[c] / total:.0f}%) {lab}"
        if part[c] / total > 0.25: t.text(left + part[c] / 2, 0.5, txt, ha="center", va="center", fontsize=7.2, color="white", fontweight="bold")
        else: t.annotate(txt, (left + part[c] / 2, 1.0), xytext=(0, 9), textcoords="offset points", ha="right", va="bottom", fontsize=7.5, color="#C4623A" if c == 1 else col, fontweight="bold",
                         arrowprops=dict(arrowstyle="-", color=col, lw=0.7, shrinkA=0, shrinkB=0), annotation_clip=False)
        left += part[c]
    # below: one row per market; shaded from the vault's first takeover there; circles colored by case
    ax.grid(False)
    k = 430 / D.group_by("row", "day").agg(pl.col("adl").sum())["adl"].max()  # marker area per dollar
    x1 = M["day"].max(); said = False
    for i, r in enumerate(rows):
        y = len(rows) - 1 - i
        ax.axhline(y, color="#E9E7E2", lw=0.7, zorder=0)
        f0 = fv.filter(pl.col("coin") == r)
        if f0.height:
            ax.fill_between([f0["first"][0], x1], y - 0.36, y + 0.36, color=VAULT, alpha=0.16, lw=0, zorder=1)
            if not said:
                ax.text(x1, y + 0.4, "shaded: after the vault's first takeover in that market ", fontsize=7, color=VAULT, fontweight="bold", ha="right", va="bottom"); said = True
        d = D.filter(pl.col("row") == r).sort("adl", descending=True)
        ax.scatter(d["day"], [y] * d.height, s=(d["adl"] * k).to_numpy().clip(5), color=[CASE[c][0] for c in d["case"]], alpha=0.85, lw=0, zorder=3)   # no outline: a small day beside a large one would draw a ring inside it
        ax.text(1.015, y, usd(d["adl"].sum() / 1e6), transform=ax.get_yaxis_transform(), va="center", fontsize=8, fontweight="bold")
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([name(r) for r in rows[::-1]], color=INK)
    ax.set_ylim(-0.6, len(rows) - 0.3)
    ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(interval=2)); ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
    ax.set_xlim(M["day"].min(), x1)
    ax.text(1.015, len(rows) - 0.4, "ADL", transform=ax.get_yaxis_transform(), fontsize=7.5, va="bottom", color=MUTE)
    ax.set_xlabel("Each circle: ADL on one day in that market (area = amount)", fontsize=7, color=MUTE, loc="left")   # under the axis, clear of the rows
    title(t, f"{usd(total / 1e6)} of ADL in {days} days: most of it on markets the vault had not entered", y=22)
    print("figs: adl_timeline: " + "; ".join(f"{usd(p / 1e6)} {lab}" for p, (_, lab) in zip(part, CASE)))
    save(fig, "adl_timeline")


# ---------------------------------------------------------------------------------------------------------------------
def crash_mark(event="GOOGL_1028", before_min=1, after_min=9):
    """The problem, today's rules only: in an earnings crash today's mark crawls behind the external price.
    Reads data/scen/final/crash/orc_{event}_today.csv (see fmarks) and liq_{event}_today.csv (h, mark: the engine's mark at
    each liquidation). The mark line is rebuilt from the orc file by fmarks; the rebuild is checked against the engine's own
    mark at every liquidation (the figure stops if they differ). Time zero: the start of the external price's fastest 60 s fall
    (fall_start). (The proposal's mark on the same crash is in mark_changes.)"""
    T = f"{FIN}/crash"
    t = fmarks(T, f"{event}_{RUN['today'][1]}")
    l = need(f"{T}/liq_{event}_{RUN['today'][1]}.csv", ("h", "mark")).sort("h").join_asof(t.select("h", "mk"), on="h")
    bad = l.filter(((pl.col("mark") - pl.col("mk")).abs() / pl.col("mark")) > 1e-5).height
    if bad:
        raise SystemExit(f"figs: crash_mark: rebuilt mark differs from the engine's at {bad}/{l.height} liquidations of {event}")
    t0 = fall_start(t)
    t = t.filter(pl.col("ms").is_between(t0 - before_min * 60e3, t0 + after_min * 60e3))
    x = (t["ms"].to_numpy() - t0) / 60e3
    coin = event.split("_")[0]

    fig, (a, b) = plt.subplots(2, 1, figsize=(W + 1.3, 3.3), sharex=True, height_ratios=[1.45, 1], gridspec_kw=dict(hspace=0.16))   # placed at the full text width
    a.plot(x, t["E"], color=INK, lw=0.9, label="External price")   # black, as on the other mark charts (gray there is xyz's order book)
    a.plot(x, t["mk"], color=TODAY, lw=1.7, label="Today's mark")
    a.set_ylabel(f"{name(coin)} price (USD)")
    gap = (t["mk"] / t["E"] - 1) * 100
    b.axhline(0, color=DARK, lw=0.9)
    b.plot(x, gap, color=TODAY, lw=1.7)
    b.set_ylabel("Mark above the\nexternal price (%)"); b.set_xlabel("Minutes from the start of the fall of the external price")
    i = int(gap.arg_max())
    b.annotate(f"{gap.max():.1f}%", (x[i], gap.max()), xytext=(7, -1), textcoords="offset points", fontsize=8, fontweight="bold", va="top")
    b.set_xlim(-before_min, after_min)
    top_legend(a, y=1.0)
    title(a, f"{name(coin)}, {mdate(event[-4:])}: today's mark stays up to {gap.max():.1f}% above the external price", y=24)
    save(fig, "crash_mark")


# ---------------------------------------------------------------------------------------------------------------------
def skhx_0727(event="SKHX_0727", stuck_pad_min=25, before_s=70, after_s=480):
    """SK Hynix, July 27, update by update: the afternoon, when the external price does not change for hours while xyz's
    book drifts down, and the minutes around the wrong price at the reopening.
    Reads data/scen/final/skhx/orc_{event}_{today,lead3q1800}.csv (see fmarks): ext = external price, xyz's book price, and
    the two marks. Every window and label is found in the data:
      afternoon = the longest run of updates with the external price unchanged, with stuck_pad_min minutes on each side;
      wrong price = the external price's largest one-update fall, until its next one-update rise of more than 10%;
      labels = that price and the one before it, the price that ends it, the book before the fall and at the first update
      where it has done 95% of its fall, each mark's lowest value in the window, and in the afternoon the largest distance
      of each mark from xyz's book while the external price is unchanged. Times are UTC."""
    T = f"{FIN}/skhx"
    m = {k: fmarks(T, f"{event}_{RUN[k][1]}") for k in RUN}
    t = m["today"].select("ms", "E", "B", mt="mk").join(m["prop"].select("ms", Bp="B", mp="mk"), on="ms").sort("ms")
    dtm = lambda d: [datetime.datetime.fromtimestamp(v / 1000, datetime.timezone.utc).replace(tzinfo=None) for v in d["ms"]]
    hms = lambda v: datetime.datetime.fromtimestamp(v / 1000, datetime.timezone.utc).strftime("%H:%M:%S")
    hm = lambda v: datetime.datetime.fromtimestamp(v / 1000, datetime.timezone.utc).strftime("%H:%M")
    px = lambda v: f"{v:,.2f}"; p0 = lambda v: f"{v:,.0f}"
    # the longest stretch with the external price unchanged
    r = t.with_columns(run=(pl.col("E") != pl.col("E").shift(1)).fill_null(True).cum_sum())
    g = r.group_by("run").agg(a=pl.col("ms").min(), b=pl.col("ms").max(), E=pl.col("E").first(), n=pl.len()).sort("n", descending=True).row(0, named=True)
    nxt = t.filter(pl.col("ms") > g["b"]).row(0, named=True)
    st = t.filter(pl.col("ms").is_between(g["a"], g["b"])).with_columns(gp=(pl.col("mp") / pl.col("Bp") - 1) * 100, gt=((pl.col("mt") / pl.col("B") - 1) * 100).abs())
    aft = t.filter(pl.col("ms").is_between(g["a"] - stuck_pad_min * 60e3, g["b"] + stuck_pad_min * 60e3))
    # the wrong price
    d = t.with_columns(dE=pl.col("E") / pl.col("E").shift(1) - 1)
    bad = d.drop_nulls("dE").sort("dE").row(0, named=True); prev = t.filter(pl.col("ms") < bad["ms"]).row(-1, named=True)
    end = d.filter((pl.col("ms") > bad["ms"]) & (pl.col("dE") > 0.10)).row(0, named=True)
    w = t.filter(pl.col("ms").is_between(bad["ms"] - before_s * 1000, bad["ms"] + after_s * 1000))
    f = t.filter(pl.col("ms").is_between(bad["ms"], end["ms"]))
    b0, bmin = prev["B"], float(f["B"].min())
    bk = f.filter(pl.col("B") <= bmin + 0.05 * (b0 - bmin)).row(0, named=True)
    lt, lp = f.sort("mt").row(0, named=True), f.sort("mp").row(0, named=True)

    fig, (a, b) = plt.subplots(1, 2, figsize=(0.94 * W + 1.08, 2.2), sharey=True, width_ratios=[1, 1.75], gridspec_kw=dict(wspace=0.05))   # placed at 0.94 of the text width
    for ax, q in ((a, aft), (b, w)):
        x = dtm(q)
        ax.plot(x, q["B"], color=GREY, lw=2.6, alpha=0.75, label="xyz's order book")
        ax.plot(x, q["E"], color=INK, lw=0.9, label="External price")
        ax.plot(x, q["mt"], color=TODAY, lw=1.4, label="Today's mark")
        ax.plot(x, q["mp"], color=LEAD, lw=1.7, ls=(0, (4, 1.5)), label="Proposal's mark")
        ax.set_xlim(x[0], x[-1])
    U = lambda v: datetime.datetime.fromtimestamp(v / 1000, datetime.timezone.utc).replace(tzinfo=None)
    note = lambda ax, s, xy, xt, col=INK, **kw: ax.annotate(s, xy, xytext=xt, textcoords="offset points", fontsize=7, color=col, linespacing=1.2,
                                                            arrowprops=dict(arrowstyle="-", color=col, lw=0.6, shrinkA=1, shrinkB=2), **kw)
    a.xaxis.set_major_locator(matplotlib.dates.HourLocator(byhour=range(11, 17, 2))); a.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    b.xaxis.set_major_locator(matplotlib.dates.MinuteLocator(byminute=range(0, 60, 2))); b.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    a.set_xlabel("Time (UTC)"); b.set_xlabel("Time (UTC)"); a.set_ylabel("SK Hynix price (USD)")
    a.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ylo = min(float(w["E"].min()), float(w["mt"].min())); a.set_ylim(ylo - 95, max(float(aft["E"].max()), float(w["E"].max())) + 75)
    # afternoon labels
    mid = U((g["a"] + g["b"]) / 2)
    a.text(mid, g["E"] + 6, f"unchanged at {px(g['E'])}\nfrom {hm(g['a'])} to {hm(g['b'])}", fontsize=7, color=INK, ha="center", va="bottom", linespacing=1.2)
    note(a, f"then {px(nxt['E'])}", (U(nxt["ms"]), nxt["E"]), (-6, -12), ha="right", va="top")
    top = st.sort("gp", descending=True).row(0, named=True)
    a.text(U(g["a"]), ylo + 118, f"While it is unchanged:\nproposal's mark up to {top['gp']:.1f}%\nabove xyz's book;\ntoday's mark within {st['gt'].max():.1f}%\nof the book", fontsize=7, color=INK, ha="left", va="top", linespacing=1.25)
    # the wrong price
    b.annotate(f"wrong price {px(bad['E'])} at {hms(bad['ms'])}, {-100 * bad['dE']:.0f}% below {px(prev['E'])}", (U(bad["ms"]), bad["E"]), xytext=(0, -5), textcoords="offset points", fontsize=7, color=INK, ha="left", va="top")
    b.annotate(f"{px(end['E'])} at {hms(end['ms'])}", (U(end["ms"]), end["E"]), xytext=(2, 4), textcoords="offset points", fontsize=7, color=INK, ha="left", va="bottom")
    # the three other labels stand in the empty part of the panel, right of the fall and below the lines, each joined to its point
    x0, lo_y = U(end["ms"] + 95_000), min(float(w["E"].min()), float(w["mt"].min()))
    span = float(w.filter(pl.col("ms") > end["ms"] + 60_000).select(pl.min_horizontal("B", "mt", "mp", "E").min()).item()) - lo_y
    far = lambda s_, xy, k, col=INK, **kw: b.annotate(s_, xy, xytext=(x0, lo_y + span * k), fontsize=7, color=col, linespacing=1.2, ha="left", va="center",
                                                       arrowprops=dict(arrowstyle="-", color=col, lw=0.6, shrinkA=1, shrinkB=2), **kw)
    far(f"the book falls from {p0(b0)} to {p0(bk['B'])} by {hms(bk['ms'])}", (U(bk["ms"]), bk["B"]), 0.82)
    far(f"proposal's mark stops at {p0(lp['mp'])} at {hms(lp['ms'])}", (U(lp["ms"]), lp["mp"]), 0.55, col=LEAD, fontweight="bold")
    far(f"today's mark reaches {p0(lt['mt'])} at {hms(lt['ms'])}", (U(lt["ms"]), lt["mt"]), 0.28, col=TODAY, fontweight="bold")
    panel(a, "Afternoon: the feed stands still")
    panel(b, "Reopening: a wrong external price for two minutes" if 100 <= (end["ms"] - bad["ms"]) / 1000 <= 140 else "Reopening: a wrong external price")
    h, l = b.get_legend_handles_labels()
    fig.legend(h, l, loc="lower right", bbox_to_anchor=(0.9, 1.0), ncol=4, handlelength=1.8, handletextpad=0.5, columnspacing=1.3, borderaxespad=0.2)
    title(a, f"{name(event.split('_')[0])}, {mdate(event[-4:])}: the external price, xyz's book and the two marks", y=42)
    print(f"figs: skhx_0727: unchanged {px(g['E'])} {hms(g['a'])}-{hms(g['b'])}, then {px(nxt['E'])} at {hms(nxt['ms'])}; book at the end of it {px(st['B'][-1])}, lowest {px(st['B'].min())}; "
          f"proposal's mark up to {top['gp']:.2f}% above the book at {hms(top['ms'])}, today's within {st['gt'].max():.2f}%; wrong price {px(bad['E'])} at {hms(bad['ms'])} until {px(end['E'])} at {hms(end['ms'])}; "
          f"book {px(b0)} -> {px(bk['B'])} by {hms(bk['ms'])} (lowest {px(bmin)}); today's mark low {px(lt['mt'])} at {hms(lt['ms'])}; proposal's {px(lp['mp'])} at {hms(lp['ms'])}")
    save(fig, "skhx_0727")


# ---------------------------------------------------------------------------------------------------------------------
def headline_crash(event="GOOGL_1028", before_min=1, after_min=3):
    """Page 1: one defined event, compact. The external price, today's mark and the proposal's mark through an earnings crash.
    Reads data/scen/final/crash/orc_{event}_{today,lead3q1800}.csv (fmarks; the rebuilt marks are checked against the
    engine's in crash_mark) and tk_{event}_*.csv (u, h, q, px). Time zero: the start of the external price's fastest 60 s
    fall (fall_start). Labels, all computed: each mark's largest gap above the external price in the window; how long the
    proposal's gap stays above 1% and its largest value after that; how long today's stays above 1% (for the title); and
    the takeovers whose price is worse for the vault than the external price at that moment, q (E - px) < 0, out of all."""
    T = f"{FIN}/crash"
    m = {k: fmarks(T, f"{event}_{RUN[k][1]}") for k in RUN}
    t0 = fall_start(m["today"])
    w = {k: d.filter(pl.col("ms").is_between(t0 - before_min * 60e3, t0 + after_min * 60e3)).with_columns(x=(pl.col("ms") - t0) / 60e3, g=(pl.col("mk") / pl.col("E") - 1) * 100) for k, d in m.items()}
    t, p = w["today"], w["prop"]
    secs = lambda d: float((d.filter(pl.col("g") > 1)["ms"].max() - d.filter(pl.col("g") > 1)["ms"].min()) / 1000 + 3) if d.filter(pl.col("g") > 1).height else 0.0
    st, sp = secs(t), secs(p)
    after = float(p.filter(pl.col("ms") > p.filter(pl.col("g") > 1)["ms"].max())["g"].max()) if sp else float(p["g"].max())
    under = {}
    for k in RUN:
        tk = ftk(T, f"{event}_{RUN[k][1]}").sort("h").join_asof(m[k].select("h", "E").sort("h"), on="h")
        under[k] = (tk.filter(pl.col("q") * (pl.col("E") - pl.col("px")) < 0).height, tk.height)
    coin = event.split("_")[0]

    fig, ax = plt.subplots(figsize=(0.60 * W + 0.42, 0.86))   # drawn for 0.60 of the text width
    ax.plot(t["x"], t["E"], color=INK, lw=0.9, label="External price")
    ax.plot(t["x"], t["mk"], color=TODAY, lw=1.7, label="Today's mark")
    ax.plot(p["x"], p["mk"], color=LEAD, lw=1.7, ls=(0, (4, 1.5)), label="Proposal's mark")
    i = int(t["g"].arg_max()); j = int(p["g"].arg_max())
    ax.annotate("", (t["x"][i], t["E"][i]), xytext=(t["x"][i], t["mk"][i]), arrowprops=dict(arrowstyle="<->", color=TODAY, lw=0.8, shrinkA=0, shrinkB=0))
    ax.annotate(f"{t['g'].max():.1f}% above", (t["x"][i], t["mk"][i]), xytext=(t["x"][i] + 0.2, t["mk"][i] + 0.12 * (float(t["E"].max()) - float(t["E"].min()))), fontsize=7.5, fontweight="bold", color=TODAY, va="center", ha="left")
    lo = float(min(t["E"].min(), p["mk"].min()))
    ax.annotate(f"{p['g'].max():.1f}% above\nfor {sp:.0f} seconds,\nthen within {after:.1f}%", (p["x"][j], p["mk"][j]), xytext=(-before_min + 0.05, lo + 0.36 * (float(t["E"].max()) - lo)), fontsize=7.5, fontweight="bold",
                color=LEAD, ha="left", va="center", linespacing=1.15, arrowprops=dict(arrowstyle="-", color=LEAD, lw=0.6, shrinkA=1, shrinkB=2))
    ax.set_xlim(-before_min, after_min); ax.set_xlabel("Minutes from the start of the fall of the external price", fontsize=7.5)
    ax.set_ylabel(f"{name(coin)} (USD)", fontsize=7.5); ax.tick_params(labelsize=7.5)
    ax.legend(loc="upper right", handlelength=1.8, borderaxespad=0.1, fontsize=7.5, labelspacing=0.25)
    ax.annotate(f"Positions the vault took over at a price worse for it than the external price:\n{under['today'][0]} of {under['today'][1]} today, {under['prop'][0]} of {under['prop'][1]} under the proposal.",
                (0, 0), xytext=(-28, -30), xycoords="axes fraction", textcoords="offset points", fontsize=7, color=MUTE, va="top", ha="left", annotation_clip=False, linespacing=1.2)
    dur = "for a minute" if 45 <= st <= 80 else f"for {st:.0f} seconds"
    if os.environ.get("TITLES") != "0":
        ax.annotate(f"{name(coin)}, {mdate(event[-4:])}: today's mark stays up to {t['g'].max():.1f}% above the\nexternal price {dur}; the proposal's mark follows the fall", (0, 1), xytext=(-28, 6),
                    xycoords="axes fraction", textcoords="offset points", fontsize=8.5, fontweight="bold", va="bottom", ha="left", annotation_clip=False, linespacing=1.15)
    print(f"figs: headline_crash: today's gap up to {t['g'].max():.2f}%, above 1% for {st:.0f} s; proposal's up to {p['g'].max():.2f}%, above 1% for {sp:.0f} s, then at most {after:.2f}%; "
          f"takeovers worse than the external price {under['today'][0]}/{under['today'][1]} today, {under['prop'][0]}/{under['prop'][1]} proposal")
    save(fig, "headline_crash")


# ---------------------------------------------------------------------------------------------------------------------
def headline():
    """Today against the proposal on results a newcomer can read. Bar length = share of the larger value of each pair; the
    label at the end of each bar is the measured value. Reads data/scen/final:
      iso/ (five replays of isolated-only markets): ADL = takeover notional
      oos/ (seven other market-days): takeover events (rows of tk_; a small position can be taken over more than once), split in two rows so the total does not hide the split: the calendar day
        that carries most of them under today's rules (its markets are oil), and the other market-days together.
    (SK Hynix, July 27 is not here: its gain is within the replay's error; it has its own chart, skhx_0727.)
    (The overnight walk of the external price is not here: its five-minute window against a 30-minute average overstates it.)"""
    ML = maxlev()
    v = lambda f, *a: (f("today", *a), f("prop", *a))
    tk = {(c, d): tuple(fvault(f"{FIN}/oos", f"{c}_{d}_{RUN[k][0]}", ML[c])["tk"] for k in ("today", "prop")) for c, d in OOS}
    days = {d: sum(t[0] for (c, dd), t in tk.items() if dd == d) for _, d in OOS}
    big = max(days, key=days.get)   # the day with most takeovers under today's rules
    one, rest = [k for k in tk if k[1] == big], [k for k in tk if k[1] != big]
    if not all(c in ("BRENTOIL", "CL") for c, _ in one):
        raise SystemExit(f"figs: headline: the day with most takeovers ({big}) is not the oil day: {one}; the row's label would be wrong")
    tot = lambda ks: tuple(sum(tk[k][i] for k in ks) for i in (0, 1))
    rows = [
        (f"ADL in {WORDS[len(ISO)]} replays of\nisolated-only markets", *v(f_iso), lambda x: rf"\${x * 1e3:.1f}k"),   # one decimal for both, as the paper's tables
        (f"Takeovers by the vault on\n{WORDS[len(one)]} oil markets, {mdate(big)}", *tot(one), n0),
        (f"Takeovers by the vault on\n{WORDS[len(rest)]} other market-days", *tot(rest), n0),
    ]
    print("figs: headline: takeovers today -> proposal: " + "; ".join(f"{c} {d} {a} -> {b}" for (c, d), (a, b) in tk.items()))
    # placed at 0.55 of the text width: drawn at that size (labels included) so the type is not scaled on the page
    fig, ax = hpairs([(None, rows)], 0.55 * W, height=1.42, norm="max", xaxis=False, h=0.36, msg="Today's rules and the proposal",
                     note="Each pair is drawn to its own scale.")
    save(fig, "headline")


# ---------------------------------------------------------------------------------------------------------------------
def mark_changes(event="GOOGL_1028"):
    """Change 1: the three votes and the mark, update by update, in a real crash (two votes fall together, the mark follows)
    and when the feed sends a wrong price (one vote falls, the mark stays).
    Reads data/scen/final/crash/orc_{event}_{today,lead3q1800}.csv and spike/orc_GOOGL_{today,pkgm3q1800}_q30s.csv, _base.csv
    (see fmarks): the proposal's votes are m1 (the external price as it votes; where it differs from ext, the feed repeated a
    value, counts as not live and votes with xyz's own price: those updates are pointed out), m2 (the 30-minute average) and xyz's book.
    The size and length of the wrong price in the panel heading are measured on ext against the base run. Time zero: the end
    of the external price's fastest 60 s fall (left), the first wrong update (right). "Anchor" is the paper's name for the
    30-minute average, which is also held between the feed's vote and the previous mark (so it can move fast in a crash)."""
    c = {k: fmarks(f"{FIN}/crash", f"{event}_{RUN[k][1]}") for k in RUN}
    t0 = fall_start(c["today"])
    s = {k: fmarks(f"{FIN}/spike", f"GOOGL_{RUN[k][0]}_q30s") for k in RUN}
    w = s["prop"].join(fmarks(f"{FIN}/spike", f"GOOGL_{RUN['prop'][0]}_base").select("h", Eb="E"), on="h").with_columns(d=(pl.col("E") / pl.col("Eb") - 1) * 100).filter(pl.col("d").abs() > 0.5)
    if w.height == 0:
        raise SystemExit("figs: mark_changes: no wrong price found in the spike run")
    s0, depth, secs = w["ms"][0], -w["d"].median(), (w["ms"][-1] - w["ms"][0]) / 1000 + 3

    moved = -float(flift(f"{FIN}/spike", f"GOOGL_{RUN['prop'][0]}_q30s", f"GOOGL_{RUN['prop'][0]}_base")[0].filter(pl.col("ms").is_between(s0, s0 + (secs + 120) * 1000))["g"].min())
    fig, axs = plt.subplots(1, 2, figsize=(0.68 * W + 0.68, 1.75), gridspec_kw=dict(wspace=0.34))   # placed at 0.68 of the text width
    L, H = -30, 210
    for ax, d, z, lo, hi in ((axs[0], c, t0, L, H), (axs[1], s, s0, -15, 75)):
        p, t = (d[k].filter(pl.col("ms").is_between(z + lo * 1000, z + hi * 1000)) for k in ("prop", "today"))
        x = lambda q: (q["ms"].to_numpy() - z) / 1000
        ax.plot(x(p), p["B"], color=GREY, lw=2.6, alpha=0.75, label="xyz's order book")
        ax.plot(x(p), p["A"], color=TEAL, lw=1.3, ls=(0, (1, 1.4)), label="Anchor")
        ax.plot(x(p), p["V"], color=INK, lw=0.9, label="The feed's vote")
        own = p.filter(((pl.col("V") / pl.col("E") - 1).abs() > 5e-4))   # updates where the feed's vote is visibly not the external price (more than 0.05% away)
        if own.height:
            xo, lo_y, hi_y = x(own), float(p["V"].min()), float(p["V"].max())
            ax.annotate("the feed repeats a value:\nfor these updates it votes\nwith xyz's own price", (xo[-1], own["V"][-1]), xytext=(hi - 2, lo_y + 0.1 * (hi_y - lo_y)),
                        ha="right", va="center", fontsize=7, color=INK, linespacing=1.2, arrowprops=dict(arrowstyle="-", color=INK, lw=0.6, shrinkA=2, shrinkB=2))
        ax.plot(x(t), t["mk"], color=TODAY, lw=1.3, label="Today's mark")
        ax.plot(x(p), p["mk"], color=LEAD, lw=1.7, ls=(0, (4, 1.5)), label="Proposal's mark")
        ax.set_xlim(lo, hi)
    # the stretch where the anchor stays above the mark: the rule holds the anchor between the feed's vote and the previous
    # mark only when xyz's book was NOT strictly between the feed's vote and the anchor at the previous update
    q = c["prop"].sort("ms").with_columns(Bp=pl.col("B").shift(1), Vp=pl.col("V").shift(1), Ap=pl.col("A").shift(1)).with_columns(
        btw=(pl.col("Bp") > pl.min_horizontal("Vp", "Ap")) & (pl.col("Bp") < pl.max_horizontal("Vp", "Ap")), gap=(pl.col("A") / pl.col("mk") - 1) * 100,
        x=(pl.col("ms") - t0) / 1000).filter(pl.col("x").is_between(L, H) & (pl.col("gap") > 1.5))
    if q.height:
        if not q["btw"].all():
            raise SystemExit(f"figs: mark_changes: the anchor is more than 1.5% above the mark on {q.height} updates, and on {q.height - int(q['btw'].sum())} of them the book was not between the two other votes: the note on the chart would be wrong")
        m_ = q.row(q.height // 2, named=True)
        axs[0].annotate(f"xyz's book is between\nthe feed and the anchor:\nthe anchor stays up to\n{q['gap'].max():.1f}% above the mark", (m_["x"], m_["A"]), xytext=(L + 0.42 * (H - L), float(c["prop"]["A"].filter(c["prop"]["ms"].is_between(t0 + L * 1000, t0 + H * 1000)).max())),
                        fontsize=7, color=INK, linespacing=1.15, ha="left", va="top", arrowprops=dict(arrowstyle="-", color=INK, lw=0.6, shrinkA=1, shrinkB=2, relpos=(0, 0.5)))
        print(f"figs: mark_changes: anchor above the mark by more than 1.5% from {q['x'].min():.0f} s to {q['x'].max():.0f} s ({q.height} updates, book between the two other votes on all of them), up to {q['gap'].max():.2f}%")
    axs[0].set_xlabel("Seconds from the start of the fall"); axs[1].set_xlabel("Seconds from the first wrong price")
    for ax in axs: ax.set_ylabel(f"{name(event.split('_')[0])} price (USD)")
    same = c["prop"].filter(pl.col("ms").is_between(t0 + L * 1000, t0 + H * 1000)).select(((pl.col("V") / pl.col("E") - 1).abs() > 5e-4).sum()).item() == 0
    panel(axs[0], f"A real crash ({mdate(event[-4:])}):\nthe mark follows")
    panel(axs[1], f"The feed is {depth:.0f}% too low for {secs:.0f} s:\nthe proposal's mark moves {moved:.2f}%")
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower left", bbox_to_anchor=(0.04, 1.08), ncol=3, handlelength=1.8, handletextpad=0.5, columnspacing=1.3, borderaxespad=0.2)
    if os.environ.get("TITLES") != "0":
        fig.suptitle(f"The mark is the middle one of three prices:\na {secs:.0f}-second wrong price barely moves it", x=0.04, y=1.29, ha="left", va="bottom", fontsize=9.5, fontweight="bold")
    if not same: print("figs: mark_changes: in the crash panel the feed's vote is not always the external price")
    save(fig, "mark_changes")


# ---------------------------------------------------------------------------------------------------------------------
def closed_attacks():
    """Change 2: someone pushes xyz's book while the external price is not live. How far the mark is moved, minute by minute.
    Reads data/scen/final/closed_CL, closed_GOLD (orc_{C}_{mark}_c5e6_f0.06_d900.csv against _base.csv: a push of 15 minutes,
    the longest tested) and quiet_up (orc_GOOGL_{mark}_c5e6_f0.06_d9000.csv against _base.csv: a bid held 2.5 hours while the
    feed is quiet). Line = mark of the pushed run / mark of the same run without the push - 1 (flift); time zero = the first
    update where the two books differ; the shaded band is the length of the push, read from the run's name. Labels: the peak
    of each line for the 15-minute pushes; for the push of hours the value when it ends (what the paper's text quotes) and
    the proposal's lift after one hour. "External price live again" = the first update after the push where ext changes."""
    # per panel: heading, folder, market, run, minutes shown, and where the two peak labels go (offset in points, alignment)
    P = [("Crude oil, daily break:\npushed for 15 minutes", f"{FIN}/closed_CL", "CL", "c5e6_f0.06_d900", 60, ((6, -1), "left", "center"), ((-5, 5), "right", "bottom")),
         ("Gold, weekend:\npushed for 15 minutes", f"{FIN}/closed_GOLD", "GOLD", "c5e6_f0.06_d900", 120, ((0, 5), "left", "bottom"), ((16, 9), "left", "bottom")),
         ("Alphabet overnight, quiet feed:\na bid held for 2.5 hours", f"{FIN}/quiet_up", "GOOGL", "c5e6_f0.06_d9000", 180, None, None)]
    fig, axs = plt.subplots(1, 3, figsize=(0.87 * W + 0.95, 1.82), sharey=True, gridspec_kw=dict(wspace=0.1))   # placed at 0.87 of the text width
    for n_, (ax, (head, T, c, tag, xmax, lt_, lp_)) in enumerate(zip(axs, P)):
        dur = int(tag.split("_d")[1]) / 60
        ax.axvspan(0, dur, color="#F1EFEA", lw=0, zorder=0)
        ax.text(dur / 2 if dur > 60 else 1, -0.25, "push" if dur <= 60 else "the bid is held", fontsize=7, color=MUTE, ha="center" if dur > 60 else "left", va="center")
        for k, col, ls in (("today", TODAY, "-"), ("prop", LEAD, (0, (4, 1.5)))):
            j, t0 = flift(T, f"{c}_{RUN[k][0]}_{tag}", f"{c}_{RUN[k][0]}_base")
            if t0 is None:
                raise SystemExit(f"figs: closed_attacks: the pushed book of {c} never differs from the base run")
            t0 = t0 // 60000 * 60000
            j = j.with_columns(x=(pl.col("ms") - t0) / 60e3, chg=pl.col("E") != pl.col("E").shift(1)).filter(pl.col("x").is_between(-xmax * 0.06, xmax))
            ax.plot(j["x"], j["g"], color=col, lw=1.6, ls=ls, label="Today" if k == "today" else "Proposal")
            tc, wt = (INK, "bold") if k == "today" else (LEAD, "bold")
            if dur < 120:   # a short push: label the peak
                i = int(j["g"].arg_max())
                ax.annotate(pct2(j["g"].max()), (j["x"][i], j["g"].max()), xytext=(lt_ if k == "today" else lp_)[0], textcoords="offset points", fontsize=7.5, fontweight=wt, color=tc, ha=(lt_ if k == "today" else lp_)[1], va=(lt_ if k == "today" else lp_)[2])
            else:           # a push of hours: label the value when it ends, and how fast the proposal's mark follows
                e = j.filter(pl.col("x") <= dur).row(-1, named=True)
                ax.annotate(pct2(e["g"]), (e["x"], e["g"]), xytext=(-30, 6) if k == "today" else (5, 2), textcoords="offset points", fontsize=7.5, fontweight=wt, color=tc, va="bottom", ha="left")
                if k == "prop":
                    rate = float(j.filter(pl.col("x") <= 60)["g"][-1])
                    ax.annotate(f"about {rate:.0f}%\nan hour", (60, rate), xytext=(8, rate + 0.75), linespacing=1.15, fontsize=7.5, color=LEAD, fontweight="bold", va="bottom", ha="left",
                                arrowprops=dict(arrowstyle="-", color=LEAD, lw=0.6, shrinkA=1, shrinkB=2))
            if k == "prop":
                live = j.filter((pl.col("x") > dur) & pl.col("chg"))
                if live.height:
                    xl_, g_ = live["x"][0], float(j.filter(pl.col("x") < live["x"][0])["g"][-1])
                    if g_ > 0.1:
                        ax.annotate("external price\nlive again", (xl_, g_), xytext=(-4, 12) if dur < 120 else (-22, -52), textcoords="offset points", fontsize=7, color=MUTE, ha="center" if dur < 120 else "right", va="bottom", linespacing=1.15,
                                    arrowprops=dict(arrowstyle="-", color=MUTE, lw=0.6, shrinkA=1, shrinkB=2))
        ax.set_xlim(-xmax * 0.06, xmax); ax.set_xlabel("Minutes from the start of the push")
        ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(xmax / 4))
        panel(ax, head)
    axs[0].set_ylim(-0.5, 7.3); axs[0].yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}%"))
    axs[0].set_ylabel("How far the push moves the mark")
    axs[1].legend(loc="upper right", handlelength=1.8, borderaxespad=0.3)
    title(axs[0], "When the external price is not live: today a push on xyz's book moves the mark\nat once; under the proposal a short push moves it slowly", y=34)
    axs[0].annotate("Replay uses the book's mid for the documented impact price; today's figures may be overstated.", (0, 0), xytext=(0, -30), xycoords="axes fraction", textcoords="offset points",
                    fontsize=7, color=MUTE, va="top", ha="left", annotation_clip=False)
    save(fig, "closed_attacks")


# ---------------------------------------------------------------------------------------------------------------------
def cutback():
    """Change 3 in numbers: the large positions of the three crashes under today's rules, under the proposal's mark with today's
    sizing (a first order of 20% of the position, then full-size orders, 30 s apart), and under the proposal (its mark and cut back to margin).
    Reads data/scen/final/liqstudy/liqbook_summary.csv (sim/score/liqbook_eval.py), rows events = 'crashes', designs today,
    lead3q1800s20 and lead3q1800: share_depth_p90 (fraction), impact_p90_bp, book_musd, vault_musd, positions."""
    d = need(f"{FIN}/liqstudy/liqbook_summary.csv", ("design", "events", "share_depth_p90", "impact_p90_bp", "book_musd", "vault_musd", "positions")).filter(pl.col("events") == "crashes")
    def one(des):
        r = d.filter(pl.col("design") == des)
        if r.height != 1:
            raise SystemExit(f"figs: cutback: {r.height} rows for design '{des}' in liqbook_summary.csv")
        return r.row(0, named=True)
    R = [(one("today"), dict(color=TODAY), INK, "normal", "Today's rules"),
         (one("lead3q1800s20"), dict(color=MIX, hatch="...", edgecolor="white", lw=0), MIX, "normal", "Proposal's mark with today's sizing (20% first, then full size)"),
         (one("lead3q1800"), dict(color=LEAD, hatch="////", edgecolor="white", lw=0), LEAD, "bold", "Proposal (its mark, and cut back to margin)")]
    if len({r["positions"] for r, *_ in R}) != 1:
        raise SystemExit(f"figs: cutback: the designs do not cover the same positions ({[r['positions'] for r, *_ in R]})")
    P = [("Share of nearby\nbook one sale\ntakes (worst\ntenth of sales)", "share_depth_p90", 100, lambda v: f"{v:.0f}%"),
         ("Best price\nmoved by one\nsale (worst\ntenth of sales)", "impact_p90_bp", 0.01, pct2),
         ("Sold in the\norder book", "book_musd", 1, usd), ("Inherited by\nthe vault", "vault_musd", 1, usd)]
    fig, axs = plt.subplots(1, 4, figsize=(0.80 * W + 1.15, 0.95), gridspec_kw=dict(wspace=0.3))   # drawn for 0.80 of the text width
    for ax, (head, col, k, fmt) in zip(axs, P):
        top = max(r[col] * k for r, *_ in R)
        for x, (r, kw, tc, wt, lab) in enumerate(R):
            ax.bar(x, r[col] * k, width=0.7, label=lab, **kw)
            v_ = r[col] * k
            ax.text(x - 0.33 if x == 2 else x, v_ + top * 0.03, fmt(v_), ha="left" if x == 2 else "center", va="bottom", fontsize=7, color=tc, fontweight=wt)
        ax.set_xlim(-0.6, 2.9); ax.set_ylim(0, top * 1.16); ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
        ax.annotate(head, (0, 1), xytext=(0, 4), xycoords="axes fraction", textcoords="offset points", fontsize=7.5, fontweight="bold", va="bottom", ha="left", annotation_clip=False, linespacing=1.15)
    fig.legend(*axs[0].get_legend_handles_labels(), loc="lower left", bbox_to_anchor=(0.1, -0.5), ncol=1, handlelength=1.4, handletextpad=0.5, borderaxespad=0, fontsize=7, labelspacing=0.3)
    save(fig, "cutback")


# ---------------------------------------------------------------------------------------------------------------------
def cutback_how(event="INTC_1029", u=3529, xlo=-12, xhi=78):
    """Change 3 at work: one real large position through a crash under the two sizing rules, both with the proposal's mark,
    side by side. The left panel is therefore not today's rules (it is drawn in gray, not orange): only the sizing differs. The position is the largest of the 23 of the liquidation study that is sold in more than one round.
    Reads data/scen/final/liqstudy: liq_{event}_{lead3q1800s20,lead3q1800}.csv, rows of account u (ms, q = position before
    the sale, filled, avg_px, mark), tk_{event}_*.csv (what the vault took over: h, q) and orc_{event}_*.csv (mark and xyz's
    book price, fmarks). Top: share of the position still open, with what was sold before the fall, what was sold in it and
    how far below the mark, and what the vault took. Bottom: the mark, xyz's book price and the price of each sale.
    The shaded part starts at the update before the book price's largest one-update fall (the same update in both runs)."""
    T = f"{FIN}/liqstudy"
    S = [("lead3q1800s20", "Proposal's mark with today's sizing:\n20% first, then full size", MIX), ("lead3q1800", "Proposal: its mark\nand cut back to margin", LEAD)]
    fig, axs = plt.subplots(2, 2, figsize=(0.92 * W + 0.55, 1.9), sharex=True, sharey="row", height_ratios=[1.65, 1], gridspec_kw=dict(hspace=0.12, wspace=0.06))   # placed at 0.92 of the text width
    t0 = q0 = None; sold = {}
    for k, (des, head, col) in enumerate(S):
        a, b = axs[0][k], axs[1][k]
        l = need(f"{T}/liq_{event}_{des}.csv", ("ms", "u", "q", "filled", "avg_px", "mark")).filter(pl.col("u") == u).sort("ms")
        if l.height < 2:
            raise SystemExit(f"figs: cutback_how: account {u} has {l.height} sales under {des} in {event}")
        if t0 is None: t0, q0 = l["ms"][0], l["q"][0]
        m = fmarks(T, f"{event}_{des}").with_columns(x=(pl.col("ms") - t0) / 1000).filter(pl.col("x").is_between(xlo, xhi))
        fall = m.with_columns(d=pl.col("B").shift(-1) / pl.col("B") - 1).drop_nulls("d").sort("d").head(1)["x"][0]
        l = l.with_columns(x=(pl.col("ms") - t0) / 1000, sh=100 * pl.col("filled") / q0, below=(1 - pl.col("avg_px") / pl.col("mark")) * 100)
        pre, post = l.filter(pl.col("x") <= fall), l.filter(pl.col("x") > fall)
        sold[des] = float(pre["sh"].sum())
        xs, ys, left = [xlo], [100.0], 100.0
        for r in l.iter_rows(named=True):
            xs += [r["x"], r["x"]]; ys += [left, left - r["sh"]]; left -= r["sh"]
        tk = ftk(T, f"{event}_{des}")
        tk = tk.filter(pl.col("u") == u).join(fmarks(T, f"{event}_{des}").select("h", "ms"), on="h", how="left") if tk is not None else None
        if tk is not None and tk.height:
            xv = (tk["ms"][0] - t0) / 1000; xs += [xv, xv, xhi]; ys += [left, 0, 0]
        else: xs += [xhi]; ys += [left]
        for ax in (a, b): ax.axvspan(fall, xhi, color="#F1EFEA", lw=0, zorder=0)
        a.fill_between(xs, ys, color=col, alpha=0.13, lw=0); a.plot(xs, ys, color=col, lw=1.7)
        a.annotate(f"Sold before\nthe fall: {sold[des]:.0f}%", ((fall + (0 if sold[des] < 50 else 8)) / 2, 100 - sold[des] - 22 if sold[des] < 50 else 76),
                   ha="center", va="center", fontsize=8.5, fontweight="bold", color=col, linespacing=1.15)
        if post.height == 1: txt = f"{post['sh'][0]:.0f}% in one block,\n{post['below'][0]:.1f}% below\nthe mark"
        else: txt = " and ".join(f"{v:.0f}%" for v in post["sh"]) + f" in {WORDS.get(post.height, post.height)} sales,\n" + " and ".join(f"{v:.1f}%" for v in post["below"]) + " below\nthe mark"
        a.text(fall + 11, 62, "Sold in the fall:\n" + txt, fontsize=7.3, color=INK, va="center", ha="left", linespacing=1.2)
        if tk is not None and tk.height:
            a.plot([xv], [left], "s", color=VAULT, ms=4.5, zorder=5)
            a.text(fall + 11, 15, f"The vault takes\nthe last {left:.0f}%", fontsize=7.3, color=VAULT, fontweight="bold", va="center", ha="left", linespacing=1.2)
        b.plot(m["x"], m["B"], color=GREY, lw=2.2, alpha=0.8, label="xyz's order book")
        b.plot(m["x"], m["mk"], color=DARK, lw=1.0, ls=(0, (3, 1.5)), label="Mark")
        b.scatter(l["x"], l["avg_px"], s=(10 + l["sh"] * 1.6).to_numpy(), color=col, edgecolor="white", lw=0.5, zorder=4)
        prev = None
        for r in l.iter_rows(named=True):   # each dot carries its share; a dot right after another one is labeled on its right
            rad = ((10 + r["sh"] * 1.6) ** 0.5) / 2
            near = prev is not None and r["x"] - prev < 6
            b.annotate(f"{r['sh']:.0f}%", (r["x"], r["avg_px"]), xytext=(rad + 5, -9) if near else (0, -rad - 1.5), textcoords="offset points",
                       ha="left" if near else "center", va="center" if near else "top", fontsize=7, color=col, fontweight="bold", zorder=5)
            prev = r["x"]
        b.set_xlim(xlo, xhi); b.set_xlabel("Seconds from the first forced sale")
        a.text(fall + 1.5, 103, "the book price falls", fontsize=7, color=MUTE, va="bottom", ha="left")
        panel(a, head)
    axs[0][0].set_ylim(0, 112); axs[0][0].set_yticks([0, 25, 50, 75, 100]); axs[0][0].yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}%"))
    axs[0][0].set_ylabel("Share of the position\nstill open"); axs[1][0].set_ylabel("Price (USD)")
    lo, hi = axs[1][0].get_ylim(); axs[1][0].set_ylim(lo - 0.45 * (hi - lo), hi)   # room for the share under the lowest dot
    h, lb = axs[1][0].get_legend_handles_labels()
    dot = lambda c: matplotlib.lines.Line2D([], [], marker="o", ls="", color=c, ms=5.5, mec="white", mew=0.5)
    fig.legend(h + [(dot(MIX), dot(LEAD))], lb + ["A forced sale, at the price it got (dot area and label = share of the position sold)"],
               handler_map={tuple: matplotlib.legend_handler.HandlerTuple(ndivide=None, pad=0.3)}, loc="upper center", bbox_to_anchor=(0.5, -0.075),
               ncol=3, handlelength=1.8, handletextpad=0.5, columnspacing=1.3, borderaxespad=0, fontsize=7.5)
    first = pl.read_csv(f"{T}/liqbook_positions.csv").filter((pl.col("event") == event) & (pl.col("u") == u))["ntl0"][0] / 1e6
    a, b = (sold[d] for d, _, _ in S)
    title(axs[0][0], f"A {usd(first)} long on {name(event.split('_')[0])}, {mdate(event[-4:])}: when the book price falls, today's sizing\nhas sold {a:.0f}% and sells most of the rest in one block; cut back has sold {b:.0f}%", y=31)
    save(fig, "cutback_how")


# ---------------------------------------------------------------------------------------------------------------------
def feed_age():
    """Change 6: how often the published external price does not change from one update to the next, overnight against regular hours.
    Reads data/scen/e_quality_coin_session.csv (sim/study/e_quality.py): one row per market, day and session with us (US-listed),
    session (overnight, regular), stale_pct (share of updates where the external price is unchanged), updates, day (MMDD).
    One count per market-day; the medians are marked; the days and the number of markets are named under the axis.
    (The file has no 'longest unchanged stretch' column.) Prints the pooled overnight share (all updates together)."""
    d = need(f"{SC}/e_quality_coin_session.csv", ("coin", "day", "session", "us", "stale_pct", "updates")).filter(pl.col("us") & (pl.col("updates") > 0))
    n = [d.filter(pl.col("session") == x).height for x in ("regular", "overnight")]
    days = sorted(f"{int(v):04d}" for v in d["day"].unique())
    S = [("regular", "Regular trading hours", dict(color=TEAL, alpha=0.85, edgecolor="white", lw=0.6), TEAL),
         ("overnight", "Overnight", dict(facecolor=(0.79, 0.58, 0.17, 0.35), edgecolor=GOLD, lw=0.9, hatch="////"), "#8F6A12")]   # neither is today's rules or the proposal: teal, and gold hatched
    fig, ax = plt.subplots(figsize=(0.66 * W + 0.6, 1.4))   # placed at 0.66 of the text width
    bins = list(range(0, 105, 5))
    for i, (ses, lab, kw, tc) in enumerate(S):
        v = d.filter(pl.col("session") == ses)["stale_pct"]
        if v.len() == 0:
            raise SystemExit(f"figs: feed_age: no US rows for session '{ses}'")
        ax.hist(v, bins=bins, label=lab, zorder=2 + i, **kw)
        ax.axvline(v.median(), color=tc, lw=1.1, ls=(0, (4, 2)), zorder=5)
        ax.annotate(f"half of market-days\nabove {v.median():.0f}%", (v.median(), 1), xycoords=("data", "axes fraction"), xytext=(-4, -2), textcoords="offset points",
                    ha="right", va="top", fontsize=7.5, color=tc, fontweight="bold", linespacing=1.2)
    ax.set_xlim(0, 100); ax.set_xticks(range(0, 101, 20)); ax.set_xticklabels([f"{v}%" for v in range(0, 101, 20)])
    months = sorted({calendar.month_name[int(x[:2])] for x in days})
    per = d.filter(pl.col("session") == "overnight").group_by("coin").agg(k=pl.col("day").n_unique()).group_by("k").agg(m=pl.len()).sort("k", descending=True)   # markets by number of days covered
    foot = " and ".join(f"{r_['m']}{' US-listed markets' if i == 0 else ''} on {WORDS.get(r_['k'], r_['k'])}{' days' if i == 0 else ''}" for i, r_ in enumerate(per.iter_rows(named=True)))
    ax.set_xlabel("Share of updates in which the published external price did not change\n"
                  f"{foot} in {' and '.join(months)} ({n[0]} market-days per session)" if len(set(n)) == 1 else foot, fontsize=7.5, linespacing=1.3)
    ax.set_ylabel("Market-days")
    top_legend(ax, y=1.0)
    title(ax, "Overnight, the published external price is unchanged\non most updates", y=22)
    o = d.filter(pl.col("session") == "overnight")
    print(f"figs: feed_age: overnight, all updates pooled: {float((o['stale_pct'] * o['updates']).sum() / o['updates'].sum()):.1f}% unchanged")
    save(fig, "feed_age")


# ---------------------------------------------------------------------------------------------------------------------
# the rest of the three crash days, as sim/score/normal_eval.py: prep folder (block times), start of the replayed day (20:00 UTC, the US close), crash onset (ms after it)
NORMAL = {"GOOGL": ("prep_GOOGL_1028", 1793217600000, 118_800), "INTC": ("prep_INTC_1029", 1793304000000, 66_800), "AMZN": ("prep_AMZN_1029", 1793304000000, 63_900)}


PRE, POST = 60_000, 1_800_000   # the crash window left out: from 60 s before the onset to 30 minutes after (ms)


def wallets(coin, day, uids):
    """Wallet addresses of the account numbers `uids` of one rebuilt market-day (data/users/users_{coin}_{day}.arrow: uid, user).
    Every market-day numbers its accounts from 0, so accounts of different markets are compared by address, never by number."""
    p = f"{ROOT}/data/users/users_{coin}_{day}.arrow"
    if not os.path.exists(p):
        raise SystemExit(f"figs: {p} is missing: fetch the address tables (ec2/users_launch.sh, see REPRODUCE.md)")
    t = pl.read_ipc(p, columns=["uid", "user"])
    m = dict(zip(t["uid"].to_list(), t["user"].to_list()))
    miss = [u for u in uids if u not in m]
    if miss:
        raise SystemExit(f"figs: {len(miss)} account numbers of {coin} {day} have no address in {p}")
    return [m[u] for u in uids]


def normal_days():
    """Outside the crashes: a random sample of market-days and one whole day of 33 markets, today against the proposal, with
    the rest of the three crash days as a smaller, secondary panel. No new replay: existing outputs only.
      Random sample: data/scen/joint_randnh/random_sample_scored.csv (sim/final/score_random.py), rows status = ok:
        today_liquidated, proposal_liquidated (accounts liquidated in the order book), today_takeovers, proposal_takeovers
        (positions that reach the backstop; their dollars are summed from the same folder's tk_ files, for the note).
      33 markets together on November 5: data/scen/joint_nohold/joint_1105.csv (sim/score/joint_eval.py), designs today and
        lead3q1800: coins, vault_inherited_M, adl_M; accounts liquidated = accounts with sim_rounds > 0 in
        rd_{COIN}_1105_{design}.csv, summed over the markets of joint_1105_coins.csv (as score_random.py counts them);
        different traders = distinct wallet addresses of those accounts (wallets()).
      Rest of the three crash days: data/scen/final/normal/{tk,rd}_{COIN}_{today,pkgm3q1800}.csv and data/prep_*/blocks.arrow,
        scored as sim/score/normal_eval.py: outside regular hours (13:30-20:00 UTC), crash window (PRE before the onset to POST
        after) left out; accounts = those with a liquidation in the book (rd, sim_rounds > 0) or a takeover (tk)."""
    DES = {"today": "today", "prop": "lead3q1800"}
    r = need(f"{SC}/joint_randnh/random_sample_scored.csv", ("status", "coin", "date", "today_liquidated", "proposal_liquidated", "today_takeovers", "proposal_takeovers")).filter(pl.col("status") == "ok")
    J = f"{SC}/joint_nohold"
    j = need(f"{J}/joint_1105.csv", ("design", "coins", "vault_inherited_M", "adl_M"))
    jr = {k: j.filter(pl.col("design") == d).row(0, named=True) for k, d in DES.items()}
    coins = need(f"{J}/joint_1105_coins.csv", ("coin",))["coin"].to_list()
    if len(coins) != jr["today"]["coins"]:
        raise SystemExit(f"figs: normal_days: {len(coins)} markets listed, {jr['today']['coins']} in joint_1105.csv")
    acc = {k: [need(f"{J}/rd_{c}_1105_{d}.csv", ("u", "sim_rounds")).filter(pl.col("sim_rounds").cast(pl.Float64) > 0)["u"].to_list() for c in coins] for k, d in DES.items()}
    jl = {k: sum(len(x) for x in v) for k, v in acc.items()}           # an account counts once per market
    # distinct traders over the 33 markets: account numbers start from 0 in every market (sim/prep/prep.py), so they are mapped
    # to wallet addresses first (data/users/users_{COIN}_1105.arrow, fetched by ec2/users_launch.sh)
    ju = {k: len({w for c, x in zip(coins, v) for w in wallets(c, "1105", x)}) for k, v in acc.items()}
    # rest of the three crash days
    T = f"{FIN}/normal"; rest = {"today": 0, "prop": 0}; per = {}
    for c, (prep, day, onset) in NORMAL.items():
        p = f"{ROOT}/data/{prep}/blocks.arrow"
        if not os.path.exists(p):
            raise SystemExit(f"figs: missing file {p}")
        blk = pl.read_ipc(p).select("h", "ms")
        hour = (pl.col("ms") % 86_400_000) / 3_600_000
        keep = lambda d: d.filter(~hour.is_between(13.5, 20, closed="left") & ~pl.col("ms").is_between(day + onset - PRE, day + onset + POST))
        for k in rest:
            m = RUN[k][0]
            tk = keep(pl.read_csv(f"{T}/tk_{c}_{m}.csv", schema_overrides={"u": pl.Int64, "h": pl.Int64}).join(blk, on="h"))
            rd = keep(need(f"{T}/rd_{c}_{m}.csv", ("u", "sim_h1", "sim_rounds")).filter(pl.col("sim_rounds") > 0).join(blk.rename({"h": "sim_h1"}), on="sim_h1"))
            per[c, k] = len(set(tk["u"]) | set(rd["u"])); rest[k] += per[c, k]
    cnt = lambda v: f"{v:,.0f}"
    usd2 = lambda v: rf"\${round(v, 2):.2f}M" if v >= 1 else usd(round(v, 2))   # to the nearest \$10k, as the paper's text writes these two amounts
    P = [(f"{r.height} random\nmarket-days:\naccounts\nliquidated", r["today_liquidated"].sum(), r["proposal_liquidated"].sum(), cnt, True),
         (f"{len(coins)} markets,\nNovember 5:\naccounts\nliquidated", jl["today"], jl["prop"], cnt, True),
         (f"{len(coins)} markets,\nNovember 5:\ninherited by\nthe vault", jr["today"]["vault_inherited_M"], jr["prop"]["vault_inherited_M"], usd2, True),
         (f"{len(coins)} markets,\nNovember 5:\nADL", jr["today"]["adl_M"], jr["prop"]["adl_M"], usd, True),
         ("Rest of the\nthree crash\ndays: accounts\nliquidated", rest["today"], rest["prop"], cnt, False)]
    n0_, n1_ = int(r["today_takeovers"].sum()), int(r["proposal_takeovers"].sum())
    def dust(des):   # dollars of the positions that reach the backstop on the sampled market-days, from the run's tk_ files
        tot = 0.0
        for x in r.iter_rows(named=True):
            t = ftk(f"{SC}/joint_randnh", f"{x['coin']}_{x['date'][5:7]}{x['date'][8:]}_{des}")
            if t is not None: tot += float(t["ntl"].sum())
        return tot
    k0, k1 = dust("today"), dust("lead3q1800")
    days = ", ".join(f"{name(c)} {mdate(NORMAL[c][0][-4:])}" for c in NORMAL)
    Q, fs, fh = P, 7.0, 7.5
    fig, axs = plt.subplots(1, len(Q), figsize=(0.80 * W + 0.85, 0.9), gridspec_kw=dict(wspace=0.45))   # drawn for 0.80 of the text width (the variant for 0.56)
    for ax, (head, va, vb, fmt, main) in zip(axs, Q):
        al = 1.0 if main else 0.45   # the secondary panel is drawn lighter
        ax.bar(0, va, width=0.62, color=TODAY, alpha=al, label="Today")
        ax.bar(1, vb, width=0.62, color=LEAD, hatch="////", edgecolor="white", lw=0, alpha=al, label="Proposal")
        top = max(va, vb)
        # each label is anchored on the outer side of its bar's middle, so a wide one grows away from the other bar
        ax.text(0.12, va + top * 0.03, fmt(va), ha="right", va="bottom", fontsize=fs, color=INK if main else MUTE)
        ax.text(0.88, vb + top * 0.03, fmt(vb), ha="left", va="bottom", fontsize=fs, color=LEAD, fontweight="bold" if main else "normal", alpha=1 if main else 0.7)
        ax.set_xlim(-0.75, 1.75); ax.set_ylim(0, top * 1.18); ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
        ax.annotate(head, (0, 1), xytext=(0, 4), xycoords="axes fraction", textcoords="offset points", fontsize=fh, fontweight="bold" if main else "normal", color=INK if main else MUTE,
                    va="bottom", ha="left", annotation_clip=False, linespacing=1.15)
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower left", bbox_to_anchor=(0.1, -0.22), ncol=2, handlelength=1.4, handletextpad=0.5, columnspacing=1.4, borderaxespad=0, fontsize=7)
    note = (f"Each panel has its own scale. Random market-days: {n0_} positions (\\${k0:,.0f} together) reach the backstop today, {n1_} (\\${k1:,.0f}) under\n"
            f"the proposal. November 5 counts an account once per market ({ju['today']:,} / {ju['prop']:,} different accounts).\n"
            "The last panel is faded because it is a weaker test: the rest of the days Alphabet, Intel and Amazon crashed,\noutside regular hours and the crash window.")
    fig.text(0.1, -0.29, note, fontsize=7, color=MUTE, va="top", ha="left", linespacing=1.25)
    print(f"figs: normal_days: November 5 accounts liquidated, market by market {jl['today']:,} / {jl['prop']:,}; different accounts {ju['today']:,} / {ju['prop']:,}")
    save(fig, "normal_days")




# ---------------------------------------------------------------------------------------------------------------------
def attacks():
    """Every attack replayed, today against the proposal, with what the proposal does not stop set apart.
    Bar length = share of the larger value of the pair; labels are the measured values. Reads data/scen/final:
      spike/ q30s runs against base: takeover notional a wrong print adds, Alphabet + Amazon (f_print)
      adapt/GOOGL_night_dn, GOOGL_day_dn: positions liquidated in five minutes when the external price is walked 10% down,
        alone (base run) and followed by a 60 s push that empties xyz's bids (f_walk, fliq)
      closed_CL, closed_GOLD: largest mark lift over the pushes tested (f_closed)
      quiet_up: mark lift five minutes and 2.5 hours after a bid 6% above the market appears on a quiet feed (f_quiet)
      longprint/ the longest wrong price replayed (q900s) against base: largest move of the mark (flift); its size is measured on ext."""
    v = lambda f, *a: (f("today", *a), f("prop", *a))
    w = lambda c: tuple(max(f_closed(k, c)) for k in ("today", "prop"))
    et = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, zoneinfo.ZoneInfo("America/New_York")).strftime("%-I:%M %p ET").replace("AM", "am").replace("PM", "pm")
    n = len(f_closed("today", "CL"))
    # a wrong price that lasts: the longest one replayed (data/scen/final/longprint), largest move of the mark against the same replay without it
    T = f"{FIN}/longprint"
    tag = max((os.path.basename(f)[:-4].split("_")[-1] for f in glob.glob(f"{T}/orc_GOOGL_{RUN['today'][0]}_q*s.csv")), key=lambda t: int(t[1:-1]), default=None)
    if tag is None:
        raise SystemExit(f"figs: attacks: no lasting-wrong-price runs in {T}")
    long = tuple(-float(flift(T, f"GOOGL_{RUN[k][0]}_{tag}", f"GOOGL_{RUN[k][0]}_base")[0]["g"].min()) for k in ("today", "prop"))
    e = fmarks(T, f"GOOGL_{RUN['prop'][0]}_{tag}").join(fmarks(T, f"GOOGL_{RUN['prop'][0]}_base").select("h", Eb="E"), on="h").with_columns(d=(pl.col("E") / pl.col("Eb") - 1) * 100).filter(pl.col("d").abs() > 0.5)
    depth, mins = -e["d"].median(), int(tag[1:-1]) / 60
    groups = [
        ("Wrong price for 30 seconds: extra taken over by the vault", [
            ("5% too low", *v(f_print), lambda x: usd(float(f"{x:.2g}")))]),   # two significant figures, as the paper's tables print it
        ("Price walked 10% down over 30 seconds, held two minutes:\nliquidated within five minutes", [
            ("Overnight", *v(f_walk, "night"), usd),
            (f"After the close ({et(WALK['day'][1])})", *v(f_walk, "day"), usd)]),
        ("Push on xyz's book: mark moved by", [
            (f"Crude oil, daily break (worst of {WORDS.get(n, n)})", *w("CL"), pct2),
            (f"Gold, weekend (worst of {WORDS.get(n, n)})", *w("GOLD"), pct2),
            ("Quiet feed, bid 6% above, after 5 minutes", *v(f_quiet, 300), pct2)]),
        ("What remains: mark moved by", [
            (f"Wrong price {depth:.0f}% too low for {mins:.0f} minutes", *long, pct2),
            ("Quiet feed, the same bid held 2.5 hours", *v(f_quiet, 9000), pct2)]),
        ("What remains: liquidated within five minutes", [
            ("Overnight walk and xyz's bids emptied", *v(f_walk, "night", 60), usd)]),
    ]
    # placed at 0.60 of the text width and drawn at that size; the percent axis is left out (each label is the value)
    fig, ax = hpairs(groups, 0.60 * W, height=3.55, norm="max", fs=7, xaxis=False, h=0.34, msg="A short wrong price barely moves the mark;\na lasting one, or a held push, still does\n",
                     note="Each pair is drawn to its own scale.")
    save(fig, "attacks")


# ---------------------------------------------------------------------------------------------------------------------
def capital():
    """Vault capital: what a gap across every market needs, and how often history's moves exceed the vault.
    Reads data/scen/capital_risk_stress.csv (move_pct, C_MM_M: falls of up to 10%), capital_risk_levels.csv
    (return_period_years, C_MM_M, ci90_lo_M, ci90_hi_M) (sim/study/capital_risk.py), and the vault's equity from
    data/bs_portfolio.json (last accountValueHistory of the 'day' window, with its date)."""
    st = need(f"{SC}/capital_risk_stress.csv", ("move_pct", "C_MM_M"))
    lv = need(f"{SC}/capital_risk_levels.csv", ("return_period_years", "C_MM_M", "ci90_lo_M", "ci90_hi_M")).filter(pl.col("return_period_years") <= 10)   # the paper stops at ten years
    p = f"{ROOT}/data/bs_portfolio.json"
    if not os.path.exists(p):
        raise SystemExit(f"figs: missing file {p}")
    last = dict(json.load(open(p)))["day"]["accountValueHistory"][-1]
    vault, vday = float(last[1]) / 1e6, datetime.datetime.fromtimestamp(last[0] / 1000, datetime.timezone.utc)
    m2 = lambda v: rf"\${v:.2f}M" if v >= 1 else usd(v)   # two decimals: the ten-year level and the vault differ in the second

    # one vertical scale for both panels, so their bars compare; orange = clearly above the vault's balance (more than 5%)
    fig, (a, b) = plt.subplots(1, 2, figsize=(0.68 * W + 0.77, 2.08), sharey=True, gridspec_kw=dict(wspace=0.08))   # placed at 0.68 of the text width
    dn = st.filter(pl.col("move_pct").is_between(-10, -1)).with_columns(x=-pl.col("move_pct")).sort("x")
    xs = list(range(dn.height))
    over = lambda v: v > vault * 1.05   # clearly more than the vault holds: highlighted (a level within 5% of it is "about the vault's balance")
    a.bar(xs, dn["C_MM_M"], width=0.62, color=[TODAY if over(v) else TEAL for v in dn["C_MM_M"]])
    for i, v in enumerate(dn["C_MM_M"]):
        a.text(i, v + 0.2, usd(v), ha="center", va="bottom", fontsize=7.5, fontweight="bold" if over(v) else "normal")
    a.set_xticks(xs); a.set_xticklabels([f"{v:g}%" for v in dn["x"]], color=INK); a.tick_params(axis="x", length=0)
    a.set_xlabel("Every market falls at once by"); a.set_ylabel("Capital the vault needs (\\$M)")
    a.set_ylim(0, dn["C_MM_M"].max() * 1.12)
    panel(a, "If every market gapped at once")

    xs = list(range(lv.height))
    b.bar(xs, lv["C_MM_M"], width=0.62, color=[TODAY if over(v) else TEAL for v in lv["C_MM_M"]])
    near = [i for i, v in enumerate(lv["C_MM_M"]) if abs(v / vault - 1) <= 0.05]
    for i in near:
        b.annotate("about the\nvault's balance", (i, lv["ci90_hi_M"][i]), xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=7, color=VAULT, fontweight="bold", linespacing=1.15)
    b.errorbar(xs, lv["C_MM_M"], yerr=[lv["C_MM_M"] - lv["ci90_lo_M"], lv["ci90_hi_M"] - lv["C_MM_M"]], fmt="none", ecolor=INK, elinewidth=0.9, capsize=2.5, capthick=0.9)
    b.set_xticks(xs); b.set_xticklabels([f"{r['return_period_years']:g} y\n{m2(r['C_MM_M'])}" for r in lv.iter_rows(named=True)], color=INK)
    b.tick_params(axis="x", length=0)
    b.set_xlabel("Exceeded once in (whiskers: 90% interval)")
    panel(b, "With the hourly moves of xyz's history")
    for ax in (a, b):
        ax.axhline(vault, color=VAULT, lw=1.3, ls=(0, (5, 2)), zorder=3)
    a.text(-0.4, vault + 0.25, f"Vault on {calendar.month_abbr[vday.month]} {vday.day}:\n\\${vault:.2f}M", color=VAULT, fontsize=7.5, fontweight="bold", va="bottom", linespacing=1.15)
    save(fig, "capital")


# ---------------------------------------------------------------------------------------------------------------------
def eligibility():
    """The isolated-only markets against the bar set by the weakest of the markets the vault already serves: six clear it.
    The count of markets served is read from data/xyzmeta.json (not delisted, no marginMode restriction), as sim/study/cross_eligibility.py does.
    Reads data/scen/cross_eligibility.csv (coin, vol_day_M, max_move_pct, oi_M, eligible, oracle_ok, liq_ok, move_ok;
    sim/study/cross_eligibility.py), and for the two thresholds data/candles/xyz_1h.parquet (coin, t, o, h, l, c, v) over the
    markets served. Circle area = open interest."""
    e = need(f"{SC}/cross_eligibility.csv", ("coin", "vol_day_M", "max_move_pct", "oi_M", "eligible", "oracle_ok", "liq_ok", "move_ok"))
    # the two thresholds, computed as sim/study/cross_eligibility.py does: over the markets the vault already serves, the largest
    # daily move and the smallest median daily volume, from the hourly candles; checked against the csv's own flags
    pc, pm = f"{ROOT}/data/candles/xyz_1h.parquet", f"{ROOT}/data/xyzmeta.json"
    for f in (pc, pm):
        if not os.path.exists(f):
            raise SystemExit(f"figs: missing file {f}")
    cross = [u["name"] for u in json.load(open(pm))[0]["universe"] if not u.get("isDelisted") and not u.get("marginMode")]   # markets with cross margin on
    served = len(cross)
    cd = (pl.read_parquet(pc).filter(pl.col("coin").is_in(cross)).with_columns(d=pl.col("t") // 86_400_000, ntl=pl.col("v") * pl.col("c")).sort("coin", "t")
          .group_by("coin", "d").agg(o=pl.col("o").first(), h=pl.col("h").max(), l=pl.col("l").min(), ntl=pl.col("ntl").sum())
          .with_columns(mv=pl.max_horizontal(pl.col("h") / pl.col("o") - 1, 1 - pl.col("l") / pl.col("o")))
          .group_by("coin").agg(max_move_pct=pl.col("mv").max() * 100, vol_day_M=pl.col("ntl").median() / 1e6))
    rv, rm = cd.sort("vol_day_M").row(0, named=True), cd.sort("max_move_pct").row(-1, named=True)
    bv, bm = rv["vol_day_M"], rm["max_move_pct"]
    if e.filter((pl.col("vol_day_M") >= round(bv, 2)) != pl.col("liq_ok")).height or e.filter((pl.col("max_move_pct") <= round(bm, 2)) != pl.col("move_ok")).height:
        raise SystemExit("figs: eligibility: the thresholds computed from the candles do not reproduce liq_ok / move_ok of cross_eligibility.csv")
    e = e.with_columns(pl.col("coin").str.replace("xyz:", ""), s=(pl.col("oi_M").clip(0.4) * 1.1))
    fig, ax = plt.subplots(figsize=(0.70 * W - 0.6, 1.85))   # drawn for 0.70 of the text width (the names right of the plot take the rest of it)
    ax.set_xscale("log")
    xmin, xmax = e["vol_day_M"].min() * 0.7, e["vol_day_M"].max() * 1.9
    ymax = e["max_move_pct"].max() * 1.08
    ax.fill_between([bv, xmax], 0, bm, color=LEAD, alpha=0.08, lw=0)
    ax.plot([bv, bv], [0, ymax], color=DARK, lw=0.9, ls=(0, (4, 2))); ax.plot([xmin, xmax], [bm, bm], color=DARK, lw=0.9, ls=(0, (4, 2)))
    rest, ok = e.filter(~pl.col("eligible")), e.filter(pl.col("eligible"))
    ax.scatter(rest["vol_day_M"], rest["max_move_pct"], s=rest["s"], color=GREY, alpha=0.75, lw=0.4, edgecolor="white", label=f"Do not clear the bar ({rest.height})")
    ax.scatter(ok["vol_day_M"], ok["max_move_pct"], s=ok["s"], color=LEAD, edgecolor="white", lw=0.5, zorder=3, label=f"Clear the bar ({ok.height})")
    ax.set_xlim(xmin, xmax); ax.set_ylim(0, ymax)   # before the names are placed: their collisions are tested in pixels
    # the eligible markets are named in a column right of the plot, in the order of their dots from top to bottom, each joined
    # to its dot by a thin line: at this size no name fits beside its dot without crossing a threshold line or another name
    srt = ok.sort("max_move_pct", descending=True)
    for k, r in enumerate(srt.iter_rows(named=True)):
        yt = 0.86 - 0.17 * k
        ax.annotate(name(r["coin"]).split(" (")[0], (r["vol_day_M"], r["max_move_pct"]), xytext=(1.07, yt), textcoords="axes fraction", ha="left", va="center",
                    fontsize=7, color=LEAD, fontweight="bold", annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=LEAD, lw=0.5, shrinkA=2, shrinkB=2, relpos=(0, 0.5)))   # each line ends at the left edge of its own name
    ax.text(bv * 0.94, ymax * 0.98, f"{name(rv['coin'][4:])}'s volume on xyz, \\${bv:.1f}M a day ", fontsize=7, color=MUTE, va="top", ha="right")
    ax.annotate(f"{name(rm['coin'][4:])}'s largest day, {bm:.0f}%", (xmin * 1.12, bm), xytext=(0, 3.5), textcoords="offset points", fontsize=7, color=MUTE, va="bottom")
    ax.set_xlabel("Median daily volume on xyz (\\$M, log scale)\nCircle area: open interest", fontsize=7, linespacing=1.3); ax.set_ylabel("Largest daily move (%)", fontsize=7); ax.tick_params(labelsize=7)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    top_legend(ax, y=1.0, fontsize=7)
    if os.environ.get("TITLES") != "0":   # from the figure's left edge: the plot itself is narrower than the title
        fig.suptitle(f"{ok.height} of the {e.height} isolated-only markets clear\nthe bar of the {served} markets the vault serves", x=0.0, y=1.05, ha="left", va="bottom", fontsize=9.5, fontweight="bold")
    save(fig, "eligibility")


# ---------------------------------------------------------------------------------------------------------------------
def six_markets():
    """An upper bound: ADL on the isolated-only markets if xyz's worst real moves hit today's positions at once (no time
    for anything to be liquidated in the order book first), today and with the vault allowed in six more markets.
    Reads data/scen/contagion_gap.csv (sim/study/contagion_gap.py): case (today, six_x), W (hours), when, noCross_ADL_M.
    The 1-hour and the 4-hour windows are two groups, set apart: several of them are windows of the same episode. The two
    values of each pair are written under it (today / with six more markets), rounded half up to one decimal."""
    c = need(f"{SC}/contagion_gap.csv", ("case", "W", "when", "noCross_ADL_M"))
    t = c.filter(pl.col("case") == "today").join(c.filter(pl.col("case") == "six_x"), on=["W", "when"], suffix="_six")
    if t.height == 0:
        raise SystemExit("figs: six_markets: no hour present in both cases")
    t = t.sort("W", "noCross_ADL_M", descending=[False, True])
    r1 = lambda v: str(decimal.Decimal(str(v)).quantize(decimal.Decimal("0.1"), rounding=decimal.ROUND_HALF_UP))
    Ws = t["W"].unique().sort().to_list()
    xs, x = [], 0.0
    for i, r in enumerate(t.iter_rows(named=True)):
        if i and r["W"] != t["W"][i - 1]: x += 0.7   # a gap between the two groups of windows
        xs.append(x); x += 1
    fig, ax = plt.subplots(figsize=(0.70 * W + 0.6, 1.15))   # drawn for 0.70 of the text width
    a, b = t["noCross_ADL_M"].to_list(), t["noCross_ADL_M_six"].to_list()
    ax.bar([v - 0.2 for v in xs], a, width=0.36, color=TODAY, label="Today")
    ax.bar([v + 0.2 for v in xs], b, width=0.36, color=VAULT, hatch="////", edgecolor="white", lw=0, label="Vault allowed in six more markets (change 4 alone)")   # green = the vault's coverage; blue is kept for the whole proposal
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{mdate(r['when'][:5].replace('-', ''), short=True)}\n{r['when'][6:]}" for r in t.iter_rows(named=True)], color=INK, linespacing=1.2, fontsize=7)
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(10))
    for v, u_, w_ in zip(xs, a, b):   # the two values under each pair, in the colors of the bars
        ax.annotate(r1(u_), (v, 0), xytext=(0, -23), textcoords="offset points", ha="center", va="top", fontsize=7, color=INK, annotation_clip=False)
        ax.annotate(r1(w_), (v, 0), xytext=(0, -32), textcoords="offset points", ha="center", va="top", fontsize=7, color=VAULT, fontweight="bold", annotation_clip=False)
    ax.tick_params(axis="x", length=0); ax.set_xlim(xs[0] - 0.6, xs[-1] + 0.6); ax.set_ylim(0, max(a) * 1.22)
    for w_ in Ws:
        g = [v for v, ww in zip(xs, t["W"]) if ww == w_]
        ax.text((g[0] + g[-1]) / 2, max(a) * 1.2, f"{w_}-hour windows", fontsize=7.5, fontweight="bold", color=INK, ha="center", va="top")
    ax.set_ylabel("ADL on isolated-only\nmarkets (\\$M)", fontsize=7.5); ax.tick_params(axis="y", labelsize=7)
    ax.annotate("Under each pair: start of the window (UTC), then the two values in \\$M.\nSeveral windows belong to the same episode.",
                (0.5, 0), xytext=(0, -44), xycoords="axes fraction", textcoords="offset points", fontsize=7, color=MUTE, ha="center", va="top", annotation_clip=False, linespacing=1.2)
    top_legend(ax, y=1.0, fontsize=7.5)
    title(ax, "Upper bound: ADL if xyz's worst moves\nhit today's positions at once", y=18)
    save(fig, "six_markets")


FIGS = dict(headline=headline, headline_crash=headline_crash, crash_mark=crash_mark, adl_timeline=adl_timeline, mark_changes=mark_changes, closed_attacks=closed_attacks,
            cutback=cutback, cutback_how=cutback_how, skhx_0727=skhx_0727, eligibility=eligibility, six_markets=six_markets, capital=capital, feed_age=feed_age, normal_days=normal_days,
            attacks=attacks)

if __name__ == "__main__":
    names = sys.argv[1:] or list(FIGS)
    for nm in names:
        if nm not in FIGS:
            raise SystemExit(f"figs: unknown figure '{nm}' (have: {', '.join(FIGS)})")
        FIGS[nm]()
