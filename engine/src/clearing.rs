//! Per-account state for one HIP-3 coin (port of archive/sim/clearinghouse.py), mark-driven liquidation triggers, and the
//! liquidation engine (market rounds + backstop takeover) for the integrated simulation.

use crate::book::{Book, Px};
use crate::io::*;
use crate::replay::{median3, OrcRec};
use ahash::{AHashMap, AHashSet};
use arrow_array::types::*;
use arrow_array::{Array, StringViewArray};

#[derive(Clone, Copy, PartialEq)]
pub enum Reduce {
    Keep,
    PropBefore,
    PropAfter,
    /// HL (fitted): realized PnL goes to margin, then max(0, equity at the fill price) * reduced/position is released
    EqRelease,
}

#[derive(Clone, Copy)]
pub struct Rules {
    pub fee_iso: bool,
    pub reduce: Reduce,
    pub liq_reduce: Reduce,
    pub lev_adjust: bool,
    // liquidation engine
    pub mm_buffer: f64,     // MM rate = mm_buffer / maxlev (HL: 0.5)
    pub backstop_frac: f64, // takeover below backstop_frac * MM (HL: 2/3)
    pub partial_ntl: f64,   // positions above this get a partial first round (HL: 100k)
    pub partial_frac: f64,  // HL: 0.2
    pub cooldown_ms: i64,   // HL: 30s
    pub liq_limit: f64,     // liquidation order limit = mark * (1 -/+ liq_limit); <= 0: no limit
    pub liq_equity_stop: bool, // stop a liquidation order where equity would cross backstop_frac * MM
    pub iso_open_mark: bool, // isolated opening also moves the fill's loss at the reference price into margin (iso_open=mark|oracle)
    pub iso_open_oracle: bool, // ... the reference being the oracle, not the mark
    pub iso_mode: u8,
    /// isolated opening margin on the notional at the mark (iso_im=mark) instead of at the fill price (default)
    pub iso_im_mark: bool,
    /// iso_im=better: the mark only when the fill is better than it (buy below / sell above), else the fill price
    pub iso_im_better: bool,
    pub lot_round: bool, // liquidation sizes on the coin's size grid: partial 20% floored, equity stop floored (lot_round=0: µ-units) // 0 loss: the opened size's loss; 1 topup: the whole position to IM at the reference; 2 slack: the loss beyond the position's excess over IM
    /// HL margin table (deployer-controlled): up to 3 tiers (notional lower bound, max leverage), increasing bounds and
    /// decreasing leverage (`tiers=0:20,1000000:10,5000000:5`; default one tier at the coin's max leverage). Per tier the
    /// MM rate is mm_buffer / maxLev and the IM rate 1 / maxLev; MM = notional * rate - deduction, continuous in size.
    pub tiers: [(f64, f64); 3],
    pub ntiers: usize,
    /// tier_topup=1: margined accounts post the extra initial margin the tiers require over the single base tier,
    /// at each opening fill and at the start (bound "traders top up"; default none: positions kept as they were)
    pub tier_topup: bool,
    /// oi_tiers=live|lock|daily: the tiers' lower bounds are shares of open interest (`tiers=0:20,0.05:10,0.15:5`: 10x
    /// above 5% of OI), not notionals. The OI reference: live = OI now (an account's tier moves when others trade);
    /// lock = a 24 h average of OI (seeded with the start-of-day OI), fixed per account at each increase of its position
    /// and kept on reductions; daily = the start-of-day OI for every account, fixed for the day.
    pub oi_tiers: bool,
    pub oi_mode: u8,
    /// tier_reduce=1 (the other response bound): margined accounts post no extra margin and hold only the size their
    /// margin carries under the tiers: the largest position whose tiered IM equals the base IM (notional / coin max
    /// leverage) of the position they really built. The excess is never opened (start positions: shed at the first
    /// update, margin kept); its fills stay on the tape (someone else holds that size, book flow unchanged).
    pub tier_reduce: bool,
    /// cluster=k (> 0): the tiers price the liquidation cluster, not the account. At each increase of its position an
    /// account locks the size of its cluster: same-side margined positions (itself included) whose liquidation price
    /// (at the base MM rate) is within k of its own. Its MM (and IM) is its notional times the cluster's average tiered
    /// rate, mm(cluster) / cluster: splitting a position into accounts with the same liquidation price changes nothing.
    pub cluster_k: f64,
    /// lev_cut=L with cut_win=a:b (ms): every tier's max leverage is capped at L during [a, b) (a scheduled-event
    /// leverage cut, deployer-controlled). With tier_topup=1 margined accounts post the extra IM at the window start.
    pub lev_cut: f64,
    pub cut_a: i64,
    pub cut_b: i64,
    /// mm_dyn=hi (mm_dyn_s=window s, default 150): the MM buffer rises from mm_buffer toward hi as the external price's
    /// move over the window approaches the base MM zone (mm_buffer / maxLev); it falls back as the move fades
    pub mm_dyn: f64,
    pub mm_dyn_ms: i64,
    pub mm_base: f64,
    /// keep_bs=1: the backstop threshold stays at backstop_frac x the base MM when the buffer is raised (only the book
    /// liquidation zone widens)
    pub keep_bs: bool,
    pub bs_base: f64,
    /// liq_restore=k (> 0): a liquidation round sells only the excess, the size that brings the account back to k x MM
    /// at the mark (k=1: back to the MM line; k=2: back to IM), at least one lot, every mark update, no cooldown and no
    /// size threshold: the position is deleveraged continuously as the price keeps moving (HL change: liquidation engine)
    pub liq_restore: f64,
    /// restore_big=1: the restore rule only for positions above partial_ntl (smaller ones still close in full)
    pub restore_big: bool,
    /// backstop=adl: isolated-only (noCross) market. The vault cannot hold the position, so a backstop liquidation is
    /// auto-deleveraging against profitable opposite positions (tape: all 23 backstop events on noCross markets were ADL,
    /// all 84 on cross-enabled markets went to the vault). It triggers when the position's equity at the mark is negative,
    /// not at 2/3 MM, and prints at the previous update's mark (see liquidate()). The events are still recorded in
    /// sim_takeovers (= ADL notional); the replay keeps them out of the vault.
    pub adl_backstop: bool,
    /// backstop=adl_mm: the rule used before 2026-11-10, kept for comparison: ADL at 2/3 MM, at the bankruptcy price
    pub adl_at_mm: bool,
    /// iso_only=1 (implied by backstop=adl): the market is isolated-only (HIP-3 noCross / strictIsolated). Every position
    /// on it is isolated, whatever the account's other collateral: accounts that open after the snapshot post isolated
    /// margin, and the cross-collateral reconstruction (acc_x) is not used. The fills' `direction` never says
    /// "Isolated" for ordinary trades, so without this such accounts were margined as cross (xyz:NOW 2026-10-28: a 10x
    /// long opened after the snapshot was liquidated on the book 5.6% lower; margined on the account's $11k it lived on).
    pub iso_only: bool,
    /// adl_book=1 (default): on an isolated-only market, book liquidation orders keep going below backstop_frac * MM,
    /// limited to the position's bankruptcy price; 0: no order below that line. See liquidate().
    pub adl_book: bool,
}

impl Rules {
    pub fn from_args(a: &[String], maxlev: f64) -> Self {
        let mut r = Rules {
            fee_iso: true, reduce: Reduce::EqRelease, liq_reduce: Reduce::EqRelease, lev_adjust: false,
            mm_buffer: 0.5, backstop_frac: 2.0 / 3.0, partial_ntl: 100_000.0, partial_frac: 0.2, cooldown_ms: 30_000,
            liq_limit: 0.0, liq_equity_stop: true, iso_open_mark: true, iso_open_oracle: false, iso_mode: 0, iso_im_mark: false, iso_im_better: false, lot_round: true,
            tiers: [(0.0, maxlev), (f64::INFINITY, maxlev), (f64::INFINITY, maxlev)], ntiers: 1, tier_topup: false, oi_tiers: false, oi_mode: 0, tier_reduce: false, cluster_k: 0.0, lev_cut: 0.0, cut_a: 0, cut_b: 0, mm_dyn: 0.0, mm_dyn_ms: 150_000, mm_base: 0.5, keep_bs: false, bs_base: 2.0 / 3.0, liq_restore: 0.0, restore_big: false, adl_backstop: false, adl_at_mm: false, iso_only: false, adl_book: true,
        };
        let red = |v: &str| match v { "prop_after" => Reduce::PropAfter, "prop_before" => Reduce::PropBefore, "eq_release" => Reduce::EqRelease, _ => Reduce::Keep };
        for kv in a {
            if let Some((k, v)) = kv.split_once('=') {
                match k {
                    "fee_iso" => r.fee_iso = v == "1",
                    "reduce" => r.reduce = red(v),
                    "liq_reduce" => r.liq_reduce = red(v),
                    "lev_change" => r.lev_adjust = v == "adjust",
                    "mm_buffer" => r.mm_buffer = v.parse().unwrap(),
                    "backstop_frac" => r.backstop_frac = v.parse().unwrap(),
                    "partial_ntl" => r.partial_ntl = v.parse().unwrap(),
                    "partial_frac" => r.partial_frac = v.parse().unwrap(),
                    "cooldown_ms" => r.cooldown_ms = v.parse().unwrap(),
                    "liq_limit" => r.liq_limit = v.parse().unwrap(),
                    "liq_equity_stop" => r.liq_equity_stop = v == "1",
                    // iso_open=off: notional / leverage only
                    "iso_open" => { r.iso_open_mark = v == "mark" || v == "oracle"; r.iso_open_oracle = v == "oracle"; }
                    "lot_round" => r.lot_round = v != "0",
                    "iso_mode" => r.iso_mode = match v { "topup" => 1, "slack" => 2, _ => 0 },
                    "iso_im" => { r.iso_im_mark = v == "mark"; r.iso_im_better = v == "better"; }
                    "tiers" => {
                        let t: Vec<(f64, f64)> = v.split(',').map(|x| { let (a, b) = x.split_once(':').unwrap(); (a.parse().unwrap(), b.parse().unwrap()) }).collect();
                        assert!(!t.is_empty() && t.len() <= 3 && t[0].0 == 0.0, "tiers: 1-3 tiers, the first from 0");
                        for k in 0..t.len() { r.tiers[k] = t[k]; }
                        r.ntiers = t.len();
                    }
                    "tier_topup" => r.tier_topup = v == "1",
                    "tier_reduce" => r.tier_reduce = v == "1",
                    "cluster" => r.cluster_k = v.parse().unwrap(),
                    "lev_cut" => r.lev_cut = v.parse().unwrap(),
                    "cut_win" => { let x: Vec<i64> = v.split(':').map(|a| a.parse().unwrap()).collect(); r.cut_a = x[0]; r.cut_b = x[1]; }
                    "keep_bs" => r.keep_bs = v == "1",
                    "liq_restore" => r.liq_restore = v.parse().unwrap(),
                    "restore_big" => r.restore_big = v == "1",
                    "backstop" => { r.adl_backstop = v == "adl" || v == "adl_mm"; r.adl_at_mm = v == "adl_mm"; if r.adl_backstop { r.iso_only = true; } }
                    "iso_only" => r.iso_only = v == "1",
                    "adl_book" => r.adl_book = v == "1",
                    "mm_dyn" => r.mm_dyn = v.parse().unwrap(),
                    "mm_dyn_s" => r.mm_dyn_ms = (v.parse::<f64>().unwrap() * 1000.0) as i64,
                    "oi_tiers" => { r.oi_tiers = true; r.oi_mode = match v { "live" => 0, "lock" => 1, "daily" => 2, _ => panic!("oi_tiers: live|lock|daily") }; }
                    _ => panic!("unknown rule {k}={v}: check the runner that set it"),
                }
            }
        }
        r.bs_base = r.backstop_frac;
        r.mm_base = if r.keep_bs { 0.5 } else { r.mm_buffer };
        if r.keep_bs { r.backstop_frac = r.bs_base * r.mm_base / r.mm_buffer; }
        r
    }

    /// Rate and deduction of the tier holding `ntl`, for a per-tier rate `rate_of(maxLev)` (HL margin tiers). The lower
    /// bounds are scaled by `s` (1 for notional tiers; OI reference * price for OI tiers, Acc::tscale).
    fn tier(&self, ntl: f64, s: f64, rate_of: impl Fn(f64) -> f64) -> (f64, f64) {
        let (mut rate, mut ded) = (rate_of(self.tiers[0].1), 0.0);
        for k in 1..self.ntiers {
            let (lb, ml) = self.tiers[k];
            let lb = lb * s;
            if ntl <= lb { break; }
            let r2 = rate_of(ml);
            ded += lb * (r2 - rate);
            rate = r2;
        }
        (rate, ded)
    }
    /// Maintenance margin of a position of notional `ntl` (with one tier: mm_buffer / maxLev * ntl).
    pub fn mm(&self, ntl: f64, s: f64) -> f64 { let (r, d) = self.mm_tier(ntl, s); ntl * r - d }
    pub fn mm_tier(&self, ntl: f64, s: f64) -> (f64, f64) { self.tier(ntl, s, |ml| self.mm_buffer / ml) }
    /// Initial margin at max leverage of a position of notional `ntl`.
    pub fn im(&self, ntl: f64, s: f64) -> f64 { let (r, d) = self.tier(ntl, s, |ml| 1.0 / ml); ntl * r - d }
    /// Largest notional whose tiered IM is `im` (inverse of im(); IM is continuous and increasing in notional).
    pub fn im_inv(&self, im: f64, s: f64) -> f64 {
        let (mut rate, mut ded) = (1.0 / self.tiers[0].1, 0.0);
        for k in 1..self.ntiers {
            let (lb, ml) = self.tiers[k];
            let lb = lb * s;
            if (im + ded) / rate <= lb { break; }
            let r2 = 1.0 / ml;
            ded += lb * (r2 - rate);
            rate = r2;
        }
        (im + ded) / rate
    }
}

#[derive(Clone, Copy, Default)]
pub struct Acc {
    pub q: f64,
    pub e: f64,
    pub m: Option<f64>,
    pub iso: Option<bool>,
    pub lev: f64,
    pub known: bool,
    /// Cross account margined like an isolated one: it holds at most this one position on the dex, so its account value
    /// is m + (mark - e) * q, with m its collateral (cross semantics in fill(): opening adds no margin, realized PnL stays,
    /// nothing is released, going flat keeps the collateral).
    pub cross_m: bool,
    /// Maintenance margin of the account's other cross positions sharing the collateral (crossacc.py).
    pub mmo: f64,
    /// Requirement R = pmf * (MM(this coin) + mmo) + pmc: 1 / 0 normally; portfolio margin (liquidatable when
    /// PMR = (20 + MM) / LV > 0.95): 1/0.95 and 20/0.95.
    pub pmf: f64,
    pub pmc: f64,
    /// oi_tiers: the open interest (shares) the account's tier bounds are measured against
    pub oi_ref: f64,
    /// cluster rule: size (shares) of the account's liquidation cluster, locked at its last increase (0: not set)
    pub cl_q: f64,
}

impl Acc {
    /// Maintenance requirement at `mark`: this coin's MM (margin tiers) plus the other positions' MM.
    /// other cross positions' MM (never negative)
    pub fn mmo_pos(&self) -> f64 { self.mmo.max(0.0) }
    pub fn req(&self, rules: &Rules, mark: f64) -> f64 {
        let (r, d) = self.mm_lin(rules, mark);
        self.pmf * (self.q.abs() * mark * r - d + self.mmo_pos()) + self.pmc
    }
    /// MM of this coin's position as rate and deduction at `mark` (margin tiers; cluster rule: the cluster's average rate).
    pub fn mm_lin(&self, rules: &Rules, mark: f64) -> (f64, f64) {
        let s = self.tscale(rules, mark);
        if rules.cluster_k > 0.0 && self.cl_q > 0.0 {
            let cn = self.cl_q.max(self.q.abs()) * mark;
            (rules.mm(cn, s) / cn, 0.0)
        } else { rules.mm_tier(self.q.abs() * mark, s) }
    }
    /// Initial margin at max leverage of the position at `px` (tiers / cluster rule as mm_lin).
    pub fn im_at(&self, rules: &Rules, px: f64) -> f64 {
        let (n, s) = (self.q.abs() * px, self.tscale(rules, px));
        if rules.cluster_k > 0.0 && self.cl_q > 0.0 {
            let cn = self.cl_q.max(self.q.abs()) * px;
            n * rules.im(cn, s) / cn
        } else { rules.im(n, s) }
    }
    /// Liquidation price at the base MM rate `r` (margined accounts): equity m + (p - e) q = r |q| p.
    pub fn liq_px(&self, r: f64) -> Option<f64> {
        let m = self.m?;
        if self.q == 0.0 { return None; }
        let p = (self.e * self.q - m) / (self.q * (1.0 - r * self.q.signum()));
        if p.is_finite() && p > 0.0 { Some(p) } else { None }
    }
    /// Scale of the tier bounds at price `px`: 1 for notional tiers, OI reference * px for OI tiers.
    pub fn tscale(&self, rules: &Rules, px: f64) -> f64 { if rules.oi_tiers { self.oi_ref * px } else { 1.0 } }
    /// Margin known and simulated: isolated with known margin, or a single-position cross account.
    pub fn margined(&self) -> bool {
        (self.iso == Some(true) || self.cross_m) && self.m.is_some()
    }
}

struct Rows {
    h: Vec<i64>, u: Vec<u32>, k: Vec<u8>, phase: Vec<u8>, cross: Vec<bool>, lev: Vec<f64>, amt: Vec<f64>,
    fee: Vec<f64>, bstop: Vec<bool>, dir_iso: Vec<bool>, dir_liq: Vec<bool>, lmark: Vec<f64>,
    /// liquidation fill on the liquidated account's side (fills' is_liquidation; prep / liqside.py). Older preps: every
    /// liquidation row counts as the liquidated side (the old behaviour).
    liq_side: Vec<bool>,
}

#[derive(Clone, Copy, Debug)]
pub struct Takeover { pub h: i64, pub u: u32, pub q: f64, pub px: f64, pub mark: f64, pub eq: f64 }
#[derive(Clone, Copy, Debug)]
pub struct Round { pub h: i64, pub u: u32, pub req: f64, pub filled: f64, pub mark: f64, pub eq_before: f64 }

pub struct Clearing {
    pub acc: AHashMap<u32, Acc>,
    pub book_fills: Vec<(u32, u32, bool, i64)>, // (taker, maker, taker buys, size) of fills made inside liquidate()
    /// (px, size) of the liquidation fills made inside liquidate() (trade prints for MARK=own_*; drained by the replay)
    pub prints: Vec<(f64, f64)>,
    /// Cross collateral outside this coin (crossacc.py): per block, changes dx of X for cross-margined accounts.
    /// (h, u, dx, dmm, pre): pre = another coin's liquidation fills that HL applies before this coin's stop
    xev: Vec<(i64, u32, f64, f64, bool)>,
    /// Simulated fill volume per user (endogenous mode): (as taker, as maker), signed (buys positive).
    pub vol: AHashMap<u32, (f64, f64)>,
    xcur: usize,
    maxlev: f64,
    pub rules: Rules,
    rows: Rows,
    cur: usize,
    ledger: AHashMap<(i64, u32), (f64, f64, bool)>,
    pub integrated: bool,
    pub vault_uid: u32,
    pub liq_fee_rate: f64,
    pub takeover_check: Vec<(u32, f64, f64, f64, f64, f64, bool)>, // user, simQ, ledQ, simEq, ledEq, ntl, known
    pub real_first: AHashMap<u32, (i64, bool)>,
    pub real_rounds: Vec<(i64, u32, f64)>,         // h, user, filled size (liquidated user's market liquidation fills)
    pub real_takeovers: Vec<(i64, u32, f64, f64)>, // h, user, size, px
    pub sim_rounds: Vec<Round>,
    pub sim_takeovers: Vec<Takeover>,
    /// real takeovers of accounts the engine does not simulate (inherited by the vault as they happened)
    pub ext_takeovers: Vec<Takeover>,
    cooldown: AHashMap<u32, i64>,
    /// endogenous: account fills come from the simulator's fill bus (both counterparties), not from the tape
    pub endogenous: bool,
    fee_taker: AHashMap<u32, f64>,
    fee_maker: AHashMap<u32, f64>,
    /// per-user liquidation fee rate (fees.arrow `liq`, sim/prep/fees_liq.py): the account's own base taker rate
    fee_liq: AHashMap<u32, f64>,
    pub bus_fills: u64,
    pub engine_counterparties: AHashSet<u32>,
    /// mark and oracle of the last relayer update (NaN before the first)
    pub mark: f64,
    pub oracle: f64,
    /// external price at the current relayer update (set by the replay before liquidate) and its history for mm_dyn
    pub ext: f64,
    ext_hist: std::collections::VecDeque<(i64, f64)>,
    pub mm_dyn_peak: f64,
    pub mm_dyn_ms_on: i64,
    mm_dyn_last: i64,
    /// DEBUG_U: log every bus fill of this user
    debug_u: Option<u32>,
    /// position at the start of the block of its latest change (block, q): triggers fire at the relayer update, after
    /// the block's tape fills are applied, and must not see their own real fill
    qstart: AHashMap<u32, (i64, f64)>,
    /// tier_topup: extra initial margin each account has posted for the margin tiers, and the total (traders' cost)
    topped: AHashMap<u32, f64>,
    pub topup_total: f64,
    /// accounts that market liquidation closes below their bankruptcy price: the negative balance left (HL: ADL against
    /// the opposite side's winners; the engine's account zeroes it when it goes flat, so it is in nobody's PnL here)
    pub liq_bad_debt: f64,
    topup_t0_done: bool,
    /// lev_cut: the window is active, and the tiers outside it
    pub cut_on: bool,
    pub cut_withdrawn: f64,
    base_tiers: [(f64, f64); 3],
    /// size grid step in µ-units (10^(6 - szDecimals)); 1 when lot_round is off
    pub lot: i64,
    /// oi_tiers: open interest at the start, now, its 24 h average (integral of OI - oi0 over ms), the vault's position
    /// (set by the replay: OI = (sum of |q| + |vault q|) / 2)
    pub oi0: f64,
    pub oi_now: f64,
    oi_int: f64,
    oi_ms: i64,
    pub vault_q: f64,
    /// tier_reduce: size each account really holds beyond its simulated position (signed), and the peak total notional
    /// shed across accounts (the traders' cost under this response)
    xs: AHashMap<u32, f64>,
    pub shed_peak: f64,
    cl_t0_done: bool,
    /// CROSS_SHOCK="ms;frac": at ms, every cross account with positions on other xyz coins loses frac of their notional
    /// (estimated as 40 x their MM, i.e. 20x coins) from its collateral: another coin's mark crashed by frac
    cross_shock: Option<(i64, f64)>,
    /// ACC_DUMP="ms;path": write every account with a position (u, q, e, m, lev, iso, cross_m, mmo, mark) at the first update >= ms
    acc_dump: Option<(i64, String)>,
    /// STOP_DUMP: every liquidation fill with the state before it (over-fill study)
    stop_dump: Option<std::io::BufWriter<std::fs::File>>,
    /// LIQ_ROUNDS_OUT: one row per market-liquidation round (size, fills, the hit side of the book before and after)
    liq_rounds: Option<std::io::BufWriter<std::fs::File>>,
    pub cross_shock_usd: f64,
}

/// One fill produced by the simulator (book matching, liquidations, vault, injected engine takers).
#[derive(Clone, Copy, Debug)]
pub struct Fill {
    pub taker: u32,
    pub maker: u32,
    pub taker_buy: bool,
    pub px: f64,
    pub sz: f64,
    pub taker_fee_rate: Option<f64>, // None: the taker's own rate
}

fn rows(dir: &str) -> Rows {
    let f = format!("{dir}/acc_events.arrow");
    let k = load::<UInt8Type>(&f, "k");
    let phase = k.iter().map(|x| match x { 1 | 2 => 0, 3 => 1, 4 => 2, _ => 3 }).collect();
    Rows {
        h: load::<Int64Type>(&f, "h"), u: load::<UInt32Type>(&f, "u"), k, phase, cross: load_bool(&f, "cross"),
        lev: load::<Float64Type>(&f, "lev"), amt: load::<Float64Type>(&f, "amt"), fee: load::<Float64Type>(&f, "fee"),
        bstop: load_bool(&f, "bstop"), dir_iso: load_bool(&f, "dir_iso"), dir_liq: load_bool(&f, "dir_liq"), lmark: load::<Float64Type>(&f, "lmark"),
        liq_side: if reader(&f).schema().column_with_name("liq_side").is_some() { load_bool(&f, "liq_side") } else { vec![true; load::<Int64Type>(&f, "h").len()] },
    }
}

impl Clearing {
    pub fn new(dir: &str, maxlev: f64, rules: Rules) -> Self {
        // ACC_INIT: another initial account table (sim/prep/lev_fit.py tries leverages without copying the prep)
        let f = std::env::var("ACC_INIT").unwrap_or_else(|_| format!("{dir}/acc_init.arrow"));
        let mmr0 = 0.5 / maxlev; // the snapshot's liquidation prices were computed under HL's MM
        let (u, q, e, lp, lev) = (load::<UInt32Type>(&f, "u"), load::<Float64Type>(&f, "q"), load::<Float64Type>(&f, "e"), load::<Float64Type>(&f, "lp"), load::<Float64Type>(&f, "lev"));
        let iso = load_bool(&f, "iso");
        // cross collateral (prep: single-position cross accounts), absent in older preps
        let cm: Vec<f64> = if reader(&f).schema().column_with_name("cm").is_some() { load::<Float64Type>(&f, "cm") } else { vec![f64::NAN; u.len()] };
        let cross_on = std::env::var("CROSS").map_or(true, |v| v != "0");
        let mut acc = AHashMap::new();
        for k in 0..u.len() {
            let mut m = None;
            if iso[k] && !lp[k].is_nan() && q[k] != 0.0 {
                let sd = if q[k] > 0.0 { 1.0 } else { -1.0 };
                m = Some(q[k].abs() * (mmr0 * lp[k] - sd * (lp[k] - e[k])));
            }
            let cross_m = cross_on && !rules.iso_only && !iso[k] && !cm[k].is_nan();
            if cross_m { m = Some(cm[k]); }
            // a flat isolated account (sim/prep/acc_lev.py: its leverage and mode come from the next snapshot; or any flat
            // account of an isolated-only market) holds no margin here and posts it when it opens
            let iso_k = iso[k] || rules.iso_only;
            if iso_k && q[k] == 0.0 { m = Some(0.0); }
            acc.insert(u[k], Acc { q: q[k], e: e[k], m, iso: Some(iso_k), lev: lev[k], known: true, cross_m, mmo: 0.0, pmf: 1.0, pmc: 0.0, oi_ref: 0.0, cl_q: 0.0 });
        }
        let oi0 = acc.values().map(|d: &Acc| d.q.abs()).sum::<f64>() / 2.0;
        for d in acc.values_mut() { d.oi_ref = oi0; }
        let lf = format!("{dir}/ledger.arrow");
        let (lh, lu, lav, lsz) = (load::<Int64Type>(&lf, "h"), load::<UInt32Type>(&lf, "u"), load::<Float64Type>(&lf, "account_value"), load::<Float64Type>(&lf, "szi"));
        let liso = load_bool(&lf, "iso");
        let mut ledger = AHashMap::new();
        for k in 0..lh.len() {
            ledger.insert((lh[k], lu[k]), (lav[k], lsz[k], liso[k]));
        }
        let meta: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(format!("{dir}/meta.json")).unwrap()).unwrap();
        let (mut fee_taker, mut fee_maker, mut fee_liq) = (AHashMap::new(), AHashMap::new(), AHashMap::new());
        let ff = format!("{dir}/fees.arrow");
        if std::path::Path::new(&ff).exists() {
            let (fu, ft, fm) = (load::<UInt32Type>(&ff, "u"), load::<Float64Type>(&ff, "taker"), load::<Float64Type>(&ff, "maker"));
            for k in 0..fu.len() { fee_taker.insert(fu[k], ft[k]); fee_maker.insert(fu[k], fm[k]); }
            if reader(&ff).schema().column_with_name("liq").is_some() && std::env::var("LIQ_FEE_COIN").is_err() {
                let fl = load::<Float64Type>(&ff, "liq");
                for k in 0..fu.len() { fee_liq.insert(fu[k], fl[k]); }
            }
        }
        // multi-dex cross / unified collateral (crossacc.py): m = x0 + e0 * q0, then the X deltas by block
        let mut xev: Vec<(i64, u32, f64, f64, bool)> = Vec::new();
        let fx = format!("{dir}/acc_x.arrow");
        if cross_on && !rules.iso_only && std::path::Path::new(&fx).exists() {
            let (xu, x0) = (load::<UInt32Type>(&fx, "u"), load::<Float64Type>(&fx, "x0"));
            let has = |c: &str| reader(&fx).schema().column_with_name(c).is_some();
            let mmo0 = if has("mmo0") { load::<Float64Type>(&fx, "mmo0") } else { vec![0.0; xu.len()] };
            let pmv = if has("pm") { load_bool(&fx, "pm") } else { vec![false; xu.len()] };
            // only accounts whose reconstruction matches the next snapshot (crossacc.py validation)
            let ok = if reader(&fx).schema().column_with_name("ok").is_some() { load_bool(&fx, "ok") } else { vec![true; xu.len()] };
            // accounts the reconstruction rejected are replayed (no fallback to the single-position collateral)
            for k in 0..xu.len() {
                if !ok[k] { if let Some(d) = acc.get_mut(&xu[k]) { if d.cross_m { d.cross_m = false; d.m = None; } } }
            }
            let sel: Vec<usize> = (0..xu.len()).filter(|&k| ok[k]).collect();
            let (mmo0, pmv): (Vec<f64>, Vec<bool>) = (sel.iter().map(|&k| mmo0[k]).collect(), sel.iter().map(|&k| pmv[k]).collect());
            let xu: Vec<u32> = sel.iter().map(|&k| xu[k]).collect();
            let x0: Vec<f64> = sel.iter().map(|&k| x0[k]).collect();
            for k in 0..xu.len() {
                let d = acc.entry(xu[k]).or_insert(Acc { q: 0.0, e: 0.0, m: None, iso: Some(false), lev: maxlev, known: false, cross_m: false, mmo: 0.0, pmf: 1.0, pmc: 0.0, oi_ref: 0.0, cl_q: 0.0 });
                if d.iso == Some(true) { continue; }
                d.iso = Some(false);
                d.cross_m = true;
                d.m = Some(x0[k] + d.e * d.q);
                d.mmo = mmo0[k];
                if pmv[k] { d.pmf = 1.0 / 0.95; d.pmc = 20.0 / 0.95; }
            }
            let fe = format!("{dir}/acc_xev.arrow");
            let (eh, eu, ed) = (load::<Int64Type>(&fe, "h"), load::<UInt32Type>(&fe, "u"), load::<Float64Type>(&fe, "dx"));
            let edm = if reader(&fe).schema().column_with_name("dmm").is_some() { load::<Float64Type>(&fe, "dmm") } else { vec![0.0; eh.len()] };
            let epre: Vec<bool> = if reader(&fe).schema().column_with_name("pre").is_some() && std::env::var("XPRE").as_deref() != Ok("0") {
                reader(&fe).flat_map(|b| { let b = b.unwrap(); (0..b.num_rows()).map(move |r| bcol(&b, "pre").value(r)).collect::<Vec<_>>() }).collect()
            } else { vec![false; eh.len()] };
            let keep: ahash::AHashSet<u32> = xu.iter().copied().collect();
            xev = (0..eh.len()).filter(|&k| keep.contains(&eu[k])).map(|k| (eh[k], eu[k], ed[k], edm[k], epre[k])).collect();
            eprintln!("cross collateral: {} accounts, {} X changes", xu.len(), xev.len());
        }
        Clearing {
            xev, xcur: 0, vol: AHashMap::new(),
            book_fills: vec![], prints: vec![],
            acc, maxlev, rules, rows: rows(dir), cur: 0, ledger, integrated: false,
            vault_uid: meta["vault_uid"].as_i64().unwrap_or(-1) as u32, liq_fee_rate: meta["liq_fee_rate"].as_f64().unwrap_or(0.0),
            takeover_check: vec![], real_first: AHashMap::new(), real_rounds: vec![], real_takeovers: vec![],
            sim_rounds: vec![], sim_takeovers: vec![], ext_takeovers: vec![], cooldown: AHashMap::new(),
            endogenous: false, fee_taker, fee_maker, fee_liq, bus_fills: 0, engine_counterparties: AHashSet::new(), mark: f64::NAN, oracle: f64::NAN, ext: 0.0, ext_hist: Default::default(), mm_dyn_peak: 0.0, mm_dyn_ms_on: 0, mm_dyn_last: 0, debug_u: std::env::var("DEBUG_U").ok().and_then(|s| s.parse().ok()), qstart: AHashMap::new(), topped: AHashMap::new(), topup_total: 0.0, liq_bad_debt: 0.0, topup_t0_done: false, cut_on: false, cut_withdrawn: 0.0, base_tiers: [(0.0, 0.0); 3],
            lot: if rules.lot_round { 10i64.pow((6 - meta["sz_decimals"].as_i64().unwrap_or(6)).max(0) as u32) } else { 1 },
            oi0, oi_now: oi0, oi_int: 0.0, oi_ms: -1, vault_q: 0.0, xs: AHashMap::new(), shed_peak: 0.0, cl_t0_done: false,
            cross_shock: std::env::var("CROSS_SHOCK").ok().map(|v| { let p: Vec<&str> = v.split(';').collect(); (p[0].parse().unwrap(), p[1].parse().unwrap()) }), cross_shock_usd: 0.0, liq_rounds: std::env::var("LIQ_ROUNDS_OUT").ok().map(|p| { use std::io::Write; let mut w = std::io::BufWriter::new(std::fs::File::create(p).unwrap()); writeln!(w, "h,ms,u,sell,q,ntl,req,filled,avg_px,mark,bid0,ask0,bid1,ask1,depth1pct,depth2pct,levels,full,eq").unwrap(); w }), stop_dump: std::env::var("STOP_DUMP").ok().map(|p| { use std::io::Write; let mut w = std::io::BufWriter::new(std::fs::File::create(p).unwrap()); writeln!(w, "h,u,px,f,q,e,m,allow,mark,c_thr,c_fix,fee,q0,e0,m0,mmo,pmf,pmc,bsf").unwrap(); w }),
            acc_dump: std::env::var("ACC_DUMP").ok().map(|v| { let p: Vec<&str> = v.splitn(2, ';').collect(); (p[0].parse().unwrap(), p[1].to_string()) }),
        }
    }

    pub fn max_lev(&self) -> f64 { self.maxlev }

    /// A synthetic attacker as an ordinary cross account at max leverage with collateral `capital` (ATTACK_PROP): margined,
    /// liquidated and taken over by the same rules as everyone else.
    pub fn add_attacker(&mut self, u: u32, capital: f64) {
        let maxlev = self.maxlev;
        self.acc.entry(u).or_insert(Acc { q: 0.0, e: 0.0, m: Some(capital), iso: Some(false), lev: maxlev, known: true, cross_m: true, mmo: 0.0, pmf: 1.0, pmc: 0.0, oi_ref: 0.0, cl_q: 0.0 });
    }
    /// A fill of a synthetic account made in the replay (its counterparty keeps its replayed fill); fee at `fee_rate`.
    pub fn ext_fill(&mut self, u: u32, buy: bool, px: f64, sz: f64, fee_rate: f64) {
        let (rules, mark) = (self.rules, self.mark);
        if let Some(a) = self.acc.get_mut(&u) { fill(a, buy, px, sz, px * sz * fee_rate, mark, rules, rules.reduce); }
    }
    /// Free margin of an account at the current mark: equity - initial margin of its position (notional / max leverage)
    pub fn free_margin(&self, u: u32) -> Option<f64> {
        let a = self.acc.get(&u)?;
        let mk = if self.mark.is_finite() { self.mark } else { return a.m };
        Some(a.m? + (mk - a.e) * a.q - a.q.abs() * mk / self.maxlev)
    }

    /// PRINT_U="u1,u2": margin top-ups (tier_topup) posted by these accounts and their final state
    pub fn print_users(&self) {
        if let Ok(v) = std::env::var("PRINT_U") {
            for u in v.split(',').filter_map(|x| x.parse::<u32>().ok()) {
                let d = self.acc.get(&u);
                println!("ACCOUNT {u}: topped ${:.0} final q {:?} m {:?}", self.topped.get(&u).copied().unwrap_or(0.0), d.map(|d| d.q), d.and_then(|d| d.m));
            }
        }
    }

    /// cluster rule: lock account u's cluster size (shares), itself included.
    fn lock_cluster(&mut self, u: u32) {
        let r0 = 0.5 / self.maxlev;
        let Some(d) = self.acc.get(&u) else { return };
        if !d.margined() { return; }
        let Some(p) = d.liq_px(r0) else { return };
        let (sg, k) = (d.q.signum(), self.rules.cluster_k);
        let c: f64 = self.acc.values()
            .filter(|o| o.margined() && o.q != 0.0 && o.q.signum() == sg)
            .filter_map(|o| o.liq_px(r0).filter(|&po| (po - p).abs() <= k * p).map(|_| o.q.abs()))
            .sum();
        self.acc.get_mut(&u).unwrap().cl_q = c;
    }

    /// tier_reduce: the position an account holds when it really holds `qr` at `px` (sign kept, size capped).
    fn reduce_target(&self, d: &Acc, qr: f64, px: f64) -> f64 {
        let n = qr.abs() * px;
        let cap = self.rules.im_inv(n / self.maxlev, d.tscale(&self.rules, px));
        if n <= cap { qr } else { qr.signum() * cap / px }
    }

    /// OI reference for a position increasing now (oi_tiers): live OI, its 24 h average, or the start-of-day OI.
    fn oi_ref_now(&self) -> f64 {
        match self.rules.oi_mode { 0 => self.oi_now, 1 => self.oi0 + self.oi_int / 86_400_000.0, _ => self.oi0 }
    }

    /// oi_tiers, at each relayer update: measure OI, advance its average; live and daily re-reference every account.
    fn update_oi(&mut self, ms: i64) {
        let oi = (self.acc.values().map(|d| d.q.abs()).sum::<f64>() + self.vault_q.abs()) / 2.0;
        if self.oi_ms >= 0 { self.oi_int += (self.oi_now - self.oi0) * (ms - self.oi_ms) as f64; }
        self.oi_ms = ms;
        self.oi_now = oi;
        if self.rules.oi_mode != 1 {
            let r = self.oi_ref_now();
            for d in self.acc.values_mut() { d.oi_ref = r; }
        }
    }

    /// Accounts the liquidation engine handles itself in the integrated run: isolated, margin known.
    pub fn engine_handles(&self, u: u32) -> bool {
        self.integrated && self.acc.get(&u).map_or(false, |d| d.margined())
    }

    /// Accounts the engine has already liquidated (rounds or takeover) keep being engine-handled.
    pub fn sim_handled(&self, u: u32) -> bool {
        self.integrated && (self.cooldown.contains_key(&u) || self.sim_takeovers.iter().any(|t| t.u == u))
    }

    /// Apply account events up to block h (rows of h only up to `phase_max`).
    pub fn advance(&mut self, h: i64, phase_max: u8) {
        while self.xcur < self.xev.len() && self.xev[self.xcur].0 <= h {
            let (_, u, dx, dmm, _) = self.xev[self.xcur];
            if let Some(d) = self.acc.get_mut(&u) {
                if d.cross_m {
                    if let Some(m) = d.m.as_mut() { *m += dx; }
                    // raw sum: events inside a block may come in any order (acc_xev ties), only the block's total is
                    // meaningful; uses clamp at 0 (mmo_pos)
                    d.mmo += dmm;
                }
            }
            self.xcur += 1;
        }
        while self.cur < self.rows.h.len() {
            let i = self.cur;
            let (rh, ph) = (self.rows.h[i], self.rows.phase[i]);
            if rh > h || (rh == h && ph > phase_max) {
                break;
            }
            self.apply(i);
            self.cur += 1;
        }
    }

    fn apply(&mut self, i: usize) {
        let (hh, uu, kk) = (self.rows.h[i], self.rows.u[i], self.rows.k[i]);
        let (bstop, dir_liq) = (self.rows.bstop[i], self.rows.dir_liq[i]);
        let liq_side = self.rows.liq_side[i];
        if kk == 4 && liq_side && (self.rows.dir_iso[i] || !bstop) {
            self.real_first.entry(uu).or_insert((hh, bstop));
        }
        if kk == 4 && liq_side && uu != self.vault_uid {
            if bstop && dir_liq {
                self.real_takeovers.push((hh, uu, self.rows.amt[i], self.rows.lev[i]));
            } else if !bstop {
                self.real_rounds.push((hh, uu, self.rows.amt[i]));
            }
        }
        if self.integrated && kk == 4 && bstop && dir_liq && uu != self.vault_uid && !(self.engine_handles(uu) || self.sim_handled(uu)) {
            let q = self.acc.get(&uu).map_or(0.0, |d| d.q);
            let sgn = if q != 0.0 { q.signum() } else if self.rows.cross[i] { -1.0 } else { 1.0 };
            self.ext_takeovers.push(Takeover { h: hh, u: uu, q: sgn * self.rows.amt[i], px: self.rows.lev[i], mark: self.rows.lmark[i], eq: f64::NAN });
        }
        if self.integrated && self.endogenous && uu != self.vault_uid && (kk == 3 || (kk == 4 && !(bstop && dir_liq))) {
            return; // book fills come from the simulator's fill bus
        }
        if self.integrated && (uu == self.vault_uid || (kk == 4 && liq_side && (self.engine_handles(uu) || self.sim_handled(uu)))) {
            return; // the vault is tracked from its own fills; engine-handled liquidations are simulated
        }
        // a counterparty of a real liquidation keeps its real fill (ENDO=0 replays the makers; GOOGL 0x4dbda869 lost 168
        // shares of liquidation buys that the simulated rounds gave to other makers, then sold a long it never had)
        let rules = self.rules;
        let maxlev = self.maxlev;
        let rp = self.ref_px();
        let oir = self.oi_ref_now();
        let d = self.acc.entry(uu).or_insert(Acc { q: 0.0, e: 0.0, m: None, iso: None, lev: maxlev, known: false, cross_m: false, mmo: 0.0, pmf: 1.0, pmc: 0.0, oi_ref: 0.0, cl_q: 0.0 });
        let (cross, lev, amt, fee) = (self.rows.cross[i], self.rows.lev[i], self.rows.amt[i], self.rows.fee[i]);
        match kk {
            1 => {
                let (newlev, iso_new) = (lev, !cross || rules.iso_only);
                if d.q != 0.0 && d.iso == Some(true) && iso_new && rules.lev_adjust {
                    if let Some(m) = d.m.as_mut() {
                        let n = d.q.abs() * d.e;
                        *m += n / newlev - n / d.lev;
                    }
                }
                if d.q == 0.0 {
                    if d.cross_m && !iso_new {
                        // stays cross: the collateral is kept
                    } else {
                        d.cross_m = false;
                        d.iso = Some(iso_new);
                        d.m = if iso_new { Some(0.0) } else { None };
                    }
                }
                d.lev = newlev;
            }
            2 => {
                if let Some(m) = d.m.as_mut() { *m += amt; }
            }
            5 => {
                if d.iso == Some(true) || d.cross_m {
                    if let Some(m) = d.m.as_mut() { *m += amt; }
                }
            }
            _ => {
                let (buy, px, sz) = (cross, lev, amt);
                if dir_liq && bstop {
                    if let (Some(m), Some(led)) = (d.m, self.ledger.get(&(hh, uu))) {
                        if led.2 || d.cross_m {
                            let mk = self.rows.lmark[i];
                            self.takeover_check.push((uu, d.q, led.1, m + (mk - d.e) * d.q, led.0, d.q.abs() * mk, d.known));
                        }
                    }
                    d.q = 0.0;
                    d.e = 0.0;
                    d.m = if d.iso == Some(true) || d.cross_m { Some(0.0) } else { None };
                    return;
                }
                if d.iso.is_none() {
                    let iso = self.rows.dir_iso[i] || rules.iso_only;
                    d.iso = Some(iso);
                    d.m = if iso { Some(0.0) } else { None };
                } else if d.cross_m && d.q == 0.0 && self.rows.dir_iso[i] {
                    // opens this coin isolated: not cross-margined here any more
                    d.cross_m = false;
                    d.iso = Some(true);
                    d.m = Some(0.0);
                }
                if kk == 3 && d.q != 0.0 && (d.q > 0.0) != buy && d.iso == Some(true) && d.m.is_some() {
                }
                let q_before = d.q;
                if rules.tier_reduce && rules.ntiers >= 2 && d.margined() && !(kk == 4 && liq_side) {
                    // trade toward the capped size of the real position; the trader posts the margin of the real opening
                    let x0 = *self.xs.get(&uu).unwrap_or(&0.0);
                    let (qr0, sg) = (q_before + x0, if buy { 1.0 } else { -1.0 });
                    let qr1 = qr0 + sg * sz;
                    let mut dd = *d;
                    if grew(qr0, qr1) { dd.oi_ref = oir; }
                    let tgt = if qr1.abs() < 1e-9 { 0.0 } else { self.reduce_target(&dd, qr1, px) };
                    let d = self.acc.get_mut(&uu).unwrap();
                    d.oi_ref = dd.oi_ref;
                    let delta = tgt - d.q;
                    if delta.abs() > 1e-9 {
                        fill(d, delta > 0.0, px, delta.abs(), fee * delta.abs() / sz, rp, rules, rules.reduce);
                    }
                    let open_real = if qr0 == 0.0 || (qr0 > 0.0) == (qr1 > 0.0) { (qr1.abs() - qr0.abs()).max(0.0) } else { (qr1.abs()).min(sz) };
                    let open_sim = if q_before == 0.0 || (q_before > 0.0) == (d.q > 0.0) { (d.q.abs() - q_before.abs()).max(0.0) } else { d.q.abs() };
                    if !d.cross_m && d.q != 0.0 { if let Some(m) = d.m.as_mut() { *m += (open_real - open_sim).max(0.0) * px / d.lev; } }
                    let x = qr1 - d.q;
                    if x.abs() > 1e-9 { self.xs.insert(uu, x); } else { self.xs.remove(&uu); }
                } else {
                fill(d, buy, px, sz, fee, rp, rules, if kk == 4 && liq_side { rules.liq_reduce } else { rules.reduce });
                let g = grew(q_before, d.q);
                if g { d.oi_ref = oir; }
                if g && rules.cluster_k > 0.0 { self.lock_cluster(uu); }
                }
                let e = self.qstart.entry(uu).or_insert((hh, q_before));
                if e.0 != hh { *e = (hh, q_before); }
                self.tier_topup(uu, px);
            }
        }
    }

    /// Apply one simulated fill to both counterparties (endogenous mode). The vault side is tracked by the replay.
    pub fn apply_fill(&mut self, f: &Fill) {
        self.bus_fills += 1;
        let rules = self.rules;
        let maxlev = self.maxlev;
        let rp = self.ref_px();
        let oir = self.oi_ref_now();
        for (u, buy, rate) in [(f.taker, f.taker_buy, f.taker_fee_rate.unwrap_or(*self.fee_taker.get(&f.taker).unwrap_or(&0.0))),
                               (f.maker, !f.taker_buy, *self.fee_maker.get(&f.maker).unwrap_or(&0.0))] {
            if u == self.vault_uid {
                continue;
            }
            let d = self.acc.entry(u).or_insert(Acc { q: 0.0, e: 0.0, m: None, iso: None, lev: maxlev, known: false, cross_m: false, mmo: 0.0, pmf: 1.0, pmc: 0.0, oi_ref: 0.0, cl_q: 0.0 });
            if d.iso.is_none() {
                if rules.iso_only { d.iso = Some(true); d.m = Some(0.0); }   // isolated-only market: it posts margin as it opens
                else { d.iso = Some(false); } // unknown accounts are cross (HL default), as in the tape-driven replay
            }
            let q0 = d.q;
            fill(d, buy, f.px, f.sz, f.px * f.sz * rate, rp, rules, rules.reduce);
            if grew(q0, d.q) { d.oi_ref = oir; }
            if self.debug_u == Some(u) {
                eprintln!("DEBUG_FILL u={u} taker={} maker={} buy={buy} px={} sz={} -> q={} m={:?} mark={}", f.taker, f.maker, f.px, f.sz, d.q, d.m, self.mark);
            }
            let v = self.vol.entry(u).or_default();
            let sg = if buy { f.sz } else { -f.sz };
            if u == f.taker { v.0 += sg } else { v.1 += sg }
        }
        for u in [f.taker, f.maker] { if u != self.vault_uid { self.tier_topup(u, f.px); } }
    }

    /// tier_topup: a margined account holds the extra initial margin its position needs under the margin tiers, over
    /// the coin's single base tier (posted when it opens size; never withdrawn).
    fn tier_topup(&mut self, u: u32, px: f64) {
        if !self.rules.tier_topup || (self.rules.ntiers < 2 && !self.cut_on) { return; }
        let Some(d) = self.acc.get_mut(&u) else { return };
        if !d.margined() || d.q == 0.0 { return; }
        let ntl = d.q.abs() * px;
        let need = (d.im_at(&self.rules, px) - ntl / self.maxlev).max(0.0);
        let t = self.topped.entry(u).or_insert(0.0);
        if need > *t {
            let add = need - *t;
            *t = need;
            if let Some(m) = d.m.as_mut() { *m += add; }
            self.topup_total += add;
        }
    }

    /// Phase-2a trigger scan: first block where an isolated account's equity < MM at the mark.
    pub fn scan_triggers(&self, h: i64, mark: f64, ft: &mut AHashMap<u32, (i64, f64, bool)>) {
        for (uu, d) in self.acc.iter() {
            if d.q != 0.0 && d.margined() && !ft.contains_key(uu) {
                let n = d.q.abs() * mark;
                let eq = d.m.unwrap() + (mark - d.e) * d.q;
                let r = d.req(&self.rules, mark);
                if eq < r {
                    ft.insert(*uu, (h, eq / n, eq < self.rules.backstop_frac * r));
                }
            }
        }
    }

    /// Position at the start of block h (before that block's tape fills); None if the account is not tracked.
    pub fn q_block_start(&self, u: u32, h: i64) -> Option<f64> {
        let q = self.acc.get(&u)?.q;
        Some(match self.qstart.get(&u) { Some(&(hb, q0)) if hb == h => q0, _ => q })
    }

    /// Free collateral for a new opening order of a cross account with modelled collateral (cross_m): equity minus the
    /// initial margin of its positions (this coin at its leverage, the others approximated as 2x their MM). Returns
    /// (free, position, leverage); None where the collateral is not modelled.
    pub fn free_collateral(&self, u: u32, mark: f64) -> Option<(f64, f64, f64)> {
        let d = self.acc.get(&u)?;
        if !d.cross_m { return None; }
        let m = d.m?;
        let eq = m + (mark - d.e) * d.q;
        Some((eq - d.q.abs() * mark / d.lev - 2.0 * d.mmo_pos() - d.pmc, d.q, d.lev))
    }

    /// reference price of the isolated opening rule
    fn ref_px(&self) -> f64 { if self.rules.iso_open_oracle { self.oracle } else { self.mark } }

    /// Liquidation engine at a mark update of block h: backstop takeover below backstop_frac*MM, else a market
    /// liquidation order (partial first round for big positions, full size during the cooldown) into the book.
    /// `others`: this block's real liquidation fills of accounts the engine does not handle, (liquidated user, maker oid,
    /// size), sorted by user; HL runs a block's liquidations in ascending address order, so they are interleaved.
    pub fn liquidate(&mut self, h: i64, ms: i64, mark: f64, book: &mut Book, last_px: &mut Option<Px>, others: &[(u32, i64, i64, i64, u32, bool)]) {
        let prev_mark = self.mark;   // the mark of the previous update (NaN at the first)
        self.mark = mark;
        if self.rules.mm_dyn > 0.0 && self.ext > 0.0 {
            self.ext_hist.push_back((ms, self.ext));
            while self.ext_hist.len() > 2 && self.ext_hist[1].0 <= ms - self.rules.mm_dyn_ms { self.ext_hist.pop_front(); }
            let e0 = self.ext_hist.front().unwrap().1;
            let mv = (self.ext / e0 - 1.0).abs();
            let z = self.rules.mm_base / self.maxlev;
            let b = self.rules.mm_base + (self.rules.mm_dyn - self.rules.mm_base) * (mv / z).min(1.0);
            if b >= 0.5 * (self.rules.mm_base + self.rules.mm_dyn) && self.mm_dyn_last > 0 { self.mm_dyn_ms_on += ms - self.mm_dyn_last; }
            self.mm_dyn_last = ms;
            self.rules.mm_buffer = b;
            if self.rules.keep_bs { self.rules.backstop_frac = self.rules.bs_base * self.rules.mm_base / b; }
            if b > self.mm_dyn_peak { self.mm_dyn_peak = b; }
        }
        if self.acc_dump.as_ref().map_or(false, |(t, _)| ms >= *t) {
            let (_, path) = self.acc_dump.take().unwrap();
            let mut w = String::from("u,q,e,m,lev,iso,cross_m,mmo,mark,ms\n");
            for (u, d) in self.acc.iter() { if d.q != 0.0 { w.push_str(&format!("{u},{},{},{},{},{},{},{},{mark},{ms}\n", d.q, d.e, d.m.map_or(f64::NAN, |x| x), d.lev, d.iso.map_or(-1, |x| x as i32), d.cross_m as i32, d.mmo)); } }
            std::fs::write(path, w).unwrap();
        }
        if let Some((t, f)) = self.cross_shock {
            if ms >= t {
                self.cross_shock = None;
                for d in self.acc.values_mut() {
                    let mo = d.mmo_pos(); if d.cross_m && mo > 0.0 { if let Some(m) = d.m.as_mut() { let x = f * mo * 40.0; *m -= x; self.cross_shock_usd += x; } }
                }
                println!("ATTACK: cross shock at {ms}: collateral removed ${:.0}", self.cross_shock_usd);
            }
        }
        if self.rules.oi_tiers { self.update_oi(ms); }
        if self.rules.lev_cut > 0.0 {
            let on = ms >= self.rules.cut_a && ms < self.rules.cut_b;
            if on != self.cut_on {
                if on {
                    self.base_tiers = self.rules.tiers;
                    for k in 0..3 { self.rules.tiers[k].1 = self.rules.tiers[k].1.min(self.rules.lev_cut); }
                } else {
                    self.rules.tiers = self.base_tiers;
                    // window over: accounts withdraw the cut's extra margin, down to what the base tiers need, as far as
                    // their equity stays above the base initial margin
                    if self.rules.tier_topup {
                        let rules = self.rules;
                        let us: Vec<u32> = self.topped.keys().copied().collect();
                        for u in us {
                            let Some(d) = self.acc.get_mut(&u) else { continue };
                            let t = self.topped.get_mut(&u).unwrap();
                            let ntl = d.q.abs() * mark;
                            let need = if d.q != 0.0 { (d.im_at(&rules, mark) - ntl / self.maxlev).max(0.0) } else { 0.0 };
                            let eq = d.m.unwrap_or(0.0) + (mark - d.e) * d.q;
                            let room = (eq - d.im_at(&rules, mark)).max(0.0);
                            let w = (*t - need).max(0.0).min(room);
                            if w > 0.0 { if let Some(m) = d.m.as_mut() { *m -= w; } *t -= w; self.cut_withdrawn += w; }
                        }
                    }
                }
                self.cut_on = on;
                println!("LEV CUT {} at {ms}: max leverage {}", if on { "on" } else { "off" }, self.rules.tiers[0].1);
                if on && self.rules.tier_topup {
                    let us: Vec<u32> = self.acc.keys().copied().collect();
                    for u in us { self.tier_topup(u, mark); }
                }
            }
        }
        if self.rules.cluster_k > 0.0 && !self.cl_t0_done {
            // positions held at the start: clusters as they stand at the first update
            self.cl_t0_done = true;
            let us: Vec<u32> = self.acc.iter().filter(|(_, d)| d.q != 0.0 && d.margined()).map(|(u, _)| *u).collect();
            for u in us { self.lock_cluster(u); }
        }
        if self.rules.tier_topup && !self.topup_t0_done {
            // positions held at the start: topped up as if the tiers had been in force when they were opened
            self.topup_t0_done = true;
            let us: Vec<u32> = self.acc.keys().copied().collect();
            for u in us { self.tier_topup(u, mark); }
        }
        if self.rules.tier_reduce && self.rules.ntiers >= 2 {
            if !self.topup_t0_done {
                // positions held at the start: shed to the capped size at the mark, margin kept
                self.topup_t0_done = true;
                let us: Vec<u32> = self.acc.iter().filter(|(_, d)| d.margined() && d.q != 0.0).map(|(u, _)| *u).collect();
                for u in us {
                    let d = self.acc[&u];
                    let tgt = self.reduce_target(&d, d.q, mark);
                    if (tgt - d.q).abs() > 1e-9 {
                        let rules = self.rules;
                        let a = self.acc.get_mut(&u).unwrap();
                        fill(a, tgt > d.q, mark, (tgt - d.q).abs(), 0.0, mark, rules, Reduce::Keep);
                        self.xs.insert(u, d.q - tgt);
                    }
                }
            }
            let shed: f64 = self.xs.values().map(|x| x.abs() * mark).sum();
            if shed > self.shed_peak { self.shed_peak = shed; }
        }
        let mut oi = 0usize;
        let rules = self.rules;
        let mut cand: Vec<u32> = self.acc.iter()
            .filter(|(_, d)| d.q != 0.0 && d.margined())
            .filter(|(_, d)| d.m.unwrap() + (mark - d.e) * d.q < d.req(&self.rules, mark))
            .map(|(u, _)| *u).collect();
        cand.sort();
        for u in cand {
            while oi < others.len() && others[oi].0 < u {
                let (tu, moid, sz, px, mu, tbuy) = others[oi];
                if book.fill_maker(moid, sz) { *last_px = Some(px); }
                self.book_fills.push((tu, mu, tbuy, sz));
                if self.endogenous {   // a replayed (real) liquidation fill: both accounts take it, as with other injected takers
                    self.apply_fill(&Fill { taker: tu, maker: mu, taker_buy: tbuy, px: px as f64 / 1e6, sz: sz as f64 / 1e6, taker_fee_rate: Some(self.liq_rate(tu)) });
                }
                oi += 1;
            }
            let d = *self.acc.get(&u).unwrap();
            let m = d.m.unwrap();
            let n = d.q.abs() * mark;
            let eq = m + (mark - d.e) * d.q;
            // Cross-enabled market: the vault takes the position over below backstop_frac * MM, at the price that leaves
            // the trader at 0. Isolated-only market (backstop=adl): there is no vault to hand it to, so the book
            // liquidation goes on at every update and the position is auto-deleveraged only once its equity at the mark
            // is negative, at the mark of the previous update (xyz:NET 2026-11-05: the 5 real ADL events each came 7
            // updates after equity crossed 2/3 MM, at the first update with equity < 0; all 13 ADL fills that day
            // printed at the previous update's mark).
            let (thr, adl) = if rules.adl_backstop && !rules.adl_at_mm { (0.0, true) } else { (rules.backstop_frac * d.req(&rules, mark), false) };
            if eq < thr {
                let px = if adl && prev_mark.is_finite() { prev_mark } else { d.e - m / d.q }; // vault: the trader ends at 0
                self.sim_takeovers.push(Takeover { h, u, q: d.q, px, mark, eq });
                let a = self.acc.get_mut(&u).unwrap();
                a.q = 0.0;
                a.e = 0.0;
                a.m = Some(0.0);
                self.xs.remove(&u);
                // its top-up went to the vault with the position: if the replay reopens it, it posts again
                self.topped.remove(&u);
                continue;
            }
            // isolated-only market, equity between 0 and backstop_frac * MM: adl_book=0 sends no more book orders
            // there (a variant kept for comparison); the default keeps sending them, with the zero-equity stop below
            if adl && !rules.adl_book && eq < rules.backstop_frac * d.req(&rules, mark) { continue; }
            self.xs.remove(&u);
            // the account's liquidation fills on coins HL processes first (lower asset index) land before this coin's
            // round: apply them now (crossacc writes them one block late, flagged `pre`) and drop them from the queue
            {
                let mut k = self.xcur;
                while k < self.xev.len() && self.xev[k].0 <= h + 1 {
                    let (eh, eu, dx, dmm, pre) = self.xev[k];
                    if pre && eu == u && eh == h + 1 {
                        if let Some(a) = self.acc.get_mut(&u) {
                            if a.cross_m { if let Some(m) = a.m.as_mut() { *m += dx; } a.mmo += dmm; }
                        }
                        self.xev[k].2 = 0.0; self.xev[k].3 = 0.0;
                    }
                    k += 1;
                }
            }
            // the fills above changed this account: re-read it, and with it the margin and equity the round size, the
            // backstop test and the bankruptcy price all depend on (they were read before those fills landed)
            let d = *self.acc.get(&u).unwrap();
            let m = d.m.unwrap();
            let eq = m + (mark - d.e) * d.q;
            let (full, req) = if rules.liq_restore > 0.0 && (n > rules.partial_ntl || !rules.restore_big) {
                // restore: keep the fraction eq / (k MM) of the position (MM is linear in size within a tier)
                let keep = (eq / (rules.liq_restore * d.req(&rules, mark))).clamp(0.0, 1.0);
                let r = ((1.0 - keep) * d.q.abs()).max(self.lot as f64 / 1e6).min(d.q.abs());
                (r >= d.q.abs() - 1e-12, r)
            } else {
                let incool = self.cooldown.get(&u).map_or(false, |&t| ms - t < rules.cooldown_ms);
                let full = n <= rules.partial_ntl || incool;
                if !full { self.cooldown.insert(u, ms); }
                (full, if full { d.q.abs() } else { rules.partial_frac * d.q.abs() })
            };
            let sell = d.q > 0.0;
            let limit: Px = if rules.liq_limit > 0.0 {
                ((mark * if sell { 1.0 - rules.liq_limit } else { 1.0 + rules.liq_limit }) * 1e6).round() as i64
            } else if sell { 0 } else { i64::MAX };
            // Walk the book; a liquidation fill is only taken while the account's equity stays at or above the backstop
            // threshold (backstop_frac * MM) of the remaining position, valued at the mark (observed: the whale's
            // round 2 stopped with equity $9 above 2/3 MM).
            let fee_rate = self.liq_rate(u);
            // equity stop against backstop_frac * R of the remaining position (R includes the other positions' MM)
            let (t_rate, t_ded) = d.mm_lin(&rules, mark);   // the position's tier (one tier: mmr, 0)
            let c_thr = rules.backstop_frac * d.pmf * t_rate * mark;
            let c_fix = rules.backstop_frac * (d.pmf * (d.mmo_pos() - t_ded) + d.pmc);
            // isolated-only market, account already below backstop_frac * MM: the order still goes to the book, as a
            // limit order at the position's bankruptcy price (where the trader ends at 0), with no equity stop: it fills
            // whatever rests at that price or better and nothing beyond. (xyz:RDDT 2026-10-29, one update, mark 118.99,
            // bid 116.78: the three accounts whose bankruptcy price was below the bid were sold on the book, the seven
            // whose bankruptcy price was above it got no fill at all, not a partial one, and were auto-deleveraged a
            // few updates later; xyz:NET 2026-11-05: the one update without a fill is the one where the book was beyond
            // the bankruptcy price.)
            let below = rules.adl_backstop && !rules.adl_at_mm && eq < rules.backstop_frac * d.req(&rules, mark);
            let limit: Px = if below {
                let pb = d.e - m / d.q;
                if sell { limit.max((pb * 1e6).ceil() as i64) } else { limit.min((pb * 1e6).floor() as i64) }
            } else { limit };
            if self.debug_u == Some(u) {
                let lv = book.levels(sell, 8);
                eprintln!("DEBUG u={u} h={h} mark={mark} eq={eq:.4} req={req:.3} R={:.4} mmo={:.4} pmf={} pmc={} cross={} q={:.3} e={:.3} m={:.4} | top levels (px, sz): {:?}",
                          d.req(&rules, mark), d.mmo, d.pmf, d.pmc, d.cross_m, d.q, d.e, m, lv.iter().map(|(p, s)| (*p as f64 / 1e6, *s as f64 / 1e6)).collect::<Vec<_>>());
            }
            // integer micro-units, like the book; HL floors the partial size to the size grid (10 partial rounds match only
            // the floored 20%, none only the nearest)
            let lot = self.lot;
            let mut left: i64 = ((req * 1e6).round() as i64 + if full { 0 } else { -(((req * 1e6).round() as i64) % lot) }).max(0);
            let mut filled = 0.0;
            // LIQ_ROUNDS_OUT: the book on the hit side before the walk (best, depth within 1% / 2% of it, in notional)
            let lr_pre = self.liq_rounds.is_some().then(|| {
                let lv = book.levels(sell, 400);
                let best = lv.first().map_or(0, |x| x.0) as f64 / 1e6;
                let dep = |w: f64| lv.iter().filter(|(p, _)| best > 0.0 && ((*p as f64 / 1e6) / best - 1.0).abs() <= w).map(|(p, z)| (*p as f64 / 1e6) * (*z as f64 / 1e6)).sum::<f64>();
                (book.best_bid(), book.best_ask(), dep(0.01), dep(0.02))
            });
            let (mut lr_ntl, mut lr_levels, mut lr_last) = (0.0f64, 0u32, -1i64);
            'lv: for lvl in book.reachable_levels(!sell, limit) {
                for k in book.level_orders(sell, lvl) {
                    if left <= 0 { break 'lv; }
                    let (mu, moid, msz) = { let o = &book.slab[k as usize]; (o.user, o.oid, o.sz) };
                    if mu == u { book.remove(moid); continue; }        // self-trade: expire maker
                    let px = lvl as f64 / 1e6;
                    let a = *self.acc.get(&u).unwrap();
                    let (a0q, a0e, a0m) = (a.q, a.e, a.m.unwrap());
                    let eq_now = a.m.unwrap() + (mark - a.e) * a.q;
                    let slip = if sell { mark - px } else { px - mark };
                    let denom = slip + fee_rate * px - c_thr;
                    let room = eq_now - c_fix - c_thr * a.q.abs();
                    let allow_i: i64 = if !rules.liq_equity_stop || below || denom <= 0.0 { i64::MAX } else { ((room / denom).max(0.0) * 1e6).floor() as i64 / lot * lot };
                    let f_i = left.min(msz).min(allow_i);
                    if f_i <= 0 { break 'lv; }
                    let f = f_i as f64 / 1e6;
                    book.fill_maker(moid, f_i);
                    self.book_fills.push((u, mu, !sell, f_i));
                    self.prints.push((px, f));
                    let a = self.acc.get_mut(&u).unwrap();
                    // a fill that closes the position below its bankruptcy price leaves the account negative
                    let av_px = a.m.unwrap() + (px - a.e) * a.q - px * f * fee_rate;
                    if f >= a.q.abs() - 1e-9 && av_px < 0.0 { self.liq_bad_debt += -av_px; }
                    fill(a, !sell, px, f, px * f * fee_rate, mark, rules, rules.liq_reduce);
                    if self.endogenous && mu != self.vault_uid {
                        // the maker's account takes the other side
                        let mrate = *self.fee_maker.get(&mu).unwrap_or(&0.0);
                        let maxlev = self.maxlev;
                        let dm = self.acc.entry(mu).or_insert(Acc { q: 0.0, e: 0.0, m: None, iso: Some(false), lev: maxlev, known: false, cross_m: false, mmo: 0.0, pmf: 1.0, pmc: 0.0, oi_ref: 0.0, cl_q: 0.0 });
                        if dm.iso.is_none() { dm.iso = Some(false); }
                        fill(dm, sell, px, f, px * f * mrate, mark, rules, rules.reduce);
                        self.bus_fills += 1;
                        self.engine_counterparties.insert(mu);
                    }
                    *last_px = Some(lvl);
                    filled += f;
                    left -= f_i;
                    lr_ntl += px * f;
                    if lvl != lr_last { lr_levels += 1; lr_last = lvl; }
                    if let Some(w) = self.stop_dump.as_mut() {
                        use std::io::Write;
                        // state before this fill: a0 (q, e, m); the round's start: d
                        writeln!(w, "{h},{u},{px},{f},{},{},{},{},{mark},{c_thr},{c_fix},{fee_rate},{},{},{},{},{},{},{}", a0q, a0e, a0m, allow_i as f64 / 1e6,
                                 d.q, d.e, m, d.mmo, d.pmf, d.pmc, rules.backstop_frac).unwrap();
                    }
                    if f_i == allow_i && f_i < msz.min(left + f_i) { break 'lv; }   // stopped by the equity rule
                }
            }
            if let (Some(w), Some((bb, ba, d1, d2))) = (self.liq_rounds.as_mut(), lr_pre) {
                use std::io::Write;
                let o = |x: Option<i64>| x.map_or(String::new(), |v| (v as f64 / 1e6).to_string());
                let avg = if filled > 0.0 { lr_ntl / filled } else { f64::NAN };
                writeln!(w, "{h},{ms},{u},{},{},{},{req},{filled},{avg},{mark},{},{},{},{},{d1},{d2},{lr_levels},{},{eq}", sell as u8, d.q.abs(), d.q.abs() * mark,
                         o(bb), o(ba), o(book.best_bid()), o(book.best_ask()), full as u8).unwrap();
            }
            self.sim_rounds.push(Round { h, u, req, filled, mark, eq_before: eq });
        }
        for &(tu, moid, sz, px, mu, tbuy) in &others[oi..] {
            if book.fill_maker(moid, sz) { *last_px = Some(px); }
            self.book_fills.push((tu, mu, tbuy, sz));
            if self.endogenous {
                self.apply_fill(&Fill { taker: tu, maker: mu, taker_buy: tbuy, px: px as f64 / 1e6, sz: sz as f64 / 1e6, taker_fee_rate: Some(self.liq_rate(tu)) });
            }
        }
    }

    /// liquidation fee rate of account u: its own (fees.arrow `liq`), else the prep's per-coin rate
    pub fn liq_rate(&self, u: u32) -> f64 { *self.fee_liq.get(&u).unwrap_or(&self.liq_fee_rate) }

    pub fn finish(&mut self) {
        if let Some(w) = self.stop_dump.as_mut() { use std::io::Write; w.flush().unwrap(); }
        if let Some(w) = self.liq_rounds.as_mut() { use std::io::Write; w.flush().unwrap(); }
        self.advance(i64::MAX, 255);
    }

    // ------------------------------------------------------------------ Phase-2a run (accounts + triggers only)
    pub fn run(&mut self, dir: &str, orc: &[OrcRec]) {
        let marks = marks_of(orc);
        let mut first_trig: AHashMap<u32, (i64, f64, bool)> = AHashMap::new();
        for &(h, x) in &marks {
            self.advance(h, 1);
            self.scan_triggers(h, x, &mut first_trig);
        }
        self.finish();
        self.report_takeovers(dir);
        self.report_triggers(&first_trig);
    }

    pub fn report_takeovers(&self, dir: &str) {
        let res = &self.takeover_check;
        if let Ok(p) = std::env::var("TK_OUT") {
            let mut s = String::from("u,sim_q,led_q,sim_eq,led_eq,ntl,known\n");
            for r in res { s += &format!("{},{},{},{},{},{},{}\n", r.0, r.1, r.2, r.3, r.4, r.5, r.6); }
            std::fs::write(p, s).unwrap();
        }
        if res.is_empty() {
            return;
        }
        let n = res.len() as f64;
        let pos_ok = res.iter().filter(|r| (r.1 - r.2).abs() < 1e-6).count() as f64;
        let mut errs: Vec<f64> = res.iter().map(|r| (r.3 - r.4).abs()).collect();
        errs.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let within1 = errs.iter().filter(|e| **e < 1.0).count() as f64;
        let bp1 = res.iter().filter(|r| (r.3 - r.4).abs() / r.5 * 1e4 < 1.0).count() as f64;
        println!("isolated takeovers scored {}  position exact {:.1}%", res.len(), 100.0 * pos_ok / n);
        println!("  |equity err| median ${:.2}  p90 ${:.2}  within $1 {:.0}%  within 1bp of ntl {:.0}%",
                 errs[errs.len() / 2], errs[(errs.len() as f64 * 0.9) as usize], 100.0 * within1 / n, 100.0 * bp1 / n);
        if let Some(w) = whale(dir) {
            if let Some(r) = res.iter().find(|r| r.0 == w) {
                println!("  whale: sim equity {:.2} ledger {:.2}  Q {} vs {}", r.3, r.4, r.1, r.2);
            }
        }
    }

    pub fn report_triggers(&self, first_trig: &AHashMap<u32, (i64, f64, bool)>) {
        let iso_set: AHashSet<u32> = self.acc.iter().filter(|(_, d)| d.iso == Some(true)).map(|(u, _)| *u).collect();
        let real: Vec<(u32, (i64, bool))> = self.real_first.iter().filter(|(u, _)| iso_set.contains(u)).map(|(u, v)| (*u, *v)).collect();
        let (mut both, mut same, mut within, mut early, mut late, mut agree, mut rb, mut sb) = (0, 0, 0, 0, 0, 0, 0, 0);
        for (u, (hr, bs)) in &real {
            if let Some((hs, _, sbk)) = first_trig.get(u) {
                both += 1;
                let dh = hs - hr;
                if dh == 0 { same += 1; }
                if dh.abs() <= 45 { within += 1; } else if dh < 0 { early += 1; } else { late += 1; }
                if *sbk == *bs { agree += 1; }
                if *bs { rb += 1; }
                if *sbk { sb += 1; }
            }
        }
        let missed = real.iter().filter(|(u, _)| !first_trig.contains_key(u)).count();
        let real_set: AHashSet<u32> = real.iter().map(|x| x.0).collect();
        let false_t = first_trig.keys().filter(|u| !real_set.contains(u)).count();
        let bf = both as f64;
        println!("LIQUIDATION TRIGGERS (isolated): real liquidated {}, sim triggered {}, both {}", real.len(), first_trig.len(), both);
        println!("  same block {:.1}%   within 1 relayer update {:.1}%   sim early {:.1}%  sim late {:.1}%",
                 100.0 * same as f64 / bf, 100.0 * within as f64 / bf, 100.0 * early as f64 / bf, 100.0 * late as f64 / bf);
        println!("  real liquidated but sim never triggered: {missed} | sim triggered but never liquidated: {false_t}");
        println!("  first action: real backstop-first {rb}  sim backstop-first {sb}  agree {:.4}", agree as f64 / bf);
    }
}

/// The position grew (same side) or flipped: an opening that re-references the account's OI tier.
fn grew(q0: f64, q1: f64) -> bool { q1 != 0.0 && (q0 == 0.0 || (q0 > 0.0) != (q1 > 0.0) || q1.abs() > q0.abs()) }

pub fn fill(d: &mut Acc, buy: bool, px: f64, sz: f64, fee: f64, mark: f64, rules: Rules, rule: Reduce) {
    let sgn = if buy { 1.0 } else { -1.0 };
    // opening margin: notional / leverage, plus (iso_open=mark|oracle) margin for the opened size's loss at the reference
    // price `mark`, by iso_mode. `slack` = the position's equity above IM before the fill.
    let gap = rules.iso_open_mark && mark.is_finite();
    let npx = if rules.iso_im_mark && mark.is_finite() { mark }
              else if rules.iso_im_better && mark.is_finite() { if buy { px.max(mark) } else { px.min(mark) } }
              else { px };
    let im = |s: f64, lv: f64, slack: f64| s * npx / lv + if gap && rules.iso_mode != 1 {
        ((sgn * (px - mark) * s).max(0.0) - if rules.iso_mode == 2 { slack.max(0.0) } else { 0.0 }).max(0.0)
    } else { 0.0 };
    let topup = |d: &mut Acc| if gap && rules.iso_mode == 1 && d.q != 0.0 {
        let lv = d.lev;
        let (q, e) = (d.q, d.e);
        if let Some(m) = d.m.as_mut() {
            let short = q.abs() * mark / lv - (*m + (mark - e) * q);
            if short > 0.0 { *m += short; }
        }
    };
    if d.cross_m {
        let q0 = d.q;
        let q1 = q0 + sgn * sz;
        if let Some(m) = d.m.as_mut() { *m -= fee; }
        if q0 == 0.0 || (q0 > 0.0) == (sgn > 0.0) {
            d.e = (q0.abs() * d.e + sz * px) / q1.abs();
        } else {
            let red = sz.min(q0.abs());
            let pnl = (px - d.e) * red * if q0 > 0.0 { 1.0 } else { -1.0 };
            if let Some(m) = d.m.as_mut() { *m += pnl; }
            if sz > q0.abs() { d.e = px; }
        }
        d.q = if q1.abs() > 1e-9 { q1 } else { 0.0 };
        if d.q == 0.0 { d.e = 0.0; }
        return;
    }
    let q0 = d.q;
    let q1 = q0 + sgn * sz;
    if rules.fee_iso {
        if let Some(m) = d.m.as_mut() { *m -= fee; }
    }
    let mut opened = false;
    if q0 == 0.0 || (q0 > 0.0) == (sgn > 0.0) {
        let lv = d.lev;
        let slack = d.m.map_or(0.0, |m| m + (mark - d.e) * q0 - q0.abs() * mark / lv);
        d.e = (q0.abs() * d.e + sz * px) / q1.abs();
        if let Some(m) = d.m.as_mut() { *m += im(sz, lv, slack); }
        opened = true;
    } else {
        let red = sz.min(q0.abs());
        let pnl = (px - d.e) * red * if q0 > 0.0 { 1.0 } else { -1.0 };
        let e0 = d.e;
        if let Some(m) = d.m.as_mut() {
            let rem = q0.abs() - red;
            *m = match rule {
                Reduce::Keep => *m + pnl,
                Reduce::PropBefore => *m * rem / q0.abs() + pnl,
                Reduce::PropAfter => (*m + pnl) * rem / q0.abs(),
                Reduce::EqRelease => {
                    let eq_px = *m + (px - e0) * q0; // equity before the fill, valued at the fill price
                    *m + pnl - eq_px.max(0.0) * red / q0.abs()
                }
            };
        }
        if sz > q0.abs() {
            d.e = px;
            let lv = d.lev;
            if let Some(m) = d.m.as_mut() { *m += im(sz - q0.abs(), lv, 0.0); }
            opened = true;
        }
    }
    d.q = if q1.abs() > 1e-9 { q1 } else { 0.0 };
    if opened { topup(d); }
    if d.q == 0.0 {
        d.e = 0.0;
        if let Some(m) = d.m.as_mut() { *m = 0.0; }
    }
}

/// Last relayer-update mark of each block (median(m1, m2, median(bid, ask, last))).
pub fn marks_of(orc: &[OrcRec]) -> Vec<(i64, f64)> {
    let mut marks: Vec<(i64, f64)> = Vec::new();
    for o in orc {
        if let Some(m) = mark_of(o) {
            match marks.last_mut() {
                Some(x) if x.0 == o.h => x.1 = m,
                _ => marks.push((o.h, m)),
            }
        }
    }
    marks
}

/// xyz's book price as Hyperliquid computes it: med(bid, ask, last). With one side of the book empty the remaining best
/// quote stands for the book price: what the tape shows (ec2/onesided_*.py, sim/tests_1110/RESULTS_10: on HIP-3 markets the
/// liquidation marks run toward the lone quote, past the last trade and the deployer's inputs). This is the default since the
/// formula was frozen (2026-11-11). ONE_SIDED=hold: no book price, the mark is left unchanged (the engine's rule before) |
/// last: the last trade stands for the book | drop: the book vote drops out, mark = mean of the two inputs (see mark_of).
/// Read once: `book_px` runs several times per relayer update, and an unknown mode must stop the run rather than
/// silently leave the book without a vote.
fn one_sided() -> &'static str {
    static MODE: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    MODE.get_or_init(|| {
        let v = std::env::var("ONE_SIDED").unwrap_or_default();
        assert!(matches!(v.as_str(), "" | "quote" | "hold" | "last" | "drop"), "unknown ONE_SIDED={v}: quote (default) | hold | last | drop");
        v
    })
}

pub fn book_px(o: &OrcRec) -> Option<Px> {
    let mode = one_sided();
    match (o.bid, o.ask, o.last) {
        (Some(b), Some(a), Some(l)) => Some(median3(b, a, l)),
        (_, _, Some(l)) if mode == "last" => Some(l),
        (Some(q), None, _) | (None, Some(q), _) if mode.is_empty() || mode == "quote" => Some(q),
        _ => None,
    }
}

pub fn mark_of(o: &OrcRec) -> Option<f64> {
    match book_px(o) {
        Some(bk) => Some(median3(o.m1, o.m2, bk).clamp(o.lo, o.hi) as f64 / 1e6),
        None if one_sided() == "drop" => Some(((o.m1 + o.m2) / 2).clamp(o.lo, o.hi) as f64 / 1e6),
        _ => None,
    }
}

pub fn whale(dir: &str) -> Option<u32> {
    user_id(dir, "0x30afce")
}

pub fn user_id(dir: &str, prefix: &str) -> Option<u32> {
    let users = reader(&format!("{dir}/users.arrow")).next().unwrap().unwrap();
    let names = users.column_by_name("user").unwrap().as_any().downcast_ref::<StringViewArray>().unwrap();
    let ids = col::<UInt32Type>(&users, "uid");
    (0..names.len()).find(|&i| names.value(i).starts_with(prefix)).map(|i| ids.value(i))
}
