//! Block replay of one coin's book from prep.py files. Port of replay_v1/replay_book.py
//! (ORDERING=orders_first_bundle, ENGINE_POS=end, PRUNE=1), printing the same checks.

use crate::book::*;
use crate::clearing::{book_px, mark_of, Acc, Clearing, Fill};
use crate::io::*;
use crate::events::{EventMerge, Row};
use crate::relayer::{Relayer, RelayerParams};
use crate::triggers::{Trig, TrigBook};
use ahash::{AHashMap, AHashSet};
use arrow_array::types::*;
use std::collections::{BTreeMap, BinaryHeap};
use std::cmp::Reverse;

#[derive(Clone, Copy, PartialEq)]
pub enum Match {
    TapeWalk,
    Engine,
}

/// One relayer update with the book-component inputs at that point.
#[derive(Clone, Copy)]
pub struct OrcRec {
    pub h: i64,
    pub m1: Px,
    pub m2: Px,
    pub bid: Option<Px>,
    pub ask: Option<Px>,
    pub last: Option<Px>,
    pub ms: i64,
    pub ext: Px,
    pub lag: u8,
    /// HyperCore's 1% per update: the final mark is clamped to [lo, hi] = previous final mark * (0.99, 1.01), rounded to
    /// 6 - szDecimals decimals (real liquidation fills: AMZN 10-29 235.47 -> 233.115, INTC 90.223 -> 89.3208). HL_CAP=0: off.
    pub lo: Px,
    pub hi: Px,
}

#[derive(Clone, Copy)]
pub struct Inj {
    pub m_oid: Oid,
    pub sz: Sz,
    pub trig: bool,
    pub px: Px,
    pub kind: u8,   // 0 other engine taker (TWAP, triggered stop), 1 liquidation round, 2 vault
    pub t_u: Uid,
    pub t_buy: bool,
    pub t_trig: bool, // taker is a triggered stop / take-profit order
    pub m_u: Uid,
}

/// Backstop vault inventory and PnL.
#[derive(Default, Debug)]
pub struct Vault {
    pub q: f64,
    pub e: f64,
    pub realized: f64,
    pub taken_ntl: f64,
    pub unwound_ntl: f64,
    pub fees: f64,
    /// VAULT_OUT: every inventory change (block, buy, px, size, kind 0 takeover / 1 unwind)
    pub now_h: i64,
    pub kind: u8,
    pub log: Vec<(i64, bool, f64, f64, u8)>,
}
impl Vault {
    pub fn trade(&mut self, buy: bool, px: f64, sz: f64) {
        self.log.push((self.now_h, buy, px, sz, self.kind));
        let sgn = if buy { 1.0 } else { -1.0 };
        let q1 = self.q + sgn * sz;
        if self.q == 0.0 || (self.q > 0.0) == buy {
            self.e = (self.q.abs() * self.e + sz * px) / q1.abs();
        } else {
            let red = sz.min(self.q.abs());
            self.realized += (px - self.e) * red * if self.q > 0.0 { 1.0 } else { -1.0 };
            if sz > self.q.abs() { self.e = px; }
        }
        self.q = if q1.abs() > 1e-9 { q1 } else { 0.0 };
    }
}

/// Vault unwind: "replay" (real vault fills injected from the tape) or "policy" (an IOC of `frac` of inventory at
/// every relayer update, limit mark -/+ `limit`; fitted on GOOGL 2026-10-28: frac 0.5%, one order per update).
#[derive(Clone, Copy)]
pub struct VaultPolicy {
    pub replay: bool,
    pub frac: f64,
    pub limit: f64,
    pub every: u32,
    pub min_ntl: f64,
    pub fair: bool,
}
impl VaultPolicy {
    pub fn from_env() -> Self {
        let g = |k: &str, d: &str| std::env::var(k).unwrap_or_else(|_| d.to_string());
        VaultPolicy {
            replay: g("VAULT", "policy") == "replay",
            frac: g("VAULT_FRAC", "0.005").parse().unwrap(),
            limit: g("VAULT_LIMIT", "1.0").parse().unwrap(),
            every: g("VAULT_EVERY", "1").parse().unwrap(),
            min_ntl: g("VAULT_MIN_NTL", "10").parse().unwrap(),
            fair: g("VAULT_FAIR", "0") == "1",
        }
    }
}

/// Counters for the parity checks. `tick` runs on every order event, so the key is the caller's literal and the
/// whole-day and in-window counts share one entry: no allocation per event.
#[derive(Default)]
struct Checks {
    c: BTreeMap<&'static str, (u64, u64, u64, u64)>,   // (ok, bad, ok in window, bad in window)
}
impl Checks {
    fn tick(&mut self, name: &'static str, ok: bool, win: bool) {
        let e = self.c.entry(name).or_default();
        if ok { e.0 += 1 } else { e.1 += 1 }
        if win { if ok { e.2 += 1 } else { e.3 += 1 } }
    }
}

pub struct Replay {
    pub book: Book,
    mode: Match,
    h0: i64,
    ms_of: Vec<i64>,
    w0: i64,
    w1: i64,
    real_fills: AHashMap<Oid, Vec<(Oid, Sz, Px, Uid)>>,
    inject: AHashMap<i64, Vec<Inj>>,
    l2: AHashMap<i64, ([Option<(Px, Sz)>; 5], [Option<(Px, Sz)>; 5])>,
    sched: AHashMap<Uid, i64>,
    sheap: BinaryHeap<Reverse<(i64, Uid)>>,
    sim_tr: AHashMap<(Oid, Oid), Sz>,
    chk: Checks,
    l2c: BTreeMap<&'static str, (u64, u64)>,
    pruned: BTreeMap<String, u64>,
    last_px: Option<Px>,
    pub orc: Vec<OrcRec>,
    pub vault: Vault,
    /// DEPTH_OUT: book depth every minute at relayer updates: (next sample ms, csv)
    depth: Option<(i64, String)>,
    /// MARK=own_a|own_b|own_c: own-book marks out of market hours (OwnMark)
    own: Option<OwnMark>,
    /// emit() is logging a forced fill (liquidation round or vault fill injected from the tape)
    forced_ctx: bool,
    /// ATTACK_AT (ms list) / ATTACK_NTL (notional list) / ATTACK_REPEAT (sweeps, 3 s apart) / ATTACK_SIDE (sell|buy):
    /// a market sweep by a fresh account, to measure how far it moves the mark; log written to ATTACK_OUT
    attack: Option<(std::collections::VecDeque<(i64, usize, f64)>, bool, String)>,
    /// more attacks (Atk2::from_env): makers pulled, relayer outage, sell wall, wash prints, trigger-fire window
    atk2: Atk2,
    vault_seen: usize,
    ext_seen: usize,
    /// backstop=adl: notional auto-deleveraged (takeovers kept out of the vault)
    pub adl_ntl: f64,
    liq_done_h: Option<i64>,
    pub vp: VaultPolicy,
    vault_fee_rate: f64,
    n_updates: u32,
    pub relayer: Option<Relayer>,
    pub trig: Option<TrigBook>,
    pm_diag: Option<Vec<String>>,
    /// PM_DIAG in tape-walk: the price the engine would give this taker (bankruptcy limit of a margined account's
    /// IOC / market order), used by the dry match only; the tape walk follows the real fills
    diag_px: Option<Px>,
    qdiag: Option<Vec<String>>,                 // QUEUE_DIAG: queue patterns at partially consumed levels
    silent: AHashMap<Oid, Vec<Oid>>,            // SILENT=1: HL's silent cancels, applied right before the revealing taker
    silent_n: u64,
    /// Signed position per user (micro-units): snapshot + every fill the replay makes. Used for reduce-only caps in pure
    /// matching (Match::Engine).
    pub pos: AHashMap<Uid, i64>,
    pub ro_capped: u64,
    pub ro_rejected: u64,
    pub ro_maker_cancel: u64,
    margin_caps: AHashMap<Oid, i64>,
    /// Silent cancels applied, by (side, px): (oid, size, block). A later 1-min L2 snapshot whose level holds exactly that
    /// much more than our book vetoes them (VETO_OUT): the order was still resting.
    silent_removed: AHashMap<(bool, Px), Vec<(Oid, Sz, i64)>>,
    vetoes: Vec<(Oid, i64)>,            // MARGIN=1: inferred match-time margin caps (notional) of opening takers
    pub margin_capped: u64,
    trig_im: bool,          // TRIG_IM=1: initial-margin check of triggered orders (off: rejects real fills of unified accounts)
    trig_im_rejected: u64,
    /// sanity cap on triggered orders: opening notional <= order_cap_x * max_lev * max(account value, $1k) (acc_av.arrow;
    /// ORDER_CAP_X, default 5, 0 = off). Catches orders no account could margin (INTC: $27.6B of $10 buy triggers).
    acc_av: AHashMap<Uid, f64>,
    order_cap_x: f64,
    pub max_lev: f64,
    /// price step of HyperCore's clamped mark: 10^-(6 - szDecimals), in micro-units
    pub cap_step: i64,
    trig_cap_rejected: u64,               // PM_DIAG: pure match vs real fills, one row per user taker                 // TRIGGERS=simulate
    trig_real: AHashMap<Oid, (i64, Sz)>,        // real trigger takers: first fill block, total size
    pub vault_orders: Vec<(i64, f64, f64)>, // h, requested, filled
    pub vault_fair_ntl: f64,
    pub endo: bool,
    bus: Vec<Fill>,
}

impl Replay {
    pub fn new(dir: &str, mode: Match) -> Self {
        let meta: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(format!("{dir}/meta.json")).unwrap()).unwrap();
        let bh = load::<Int64Type>(&format!("{dir}/blocks.arrow"), "h");
        let bms = load::<Int64Type>(&format!("{dir}/blocks.arrow"), "ms");
        let h0 = bh[0];
        let mut ms_of = vec![0i64; (bh[bh.len() - 1] - h0 + 1) as usize];
        for (h, m) in bh.iter().zip(bms.iter()) {
            ms_of[(h - h0) as usize] = *m;
        }
        let mut real_fills: AHashMap<Oid, Vec<(Oid, Sz, Px, Uid)>> = AHashMap::new();
        let rf = format!("{dir}/real_fills.arrow");
        let (rt, rm, rs, rp, ru) = (load::<Int64Type>(&rf, "t_oid"), load::<Int64Type>(&rf, "m_oid"), load::<Int64Type>(&rf, "sz"), load::<Int64Type>(&rf, "px"), load::<UInt32Type>(&rf, "m_u"));
        for k in 0..rt.len() {
            real_fills.entry(rt[k]).or_default().push((rm[k], rs[k], rp[k], ru[k]));
        }
        let trig_sim = std::env::var("TRIGGERS").as_deref() == Ok("simulate");
        let mut trig_real: AHashMap<Oid, (i64, Sz)> = AHashMap::new();
        let tf = format!("{dir}/trig_fills.arrow");
        if trig_sim {
            let (tt, tm, ts, tp, tu, th) = (load::<Int64Type>(&tf, "t_oid"), load::<Int64Type>(&tf, "m_oid"), load::<Int64Type>(&tf, "sz"), load::<Int64Type>(&tf, "px"), load::<UInt32Type>(&tf, "m_u"), load::<Int64Type>(&tf, "h"));
            for k in 0..tt.len() {
                real_fills.entry(tt[k]).or_default().push((tm[k], ts[k], tp[k], tu[k]));
                let e = trig_real.entry(tt[k]).or_insert((th[k], 0));
                e.0 = e.0.min(th[k]);
                e.1 += ts[k];
            }
        }
        let mut inject: AHashMap<i64, Vec<Inj>> = AHashMap::new();
        let inj = format!("{dir}/inject.arrow");
        let ih = load::<Int64Type>(&inj, "h");
        let im = load::<Int64Type>(&inj, "m_oid");
        let isz = load::<Int64Type>(&inj, "sz");
        let itr = load_bool(&inj, "m_is_trig");
        let ipx = load::<Int64Type>(&inj, "px");
        let ik = load::<UInt8Type>(&inj, "t_kind");
        let itu = load::<UInt32Type>(&inj, "t_u");
        let itb = load_bool(&inj, "t_buy");
        let itt = load_bool(&inj, "t_is_trig");
        let imu = load::<UInt32Type>(&inj, "m_u");
        for k in 0..ih.len() {
            if trig_sim && ik[k] == 0 && itt[k] { continue; } // the engine fires these triggers itself
            inject.entry(ih[k]).or_default().push(Inj { m_oid: im[k], sz: isz[k], trig: itr[k], px: ipx[k], kind: ik[k], t_u: itu[k], t_buy: itb[k], t_trig: itt[k], m_u: imu[k] });
        }
        let mut l2: AHashMap<i64, ([Option<(Px, Sz)>; 5], [Option<(Px, Sz)>; 5])> = AHashMap::new();
        let lf = format!("{dir}/l2.arrow");
        let (lh, lb, ll, lp, ls) = (load::<Int64Type>(&lf, "h"), load::<UInt8Type>(&lf, "buy"), load::<UInt8Type>(&lf, "lvl"), load::<Int64Type>(&lf, "px"), load::<Int64Type>(&lf, "sz"));
        for k in 0..lh.len() {
            let e = l2.entry(lh[k]).or_insert(([None; 5], [None; 5]));
            let arr = if lb[k] == 1 { &mut e.0 } else { &mut e.1 };
            arr[ll[k] as usize] = Some((lp[k], ls[k]));
        }
        let mut book = Book::new();
        // HL priority bids (sim/prep/prio.py): a higher bid queues ahead of lower bids that arrived < PRIO_WINDOW_MS (399) before
        // it, else FIFO. PRIO=0: plain price-time.
        let pf = format!("{dir}/prio.arrow");
        if std::env::var("PRIO").map_or(true, |v| v != "0") && std::path::Path::new(&pf).exists() {
            let (o, r) = (load::<Int64Type>(&pf, "oid"), load::<Int32Type>(&pf, "rank"));
            book.prio = o.into_iter().zip(r).collect();
            book.prio_window_ms = std::env::var("PRIO_WINDOW_MS").ok().and_then(|v| v.parse().ok()).unwrap_or(399);
        }
        let sf = format!("{dir}/seeds.arrow");
        let (so, su, sb, sp, ss) = (load::<Int64Type>(&sf, "m_oid"), load::<UInt32Type>(&sf, "u"), load_bool(&sf, "buy"), load::<Int64Type>(&sf, "px"), load::<Int64Type>(&sf, "sz"));
        for k in 0..so.len() {
            book.rest(so[k], su[k], sb[k], sp[k], ss[k], 0);
        }
        eprintln!("seeded pre-window resting orders {}", so.len());
        Replay {
            book, mode, h0, ms_of,
            w0: meta["w0_ms"].as_i64().unwrap(), w1: meta["w1_ms"].as_i64().unwrap(),
            real_fills, inject, l2,
            sched: AHashMap::new(), sheap: BinaryHeap::new(), sim_tr: AHashMap::new(),
            chk: Checks::default(), l2c: BTreeMap::new(), pruned: BTreeMap::new(), last_px: None, orc: Vec::new(),
            vault: Vault::default(), own: OwnMark::from_env(), forced_ctx: false, atk2: Atk2::from_env(), attack: std::env::var("ATTACK_AT").ok().map(|at| {
                let ntl: Vec<f64> = std::env::var("ATTACK_NTL").unwrap().split(',').map(|x| x.parse().unwrap()).collect();
                let rep: i64 = std::env::var("ATTACK_REPEAT").ok().and_then(|v| v.parse().ok()).unwrap_or(1);
                let mut q: Vec<(i64, usize, f64)> = Vec::new();
                for (i, a) in at.split(',').enumerate() {
                    let t0: i64 = a.parse().unwrap();
                    for k in 0..rep { q.push((t0 + 3000 * k, i, ntl[i % ntl.len()])); }
                }
                q.sort_by_key(|x| x.0);
                (q.into(), std::env::var("ATTACK_SIDE").map_or(false, |v| v == "buy"), String::from("id,ms,mid0,ntl,filled_sz,filled_ntl,cost\n"))
            }), depth: std::env::var("DEPTH_OUT").ok().map(|_| (0, String::from("h,ms,mid,side,dbps,ntl\n"))), vault_seen: 0, ext_seen: 0, adl_ntl: 0.0, liq_done_h: None,
            vp: VaultPolicy::from_env(), n_updates: 0, vault_orders: vec![], vault_fair_ntl: 0.0,
            trig: trig_sim.then(TrigBook::default), trig_real,
            qdiag: std::env::var("QUEUE_DIAG").ok().map(|_| vec!["oid,h,px,pattern,oids".to_string()]),
            silent: {
                let mut m: AHashMap<Oid, Vec<Oid>> = AHashMap::new();
                let f = format!("{dir}/silent_cancels.arrow");
                if std::env::var("SILENT").map_or(false, |v| v != "0") && std::path::Path::new(&f).exists() {
                    let (t, mo) = (load::<Int64Type>(&f, "t_oid"), load::<Int64Type>(&f, "m_oid"));
                    for k in 0..t.len() { m.entry(t[k]).or_default().push(mo[k]); }
                }
                m
            },
            silent_n: 0,
            pos: {
                // ACC_INIT: another initial account table (sim/prep/lev_fit.py tries leverages without copying the prep)
                let f = std::env::var("ACC_INIT").unwrap_or_else(|_| format!("{dir}/acc_init.arrow"));
                let (u, q) = (load::<UInt32Type>(&f, "u"), load::<Float64Type>(&f, "q"));
                u.iter().zip(q.iter()).map(|(&u, &q)| (u, (q * 1e6).round() as i64)).collect()
            },
            ro_capped: 0, ro_rejected: 0, ro_maker_cancel: 0,
            acc_av: {
                let f = format!("{dir}/acc_av.arrow");
                if std::path::Path::new(&f).exists() {
                    let (u, a) = (load::<UInt32Type>(&f, "u"), load::<Float64Type>(&f, "av"));
                    u.into_iter().zip(a).collect()
                } else { AHashMap::new() }
            },
            order_cap_x: std::env::var("ORDER_CAP_X").ok().and_then(|v| v.parse().ok()).unwrap_or(5.0),
            max_lev: 0.0, trig_cap_rejected: 0,
            margin_caps: {
                let f = format!("{dir}/margin_caps.arrow");
                if std::env::var("MARGIN").map_or(false, |v| v != "0") && std::path::Path::new(&f).exists() {
                    let (t, c) = (load::<Int64Type>(&f, "t_oid"), load::<Int64Type>(&f, "cap_ntl"));
                    t.into_iter().zip(c).collect()
                } else { AHashMap::new() }
            },
            margin_capped: 0,
            trig_im: std::env::var("TRIG_IM").map_or(false, |v| v == "1"), trig_im_rejected: 0,
            silent_removed: AHashMap::new(), vetoes: Vec::new(),
            diag_px: None,
            pm_diag: std::env::var("PM_DIAG").ok().map(|_| vec!["oid,u,h,buy,px,sz,m,mu,mpx,real_sz,sim_sz,inbook,book_sz,sim_idx".to_string()]),
            relayer: (std::env::var("MARK_SOURCE").as_deref() == Ok("simulate")).then(|| {
                Relayer::new(RelayerParams::from_env(meta["w0_ms"].as_i64().unwrap()), meta["sz_decimals"].as_i64().unwrap() as i32)
            }),
            vault_fee_rate: meta["vault_fee_rate"].as_f64().unwrap_or(0.0),
            cap_step: 10i64.pow((meta["sz_decimals"].as_i64().unwrap_or(2)) as u32),
            endo: false, bus: Vec::new(),
        }
    }

    fn mid(&self) -> Option<f64> {
        match (self.book.best_bid(), self.book.best_ask()) {
            (Some(b), Some(a)) => Some((b + a) as f64 / 2e6),
            _ => None,
        }
    }

    fn ms(&self, h: i64) -> i64 {
        let k = h - self.h0;
        if k >= 0 && (k as usize) < self.ms_of.len() { self.ms_of[k as usize] } else { 0 }
    }
    fn win(&self, h: i64) -> bool {
        let m = self.ms(h);
        self.w0 <= m && m < self.w1
    }
    fn tick(&mut self, name: &'static str, ok: bool, h: i64) {
        let w = self.win(h);
        self.chk.tick(name, ok, w);
    }

    fn emit(&mut self, taker: Uid, maker: Uid, taker_buy: bool, px: Px, sz: Sz) {
        if taker == PROP_U || maker == PROP_U {
            let buy = (taker == PROP_U) == taker_buy;
            let (p, z) = (px as f64 / 1e6, sz as f64 / 1e6);
            self.atk2.prop_q += if buy { z } else { -z };
            self.atk2.prop_cash -= if buy { p * z } else { -p * z };
            self.atk2.prop_max_q = self.atk2.prop_max_q.max(self.atk2.prop_q.abs());
            if self.atk2.prop_cap.is_some() { self.atk2.prop_fills.push((PROP_U, buy, p, z, taker == PROP_U)); }
        }
        if self.atk2.cap.is_some() {
            for u in [SWEEP_U, WALL_U, WASH_A, WASH_B] {
                if taker == u || maker == u {
                    let (p, z) = (px as f64 / 1e6, sz as f64 / 1e6);
                    self.atk2.prop_fills.push((u, (taker == u) == taker_buy, p, z, taker == u));
                }
            }
        }
        self.move_pos(taker, maker, taker_buy, sz);
        let forced = self.forced_ctx;
        if let Some(o) = self.own.as_mut() { o.trade_f(self.book.now_ms, px as f64 / 1e6, sz as f64 / 1e6, forced); }
        if self.endo {
            self.bus.push(Fill { taker, maker, taker_buy, px: px as f64 / 1e6, sz: sz as f64 / 1e6, taker_fee_rate: None });
        }
    }

    fn move_pos(&mut self, taker: Uid, maker: Uid, taker_buy: bool, sz: Sz) {
        let d = if taker_buy { sz } else { -sz };
        *self.pos.entry(taker).or_default() += d;
        *self.pos.entry(maker).or_default() -= d;
    }

    /// Book the attacker's replay fills in its clearing account (taker at the coin's base taker rate, maker at 0).
    /// Notional a synthetic attacker can still place (HL's order margin check: free margin x max leverage); None when the
    /// attackers are phantoms (ATTACK_CAP unset) or no clearing is attached.
    fn syn_budget(&mut self, u: Uid, c: Option<&mut Clearing>) -> Option<f64> {
        let cap = self.atk2.cap?;
        let c = c?;
        c.add_attacker(u, cap);
        self.book_prop_fills(c);
        Some((c.free_margin(u).unwrap_or(0.0) * c.max_lev()).max(0.0))
    }

    /// A faithful wash: WASH_A rests an ask at p, WASH_B sends a buy limit p for the same size (both within their margin).
    /// B's order walks every real ask below p first (HyperCore price-time); the print enters P and the last price as any trade.
    /// Returns (shares B bought from the book, from A).
    fn wash_trade(&mut self, p: Px, ntl: f64, mut c: Option<&mut Clearing>) -> (f64, f64) {
        let mut n = ntl;
        if let Some(b) = self.syn_budget(WASH_A, c.as_deref_mut()) { n = n.min(b); }
        if let Some(b) = self.syn_budget(WASH_B, c.as_deref_mut()) { n = n.min(b); }
        let sz = ((n / (p as f64 / 1e6)) * 1e6) as Sz;
        if sz <= 0 { return (0.0, 0.0); }
        self.book.rest_ro(WASH_OID, WASH_A, false, p, sz, 0, false);
        let (fills, _, _) = self.book.match_order_caps(true, p, sz, WASH_B, &self.pos, None);
        let (mut from_book, mut from_a) = (0.0, 0.0);
        for (m, mu, px, f) in fills {
            if let Some(tr) = self.trig.as_mut() { tr.parent_filled(m); }
            self.last_px = Some(px);
            self.emit(WASH_B, mu, true, px, f);
            if mu == WASH_A { from_a += f as f64 / 1e6 } else { from_book += f as f64 / 1e6 }
        }
        self.book.remove(WASH_OID);
        (from_book, from_a)
    }

    /// Give the clearing the fills it made on the book (liquidation orders).
    fn book_prop_fills(&mut self, c: &mut Clearing) {
        for (u, buy, px, sz, taker) in std::mem::take(&mut self.atk2.prop_fills) {
            let cap = if u == PROP_U { self.atk2.prop_cap } else { self.atk2.cap }.unwrap_or(0.0);
            c.add_attacker(u, cap);
            let fr = if taker { c.liq_rate(u) } else { 0.0 };
            c.ext_fill(u, buy, px, sz, fr);
        }
    }

    fn sync_clearing(&mut self, c: &mut Clearing) {
        for (t, m, b, z) in std::mem::take(&mut c.book_fills) { self.move_pos(t, m, b, z); }
    }


    fn start_block(&mut self, h: i64, mut clr: Option<&mut Clearing>) {
        let t = self.ms(h);
        self.book.now_ms = t;
        if let Some((us, a, _)) = self.atk2.pull.clone() {
            if t >= a && !self.atk2.pull_done {
                self.atk2.pull_done = true;
                let mut n = 0.0;
                for u in us { for (p, z) in self.book.user_orders(u) { n += p as f64 / 1e6 * z as f64 / 1e6; } self.book.cancel_user(u); if let Some(tr) = self.trig.as_mut() { tr.cancel_user(u); } }
                self.atk2.log.push(format!("pull at {t}: cancelled ${n:.0} of resting orders"));
            }
        }
        if let Some((a, b, ntl)) = self.atk2.wall {
            self.book.remove(WALL_OID);
            if t >= a && t < b {
                if let Some(bb) = self.book.best_bid() {
                    let p = bb + tick_of(bb);
                    if self.book.best_ask().map_or(true, |x| x > p) {
                        let n = self.syn_budget(WALL_U, clr.as_deref_mut()).map_or(ntl, |b| ntl.min(b));
                        if n > 0.0 { self.book.rest_ro(WALL_OID, WALL_U, false, p, ((n / (p as f64 / 1e6)) * 1e6) as Sz, 0, false); }
                    }
                }
            }
        }
        if let Some((a, b, fr, ntl)) = self.atk2.prop {
            self.book.remove(PROP_OID);
            if t >= a && t < b {
                if self.atk2.prop_px.is_none() { if let Some(m) = self.mid() { self.atk2.prop_px = Some((m * (1.0 + fr) * 1e6) as Px / 10000 * 10000); } }
                if let Some(p0) = self.atk2.prop_px {
                    let mut ntl_b = ntl;
                    if let (Some(cap), Some(c)) = (self.atk2.prop_cap, clr.as_deref_mut()) {
                        // HL's order margin check: the order's notional / max leverage must fit in the free margin
                        c.add_attacker(PROP_U, cap);
                        self.book_prop_fills(c);
                        ntl_b = ntl.min((c.free_margin(PROP_U).unwrap_or(0.0) * c.max_lev()).max(0.0));
                    }
                    let sz = ((ntl_b / (p0 as f64 / 1e6)) * 1e6) as Sz;
                    let pbuy = fr >= 0.0;   // frac < 0: the mirror attack, a sell limit below the mid (hits every bid at or above P0)
                    let (fills, _, _) = self.book.match_order_caps(pbuy, p0, sz, PROP_U, &self.pos, None);
                    let mut left = sz;
                    for (m, mu, px, f) in fills {
                        if let Some(tr) = self.trig.as_mut() { tr.parent_filled(m); }
                        self.last_px = Some(px);
                        self.emit(PROP_U, mu, pbuy, px, f);
                        left -= f;
                    }
                    if left > 0 { self.book.rest_ro(PROP_OID, PROP_U, pbuy, p0, left, 0, false); }
                }
            }
        }
        while self.attack.as_ref().map_or(false, |a| a.0.front().map_or(false, |x| x.0 <= t)) {
            let (buy, (_, id, ntl)) = { let a = self.attack.as_mut().unwrap(); (a.1, a.0.pop_front().unwrap()) };
            if let Some(mid) = self.mid() {
                let ntl = self.syn_budget(SWEEP_U, clr.as_deref_mut()).map_or(ntl, |b| ntl.min(b));
                let sz = ((ntl / mid) * 1e6) as Sz;
                let attacker: Uid = SWEEP_U;
                let (fills, _, _) = self.book.match_order_caps(buy, if buy { i64::MAX } else { 0 }, sz, attacker, &self.pos, None);
                let (mut fz, mut fn_, mut cost) = (0.0, 0.0, 0.0);
                for (m, mu, px, f) in fills {
                    if let Some(tr) = self.trig.as_mut() { tr.parent_filled(m); }
                    self.last_px = Some(px);
                    self.emit(attacker, mu, buy, px, f);
                    let (p, z) = (px as f64 / 1e6, f as f64 / 1e6);
                    fz += z; fn_ += p * z; cost += if buy { p - mid } else { mid - p } * z;
                }
                self.attack.as_mut().unwrap().2.push_str(&format!("{id},{t},{mid},{ntl},{fz},{fn_:.0},{cost:.0}\n"));
            }
        }
        while let Some(&Reverse((tm, u))) = self.sheap.peek() {
            if tm > t {
                break;
            }
            self.sheap.pop();
            if self.sched.get(&u) == Some(&tm) {
                self.book.cancel_user(u);
                if let Some(t) = self.trig.as_mut() { t.cancel_user(u); }
                self.sched.remove(&u);
            }
        }
    }

    fn end_block(&mut self, h: i64, cl: &mut Option<&mut Clearing>) {
        let mut v = self.inject.remove(&h).unwrap_or_default();
        if let Some(c) = cl.as_deref_mut() {
            c.advance(h, 1);
            let b = std::mem::take(&mut self.bus);
            for f in &b { c.apply_fill(f); }
            // kind-1 fills are either simulated (engine accounts) or were applied inside liquidate() at the relayer update
            if self.liq_done_h == Some(h) {
                v.retain(|j| j.kind != 1);
            } else {
                v.retain(|j| j.kind != 1 || !(c.engine_handles(j.t_u) || c.sim_handled(j.t_u)));
            }
        }
        if cl.is_some() && !self.vp.replay {
            v.retain(|j| j.kind != 2);
        }
        {
            for j in v {
                if let Some(&k) = self.book.by_oid.get(&j.m_oid) {
                    self.last_px = Some(self.book.slab[k as usize].px);
                }
                let ok = self.book.fill_maker(j.m_oid, j.sz) || j.trig;
                if let Some(t) = self.trig.as_mut() { t.parent_filled(j.m_oid); }
                self.tick("inject_maker_found", ok, h);
                self.forced_ctx = j.kind == 1 || j.kind == 2;
                self.emit(j.t_u, j.m_u, j.t_buy, j.px, j.sz);
                self.forced_ctx = false;
                if j.kind == 2 && cl.is_some() {
                    self.vault.now_h = h; self.vault.kind = 1;
                    self.vault.trade(j.t_buy, j.px as f64 / 1e6, j.sz as f64 / 1e6);
                    self.vault.unwound_ntl += j.px as f64 / 1e6 * j.sz as f64 / 1e6;
                }
            }
        }
        if let Some(c) = cl.as_deref_mut() {
            self.vault.now_h = h; self.vault.kind = 0;
            // takeovers are inherited where they happen (the relayer-update path); nothing is left to do here
            debug_assert_eq!(self.vault_seen, c.sim_takeovers.len(), "a takeover was not inherited at its update");
            let e0 = self.ext_seen;
            for t in &c.ext_takeovers[e0..] {
                let qi = (t.q * 1e6).round() as i64;
                *self.pos.entry(t.u).or_default() -= qi;
                if c.rules.adl_backstop { self.adl_ntl += t.px * t.q.abs(); continue; }
                *self.pos.entry(c.vault_uid).or_default() += qi;
                self.vault.trade(t.q > 0.0, t.px, t.q.abs());
                self.vault.taken_ntl += t.px * t.q.abs();
            }
            self.ext_seen = c.ext_takeovers.len();
            let b = std::mem::take(&mut self.bus);
            for f in &b { c.apply_fill(f); }
            c.advance(h, 3);
        }
        if let Some((rb, ra)) = self.l2.get(&h).cloned() {
            for (buy, real) in [(true, rb), (false, ra)] {
                let real: Vec<(Px, Sz)> = real.iter().flatten().copied().collect();
                let sim = self.book.levels(buy, 5);
                let best = !real.is_empty() && !sim.is_empty() && real[0].0 == sim[0].0;
                let e = self.l2c.entry("best_px").or_default(); if best { e.0 += 1 } else { e.1 += 1 }
                let e = self.l2c.entry("top5_exact").or_default(); if real == sim { e.0 += 1 } else { e.1 += 1 }
                let pe = real.iter().map(|x| x.0).eq(sim.iter().map(|x| x.0));
                let e = self.l2c.entry("top5_px").or_default(); if pe { e.0 += 1 } else { e.1 += 1 }
                if !self.silent_removed.is_empty() {
                    let simsz: AHashMap<Px, Sz> = self.book.levels(buy, 50).into_iter().collect();
                    for &(px, rsz) in &real {
                        let d = rsz - simsz.get(&px).copied().unwrap_or(0);
                        if d <= 0 { continue; }
                        if let Some(v) = self.silent_removed.get_mut(&(buy, px)) {
                            // one removed order of exactly the missing size, else all of them if they add up to it
                            let pick: Vec<usize> = if let Some(i) = v.iter().position(|x| x.1 == d && x.2 < h) { vec![i] }
                                else if v.iter().filter(|x| x.2 < h).map(|x| x.1).sum::<Sz>() == d { (0..v.len()).filter(|&i| v[i].2 < h).collect() }
                                else { vec![] };
                            for &i in pick.iter().rev() { let (o, _, _) = v.remove(i); self.vetoes.push((o, h)); }
                        }
                    }
                }
            }
        }
    }

    fn prune(&mut self, buy_side: bool, px: Px, why: &str) {
        let n = self.book.prune_better(buy_side, px);
        if n > 0 {
            *self.pruned.entry(why.to_string()).or_default() += n as u64;
        }
    }

    fn tape_walk(&mut self, oid: Oid, u: Uid, buy: bool, p: Px, s: Sz, h: i64) -> Sz {
        let real = self.real_fills.get(&oid).cloned();
        if self.pm_diag.is_some() { self.pm_compare(oid, u, buy, p, s, h, real.as_deref().unwrap_or(&[])); }
        let mut want: AHashMap<Oid, Sz> = AHashMap::new();
        let mut want_order: Vec<Oid> = Vec::new();
        let mut real_px: AHashMap<Oid, (Px, Uid)> = AHashMap::new();
        if let Some(rf) = &real {
            for &(m, sz, rpx, ru) in rf {
                if !want.contains_key(&m) { want_order.push(m); }
                *want.entry(m).or_default() += sz;
                real_px.insert(m, (rpx, ru));
            }
        }
        let mut rem = s;
        let mut stp: Vec<u32> = Vec::new();
        let levels = self.book.reachable_levels(buy, p);
        'outer: for &lvl in &levels {
            if want.is_empty() { break; }
            for k in self.book.level_orders(!buy, lvl) {
                if want.is_empty() { break 'outer; }
                let (mu, moid) = { let o = &self.book.slab[k as usize]; (o.user, o.oid) };
                if mu == u {
                    stp.push(k);
                } else if let Some(f) = want.remove(&moid) {
                    rem -= f;
                    *self.sim_tr.entry((oid, moid)).or_default() += f;
                    self.book.fill_maker(moid, f);
                    if let Some(t) = self.trig.as_mut() { t.parent_filled(moid); }
                    self.last_px = Some(lvl);
                    self.emit(u, mu, buy, lvl, f);
                }
            }
        }
        for m in want_order {
            if let Some(sz) = want.remove(&m) {
                self.tick("tape_maker_in_book", false, h);
                self.book.fill_maker(m, sz);
                if let Some(t) = self.trig.as_mut() { t.parent_filled(m); }
                rem -= sz;
                let (rpx, ru) = real_px[&m];
                self.emit(u, ru, buy, rpx, sz);       // the real fill happened even if the maker is not in the simulated book
            }
        }
        if real.as_ref().map_or(false, |r| !r.is_empty()) {
            self.tick("tape_maker_in_book", true, h);
        }
        if rem > 0 {
            'o2: for &lvl in &levels {
                for k in self.book.level_orders(!buy, lvl) {
                    let mu = self.book.slab[k as usize].user;
                    if mu == u {
                        if !stp.contains(&k) { stp.push(k); }
                    } else {
                        break 'o2;
                    }
                }
            }
        }
        for k in stp {
            let o = &self.book.slab[k as usize];
            if o.live {
                let oid2 = o.oid;
                if self.book.remove(oid2) { self.tick("stp_cancel", true, h); }
            }
        }
        rem
    }

    #[allow(clippy::too_many_arguments)]
    fn place(&mut self, oid: Oid, u: Uid, buy: bool, p: Px, s: Sz, tif: u8, cl: u64, filled: i64, h: i64, ro: bool) {
        if self.atk2.pulled(u, self.book.now_ms) { return; }
        if let Some(v) = self.silent.remove(&oid) {
            for m in v {
                if let Some(&k) = self.book.by_oid.get(&m) {
                    let o = &self.book.slab[k as usize];
                    self.silent_removed.entry((o.buy, o.px)).or_default().push((m, o.sz, h));
                }
                if self.book.remove(m) { self.silent_n += 1; }
                if let Some(t) = self.trig.as_mut() { t.parent_cancelled(m); }
            }
        }
        if tif == 0 {
            // ATTACK_PROP: a post-only ask at or below the attacker's bid sells to it at the bid (a maker facing a buyer above
            // the market), instead of the replay's usual pruning of the crossing bid
            let mut s = s;
            let pbuy = self.atk2.prop.map_or(true, |x| x.2 >= 0.0);
            if buy != pbuy && self.atk2.prop_px.map_or(false, |p0| if pbuy { p <= p0 } else { p >= p0 }) && self.book.by_oid.contains_key(&PROP_OID) {
                if self.atk2.prop_cap.is_some() {
                    // HL rejects a post-only order that would cross: the attacker's bid is at or above this ask
                    self.atk2.prop_alo_rejected += 1;
                    if let Some(t) = self.trig.as_mut() { t.parent_cancelled(oid); }
                    return;
                }
                let (fills, rem, _) = self.book.match_order_caps(buy, p, s, u, &self.pos, None);
                for (m, mu, px, f) in fills { if let Some(t) = self.trig.as_mut() { t.parent_filled(m); } self.last_px = Some(px); self.emit(u, mu, buy, px, f); }
                if rem == 0 { return; }
                s = rem;
            }
            if self.book.would_cross(buy, p) {
                self.tick("alo_accepted_but_sim_crosses", false, h);
                self.prune(!buy, p + if buy { 1 } else { -1 }, "alo_accepted");
            }
            self.book.rest_ro(oid, u, buy, p, s, cl, ro);
            return;
        }
        let rem = match self.mode {
            Match::TapeWalk => self.tape_walk(oid, u, buy, p, s, h),
            Match::Engine => {
                // a reduce-only taker only fills what reduces its position (nothing at all on the wrong side)
                let mut s_eff = s;
                if ro {
                    let q = self.pos.get(&u).copied().unwrap_or(0);
                    let room = if buy { (-q).max(0) } else { q.max(0) };
                    if room < s { if room == 0 { self.ro_rejected += 1 } else { self.ro_capped += 1 } }
                    s_eff = s.min(room);
                }
                let cap = self.margin_caps.get(&oid).copied();
                if cap.is_some() { self.margin_capped += 1; }
                let (fills, rem0, roc) = self.book.match_order_caps(buy, p, s_eff, u, &self.pos, cap);
                self.ro_maker_cancel += roc;
                let rem = rem0 + (s - s_eff);
                for (m, mu, px, f) in fills {
                    if let Some(t) = self.trig.as_mut() { t.parent_filled(m); }
                    *self.sim_tr.entry((oid, m)).or_default() += f;
                    self.last_px = Some(px);
                    self.emit(u, mu, buy, px, f);
                }
                rem
            }
        };
        if filled >= 0 {
            self.tick("filled_size", ((s - rem) - filled).abs() <= 1, h);
        }
        if rem < s {
            if let Some(t) = self.trig.as_mut() { t.parent_filled(oid); }
        }
        if rem > 0 && tif == 1 {
            if self.mode == Match::TapeWalk && self.book.would_cross(buy, p) {
                self.tick("gtc_remainder_cancelled_at_match", true, h);
            } else {
                self.book.rest_ro(oid, u, buy, p, rem, cl, ro);
            }
        }
    }

    /// An isolated account's taker order does not fill beyond the account's bankruptcy price e - m/q (the price at which
    /// its margin is gone): the whale's 37,577-share stop stopped at 305.77, its bankruptcy price 305.79. Invariant under
    /// reduces with the proportional margin release, so it holds through the order.
    fn bk_limit(a: Option<&Acc>, buy: bool, px: Px) -> Px {
        match a {
            Some(a) if (a.iso == Some(true) || a.cross_m) && a.q != 0.0 && ((a.q > 0.0) != buy) => {
                let bk = a.e - a.m.unwrap_or(0.0) / a.q;
                if buy { px.min((bk * 1e6).floor() as Px) } else { px.max((bk * 1e6).ceil() as Px) }
            }
            _ => px,
        }
    }

    fn drain_fills(&mut self) {
        if let Some(t) = self.trig.as_mut() {
            for o in self.book.filled_log.drain(..) { t.parent_filled(o); }
        }
    }

    /// PM_DIAG: compare what pure price-time matching would do on the current book with the real fills of this taker,
    /// maker by maker (real fill order within a taker is not the matching order). One row per maker where they differ,
    /// one row with maker -1 for an exact taker.
    #[allow(clippy::too_many_arguments)]
    fn pm_compare(&mut self, oid: Oid, u: Uid, buy: bool, p: Px, s: Sz, h: i64, real: &[(Oid, Sz, Px, Uid)]) {
        // the engine's limit for this taker (the whale's 20:03 stop was dry-matched through $298 with HL stopping at $305.77)
        let p = self.diag_px.take().unwrap_or(p);
        let (sim, _) = self.book.dry_match(buy, p, s, u);
        let mut rm: AHashMap<Oid, (Sz, Px, Uid)> = AHashMap::new();
        for &(m, z, px, mu) in real { let e = rm.entry(m).or_insert((0, px, mu)); e.0 += z; }
        let mut sm: AHashMap<Oid, (Sz, Px, Uid, usize)> = AHashMap::new();
        for (i, &(m, mu, px, z)) in sim.iter().enumerate() { let e = sm.entry(m).or_insert((0, px, mu, i)); e.0 += z; }
        let mut rows = Vec::new();
        let mut keys: Vec<Oid> = rm.keys().chain(sm.keys()).copied().collect();
        keys.sort(); keys.dedup();
        for m in keys {
            let r = rm.get(&m).copied();
            let q = sm.get(&m).copied();
            if r.map(|x| x.0) == q.map(|x| x.0) { continue; }
            let (px, mu) = r.map(|x| (x.1, x.2)).or(q.map(|x| (x.1, x.2))).unwrap();
            let k = self.book.by_oid.get(&m).copied();
            let (bsz, inbook) = k.map_or((0, false), |k| (self.book.slab[k as usize].sz, true));
            rows.push(format!("{oid},{u},{h},{buy},{p},{s},{m},{mu},{px},{},{},{inbook},{bsz},{}", r.map_or(0, |x| x.0), q.map_or(0, |x| x.0), q.map_or(-1, |x| x.3 as i64)));
        }
        if rows.is_empty() { rows.push(format!("{oid},{u},{h},{buy},{p},{s},-1,0,0,0,0,false,0,-1")); }
        // queue discipline: at each level the real fills touched, the queue (our order) and which ones real filled
        if let Some(qd) = self.qdiag.as_mut() {
            let mut lv: AHashMap<Px, Vec<Oid>> = AHashMap::new();
            for (m, (_, px, _)) in &rm { lv.entry(*px).or_default().push(*m); }
            for (px, filled) in lv {
                let q = self.book.level_orders(!buy, px);
                if q.len() < 2 { continue; }
                let fs: AHashSet<Oid> = filled.iter().copied().collect();
                let pat: String = q.iter().map(|&k| { let o = &self.book.slab[k as usize]; if o.user == u { 's' } else if fs.contains(&o.oid) { 'F' } else { '.' } }).collect();
                let ids: Vec<String> = q.iter().map(|&k| self.book.slab[k as usize].oid.to_string()).collect();
                if pat.contains('.') && pat.contains('F') { qd.push(format!("{oid},{h},{px},{pat},{}", ids.join(";"))); }
            }
        }
        if let Some(v) = self.pm_diag.as_mut() { v.extend(rows); }
    }

    /// Fire the live triggers whose condition holds at this update's mark, as orders of their own. Size 0 = the whole
    /// position; reduce-only orders are capped at the position and dropped when it is flat or on the same side
    /// (`pos` = signed position from the clearing, None without one: then size 0 takes the real filled size).
    fn fire_triggers(&mut self, h: i64, mark: Px, pos: impl Fn(Uid) -> Option<f64>, lim: impl Fn(Uid, bool, Px) -> Px, free: impl Fn(Uid, f64) -> Option<(f64, f64, f64)>) {
        let due = self.trig.as_mut().unwrap().due(mark, h);
        let engine = self.mode == Match::Engine;
        // sizes first: HL executes the triggered orders of an update smallest first (GOOGL: 839 / 839 ordered pairs)
        let mut jobs: Vec<(Sz, Trig, Option<i64>)> = due.into_iter().map(|t| {
            // the clearing's position when it has one (ENDO=0: the replayed real position; ENDO=1: the simulated one), else
            // the book's running position: a whole-position trigger sized from the matching-based position fired 8.056
            // shares short on GOOGL (0x736850ee, 4,171.086 vs 4,179.142) and left HL's last 4 fills to other makers
            let qc = pos(t.u).map(|q| (q * 1e6).round() as i64);
            let q = if engine { Some(qc.unwrap_or_else(|| self.pos.get(&t.u).copied().unwrap_or(0))) } else { qc };
            let mut sz = if t.sz > 0 { t.sz } else { q.map_or(self.trig_real.get(&t.oid).map_or(0, |r| r.1), |q| q.abs()) };
            if t.reduce_only() {
                if let Some(q) = q {
                    let closes = (q > 0 && !t.buy) || (q < 0 && t.buy);
                    sz = if closes { sz.min(q.abs()) } else { 0 };
                }
            }
            (sz, t, q)
        }).collect();
        jobs.sort_by_key(|j| (j.0, j.1.oid));
        for (sz, t, q) in jobs {
            if sz <= 0 {
                self.trig.as_mut().unwrap().dropped_reduce += 1;
                self.trig.as_mut().unwrap().log.push((t, h, mark, q.unwrap_or(i64::MIN), 0, -1));
                continue;
            }
            // initial margin at trigger time (accounts with modelled cross collateral): HL rejects the whole triggered
            // order when its opening part needs more than the free collateral (AMZN: a $28k account's 1,000-share
            // take-profits never filled although the mark crossed them)
            if self.trig_im {
                if let Some((avail, q, lev)) = free(t.u, mark as f64 / 1e6) {
                    let closes = if (q > 0.0) != t.buy { q.abs().min(sz as f64 / 1e6) } else { 0.0 };
                    let open = sz as f64 / 1e6 - closes;
                    if open > 0.0 && open * (t.px as f64 / 1e6) / lev > avail {
                        self.trig_im_rejected += 1;
                        self.trig.as_mut().unwrap().log.push((t, h, mark, (q * 1e6).round() as i64, 0, -2));
                        continue;
                    }
                }
            }
            // sanity cap: an opening notional no account could margin is rejected
            if self.order_cap_x > 0.0 && self.max_lev > 0.0 && !self.acc_av.is_empty() {
                let qv = q.unwrap_or(0);
                let closes = if qv != 0 && (qv > 0) != t.buy { qv.abs().min(sz) } else { 0 };
                let open_ntl = (sz - closes) as f64 / 1e6 * t.px as f64 / 1e6;
                let av = self.acc_av.get(&t.u).copied().unwrap_or(0.0).max(1000.0);
                if open_ntl > self.order_cap_x * self.max_lev * av {
                    self.trig_cap_rejected += 1;
                    self.trig.as_mut().unwrap().log.push((t, h, mark, q.unwrap_or(i64::MIN), 0, -3));
                    continue;
                }
            }
            let before = self.book.by_oid.contains_key(&t.oid);
            let px = if engine && t.tif() == 2 { lim(t.u, t.buy, t.px) } else { t.px };
            if self.pm_diag.is_some() && !engine && t.tif() == 2 { self.diag_px = Some(lim(t.u, t.buy, t.px)); }
            self.place(t.oid, t.u, t.buy, px, sz, t.tif(), t.cl, -1, h, t.reduce_only());
            self.diag_px = None;
            let rested = !before && self.book.by_oid.contains_key(&t.oid);
            self.trig.as_mut().unwrap().log.push((t, h, mark, q.unwrap_or(i64::MIN), sz, rested as i64));
        }
    }

    pub fn run(&mut self, dir: &str) {
        self.run_with(dir, None);
    }

    pub fn run_with(&mut self, dir: &str, mut clr: Option<&mut Clearing>) {
        let mut cur_h: Option<i64> = None;
        let mut n = 0u64;
        self.book.log_fills = self.trig.is_some();
        for ev in EventMerge::open(dir) {
            n += 1;
            self.drain_fills();
            let hh = ev.h;
            if cur_h != Some(hh) {
                if let Some(c) = cur_h {
                    self.end_block(c, &mut clr);
                    for g in c + 1..hh {
                        self.start_block(g, clr.as_deref_mut());
                        self.end_block(g, &mut clr);
                    }
                    let (t, mid) = (self.ms(c), self.mid());
                    if let Some(r) = self.relayer.as_mut() { r.book(t, mid); }
                    if let Some(o) = self.own.as_mut() { o.sample(t, &self.book); }
                }
                cur_h = Some(hh);
                self.start_block(hh, clr.as_deref_mut());
            }
            let uu = ev.u;
            // ATTACK_FREEZE: nobody touches the book. No recorded order, modify or cancel is applied in the window; resting
            // orders stay where they are, and only the engine's own liquidations and fired triggers trade against them
            if ev.k != 5 && self.atk2.frozen(self.book.now_ms) { self.atk2.frozen_n += 1; continue; }
            match ev.k {
                0 => {
                    let o = ev.oid;
                    let mut removed = o >= 0 && self.book.remove(o);
                    if let Some(t) = self.trig.as_mut() {
                        removed |= o >= 0 && t.remove(o);
                        if ev.x == 1 { t.parent_cancelled(o); }
                    }
                    let real_ok = ev.x == 1;
                    self.tick("cancel_status", removed == real_ok || (!real_ok && !removed), hh);
                }
                1 => {
                    if let Some(&o) = self.book.by_cloid.get(&(uu, ev.cl)) {
                        self.book.remove(o);
                        if let Some(t) = self.trig.as_mut() { t.parent_cancelled(o); }
                    } else if let Some(t) = self.trig.as_mut() {
                        t.remove_cloid(uu, ev.cl);
                    }
                }
                2 => {
                    let tm = ev.x;
                    if tm < 0 {
                        self.sched.remove(&uu);
                    } else {
                        self.sched.insert(uu, tm);
                        self.sheap.push(Reverse((tm, uu)));
                    }
                }
                5 => self.on_update(&ev, hh, &mut clr),
                _ => {
                    let (t, s, oin, oincl) = (ev.ty, ev.st, ev.oid_in, ev.oid_in_cl);
                    let remove_in = |bk: &mut Book| {
                        if oin >= 0 {
                            bk.remove(oin);
                        } else if oincl != 0 {
                            if let Some(&o2) = bk.by_cloid.get(&(uu, oincl)) {
                                bk.remove(o2);
                            }
                        }
                    };
                    if ev.trg {
                        if (t == 1 || t == 2) && oin >= 0 {
                            self.book.remove(oin);
                            // an expired modify (7) leaves the original trigger in place
                            if s != 7 { if let Some(tb) = self.trig.as_mut() { tb.remove(oin); } }
                        } else if (t == 1 || t == 2) && oincl != 0 && s != 7 {
                            // modify by cloid: the original trigger is replaced (AMZN: a bot's 1,000-share triggers,
                            // modified then cancelled by cloid, otherwise stayed live and fired)
                            if let Some(tb) = self.trig.as_mut() { tb.remove_cloid(uu, oincl); }
                        }
                        if let Some(tb) = self.trig.as_mut() {
                            // placed: order with a status (0), modify ok (5), batchModify ok (0)
                            if (t == 0 && s == 0) || (t == 1 && s == 5) || (t == 2 && s == 0) {
                                tb.add(Trig { oid: ev.oid, u: uu, buy: ev.buy, px: ev.px, sz: ev.sz, tpx: ev.e_bid, flags: ev.e_ask,
                                              parent: ev.x, cl: ev.cl, active: ev.e_ask & crate::triggers::F_WAIT_FILL == 0 });
                            }
                        }
                        continue;
                    }
                    if (t == 1 || t == 2) && oin < 0 && oincl != 0 && s != 7 {
                        if let Some(tb) = self.trig.as_mut() { tb.remove_cloid(uu, oincl); }
                    }
                    if (t == 1 || t == 2) && oin >= 0 {
                        if let Some(tb) = self.trig.as_mut() {
                            tb.remove(oin);
                            // normalTpsl children follow a modified parent; a failed modify cancels it with them
                            match s { 6 => tb.parent_cancelled(oin), 7 => {}, _ => tb.reparent(oin, ev.oid) }
                        }
                    }
                    if t == 1 || t == 2 {
                        if s == 6 {
                            remove_in(&mut self.book);
                            continue;
                        }
                        if s == 7 {
                            continue;
                        }
                        remove_in(&mut self.book);
                    }
                    match s {
                        1 | 4 => continue,
                        2 => {
                            let crosses = self.book.would_cross(ev.buy, ev.px);
                            self.tick("alo_reject_sim_crosses", crosses, hh);
                            let (rb, ra) = (ev.e_bid, ev.e_ask);
                            if rb >= 0 && ra >= 0 {
                                let exact = self.book.best_bid() == Some(rb) && self.book.best_ask() == Some(ra);
                                self.tick("echo_bbo_exact", exact, hh);
                                self.prune(true, rb, "echo");
                                self.prune(false, ra, "echo");
                            }
                            continue;
                        }
                        3 => {
                            let crosses = self.book.would_cross(ev.buy, ev.px);
                            self.tick("ioc_nomatch_sim_agrees", !crosses, hh);
                            continue;
                        }
                        _ => {}
                    }
                    let px = if self.mode == Match::Engine && (ev.tif == 2 || ev.tif == 3) { clr.as_deref().map_or(ev.px, |c| Self::bk_limit(c.acc.get(&uu), ev.buy, ev.px)) } else { ev.px };
                    if self.pm_diag.is_some() && self.mode != Match::Engine && (ev.tif == 2 || ev.tif == 3) {
                        self.diag_px = clr.as_deref().map(|c| Self::bk_limit(c.acc.get(&uu), ev.buy, ev.px));
                    }
                    self.place(ev.oid, uu, ev.buy, px, ev.sz, ev.tif, ev.cl, ev.filled, hh, ev.ro);
                    self.diag_px = None;
                }
            }
        }
        if let Some(c) = cur_h {
            self.end_block(c, &mut clr);
        }
        if let Some(c) = clr.as_deref_mut() {
            self.book_prop_fills(c);
            c.finish();
            if c.rules.adl_backstop {
                let real: f64 = c.real_takeovers.iter().map(|x| x.2 * x.3).sum();
                println!("ADL (isolated-only market, backstop = auto-deleveraging): sim ${:.0}  real ${:.0}  events sim {} ext {}", self.adl_ntl, real, c.sim_takeovers.len(), c.ext_takeovers.len());
            }
            if let Some(cap) = self.atk2.cap {
                for (u, name) in [(SWEEP_U, "sweeper"), (WALL_U, "ask wall"), (WASH_A, "wash A"), (WASH_B, "wash B")] {
                    if let Some(a) = c.acc.get(&u) {
                        let tk = c.sim_takeovers.iter().filter(|t| t.u == u).count();
                        let rounds: f64 = c.sim_rounds.iter().filter(|r| r.u == u).map(|r| r.filled).sum();
                        let eq = a.m.unwrap_or(0.0) + (c.mark - a.e) * a.q;
                        println!("ATTACKER {name}: capital ${cap:.0} | end position {:.1} equity at last mark ${eq:.0} | liquidated {rounds:.1} shares, taken over {tk}", a.q);
                    }
                }
                if self.atk2.wash_done != (0.0, 0.0) { println!("WASH FAITHFUL: {:.1} shares traded between the attacker's accounts, {:.1} bought from the real book", self.atk2.wash_done.0, self.atk2.wash_done.1); }
            }
            if let (Some(cap), Some(a)) = (self.atk2.prop_cap, c.acc.get(&PROP_U)) {
                let tk = c.sim_takeovers.iter().filter(|t| t.u == PROP_U).count();
                let rounds: f64 = c.sim_rounds.iter().filter(|r| r.u == PROP_U).map(|r| r.filled).sum();
                let eq = a.m.unwrap_or(0.0) + (c.mark - a.e) * a.q;
                println!("PROP ACCOUNT: capital ${cap:.0} | end position {:.1} equity at last mark ${eq:.0} | liquidated {rounds:.1} shares, taken over {tk} | post-only asks rejected {}", a.q, self.atk2.prop_alo_rejected);
            }
        }
        self.report_run(n);
    }

    /// What the replay prints and writes once the last event is in: the counters, the relayer's and the triggers'
    /// own reports, and the output files the runners ask for by environment variable.
    fn report_run(&mut self, n: u64) {
        eprintln!("events {n}");
        if let (Ok(f), Some(v)) = (std::env::var("PM_DIAG"), self.pm_diag.as_ref()) { std::fs::write(f, v.join("\n")).unwrap(); }
        if let (Ok(f), Some(v)) = (std::env::var("QUEUE_DIAG"), self.qdiag.as_ref()) { std::fs::write(f, v.join("\n")).unwrap(); }
        if let Ok(f) = std::env::var("VETO_OUT") {
            let mut w = String::from("m_oid,veto_h\n");
            for (o, h) in &self.vetoes { w += &format!("{o},{h}\n"); }
            std::fs::write(f, w).unwrap();
            println!("silent cancels vetoed by L2 snapshots: {}", self.vetoes.len());
        }
        if !self.silent.is_empty() || self.silent_n > 0 { println!("silent cancels applied: {}", self.silent_n); }
        if self.mode == Match::Engine {
            println!("reduce-only: takers capped {}  rejected {}  makers cancelled at match {} | margin-capped opening takers {} | triggers rejected for initial margin {} | over the sanity cap {}", self.ro_capped, self.ro_rejected, self.ro_maker_cancel, self.margin_capped, self.trig_im_rejected, self.trig_cap_rejected);
        }
        self.dump_sim_tr();
        if let Some(r) = self.relayer.as_ref() { r.report(); }
        if let Some(t) = self.trig.as_ref() { self.trig_report(t); }
        if let (Ok(f), Some(t)) = (std::env::var("TRIG_OUT"), self.trig.as_ref()) {
            let mut w = String::from("oid,u,h,buy,px,sz,tpx,flags,parent,mark,pos,placed_sz,rested,real_h,real_sz\n");
            for (x, h, mk, q, psz, rested) in &t.log {
                let (rh, rs) = self.trig_real.get(&x.oid).copied().unwrap_or((-1, 0));
                w += &format!("{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}\n", x.oid, x.u, h, x.buy, x.px, x.sz, x.tpx, x.flags, x.parent, mk,
                              if *q == i64::MIN { String::new() } else { q.to_string() }, psz, rested, rh, rs);
            }
            std::fs::write(f, w).unwrap();
        }
        if let (Ok(f), Some((_, w))) = (std::env::var("DEPTH_OUT"), self.depth.as_ref()) { std::fs::write(f, w).unwrap(); }
        if let (Ok(f), Some(a)) = (std::env::var("ATTACK_OUT"), self.attack.as_ref()) { std::fs::write(f, &a.2).unwrap(); }
        for l in &self.atk2.log { println!("ATTACK: {l}"); }
        if self.atk2.still.is_some() { println!("ATTACK: book frozen, {} recorded book actions dropped", self.atk2.frozen_n); }
        if self.atk2.prop.is_some() { println!("PROP: price {:.3} | bought {:.1} shares for ${:.0} (avg {:.3}) | peak position {:.1}", self.atk2.prop_px.unwrap_or(0) as f64 / 1e6, self.atk2.prop_q, -self.atk2.prop_cash, if self.atk2.prop_q != 0.0 { -self.atk2.prop_cash / self.atk2.prop_q } else { 0.0 }, self.atk2.prop_max_q); }
        if let Some(o) = self.own.as_ref() { println!("OWN MARK mode {}: updates {} | steps limited (B) {} | confirmed by ext (C) / no trades (ET) {} | V peak ${:.0} | band held (P4) {} | hold expired {} | hold starts blocked {} | divergence holds {} | steps skipped {} | wash ${:.0}", o.mode, o.stats[0], o.stats[1], o.stats[2], o.v_peak, o.gate_held, o.hold_expired, o.trig_blocked, o.diverge_starts, o.steps_skipped, o.wash_ntl); }
        if let Ok(f) = std::env::var("ORC_OUT") {
            let mut w = String::from("h,ms,m1,m2,ext,lag,bid,ask,last\n");
            let o = |x: Option<Px>| x.map_or(String::new(), |v| v.to_string());
            for r in &self.orc {
                w += &format!("{},{},{},{},{},{},{},{},{}\n", r.h, r.ms, r.m1, r.m2, r.ext, r.lag, o(r.bid), o(r.ask), o(r.last));
            }
            std::fs::write(f, w).unwrap();
        }
    }

    /// A relayer update (event kind 5): the published mark and oracle for this block, then the liquidations,
    /// takeovers and ADL the new mark calls for. The largest step of the replay, kept out of the event loop.
    fn on_update(&mut self, ev: &Row, hh: i64, clr: &mut Option<&mut Clearing>) {
        let rec = self.publish(ev, hh, clr);
        if let Some((next, w)) = self.depth.as_mut() {
            if ev.filled >= *next {
                *next = ev.filled + 60_000;
                if let (Some(b), Some(a)) = (self.book.best_bid(), self.book.best_ask()) {
                    let mid = (b + a) as f64 / 2e6;
                    for (buy, side) in [(true, "bid"), (false, "ask")] {
                        let lv = self.book.levels(buy, 5000);
                        for d in [10.0, 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0] {
                            let lim = mid * (1.0 + if buy { -d } else { d } / 1e4);
                            let ntl: f64 = lv.iter().map(|&(p, z)| (p as f64 / 1e6, z as f64 / 1e6))
                                .filter(|&(p, _)| if buy { p >= lim } else { p <= lim }).map(|(p, z)| p * z).sum();
                            w.push_str(&format!("{hh},{},{mid},{side},{d},{ntl:.0}\n", ev.filled));
                        }
                    }
                }
            }
        }
        // one definition of the mark for triggers and for liquidations (clearing::mark_of): with one side
        // of the book empty the lone quote stands for the book price (ONE_SIDED, default since 2026-11-11)
        let mark_i = mark_of(&rec).map(|m| (m * 1e6).round() as Px);
        if clr.is_none() && self.trig.is_some() {
            if let Some(mk) = mark_i { self.fire_triggers(hh, mk, |_| None, |_, _, p| p, |_, _| None); }
        }
        // the liquidation engine runs right at the relayer update, with the new mark (orders later in
        // the block are not in the book yet: the whale's round 2 never met a bid placed later in its block)
        if let (Some(c), Some(mark)) = (clr.as_deref_mut(), mark_of(&rec)) {
            c.advance(hh, 1);
            self.book_prop_fills(c);
            let b = std::mem::take(&mut self.bus);
            for f in &b { c.apply_fill(f); }
            let ms = self.ms(hh);
            let mut others: Vec<(u32, i64, i64, i64, u32, bool)> = self.inject.get(&hh).map(|v| v.iter()
                .filter(|j| j.kind == 1 && !(c.engine_handles(j.t_u) || c.sim_handled(j.t_u)))
                .map(|j| (j.t_u, j.m_oid, j.sz, j.px, j.m_u, j.t_buy)).collect()).unwrap_or_default();
            others.sort_by_key(|x| x.0);
            // triggered stop orders fire on the same mark update: TRIG_POS=before|after|end (end = with
            // the other engine takers at the end of the block)
            // triggers fill before this block's other takers (the position they reduce is the one the
            // clearing sees at the block start)
            let mut trig_fills: Vec<Inj> = vec![];
            {
                if let Some(v) = self.inject.get_mut(&hh) {
                    trig_fills = v.iter().filter(|j| j.kind == 0 && j.t_trig).copied().collect();
                    v.retain(|j| !(j.kind == 0 && j.t_trig));
                }
            }
            // simulated triggers fire here, on positions up to date, before the liquidations
            if let (true, Some(mk)) = (self.trig.is_some(), mark_i) {
                // endogenous accounts only: replayed accounts already hold this block's real fills
                let endo = c.endogenous;
                let engine_mode = self.mode == Match::Engine;
                let cc: &Clearing = c;
                self.fire_triggers(hh, mk, |u| if endo { cc.acc.get(&u).map(|a| a.q) } else if engine_mode { cc.q_block_start(u, hh) } else { None }, |u, b, p| Self::bk_limit(cc.acc.get(&u), b, p), |u, mk| cc.free_collateral(u, mk));
                let b = std::mem::take(&mut self.bus);
                for f in &b { c.apply_fill(f); }
            }
            for j in &trig_fills {
                if self.book.fill_maker(j.m_oid, j.sz) { self.last_px = Some(j.px); }
                if let Some(o) = self.own.as_mut() { o.trade(ms, j.px as f64 / 1e6, j.sz as f64 / 1e6); }
                if c.endogenous { c.apply_fill(&Fill { taker: j.t_u, maker: j.m_u, taker_buy: j.t_buy, px: j.px as f64 / 1e6, sz: j.sz as f64 / 1e6, taker_fee_rate: None }); }
            }
            c.vault_q = self.vault.q;
            c.ext = rec.ext as f64 / 1e6;
            c.liquidate(hh, ms, mark, &mut self.book, &mut self.last_px, &others);
            for (px, z) in std::mem::take(&mut c.prints) { if let Some(o) = self.own.as_mut() { o.trade_f(ms, px, z, true); } }
            c.oracle = rec.m1 as f64 / 1e6;
            self.drain_fills();
            self.sync_clearing(c);
            // vault: inherit this update's takeovers, then (policy mode) send its unwind IOC
            let n0 = self.vault_seen;
            self.vault.now_h = hh; self.vault.kind = 0;
            for t in &c.sim_takeovers[n0..] {
                // the position leaves the trader: its resting reduce-only orders are no longer backed
                let qi = (t.q * 1e6).round() as i64;
                *self.pos.entry(t.u).or_default() -= qi;
                if c.rules.adl_backstop { self.adl_ntl += t.px * t.q.abs(); continue; }   // noCross: ADL, not the vault
                *self.pos.entry(c.vault_uid).or_default() += qi;
                self.vault.trade(t.q > 0.0, t.px, t.q.abs());
                self.vault.taken_ntl += t.px * t.q.abs();
            }
            self.vault_seen = c.sim_takeovers.len();
            self.n_updates += 1;
            self.vault.kind = 1;
            if !self.vp.replay && self.vault.q != 0.0 && self.n_updates % self.vp.every == 0 {
                let sell = self.vault.q > 0.0;
                // HL minimum order value ($10): small inventories are closed with min-size orders
                // on the size grid: the policy size floored, the $10 minimum rounded up, capped at the inventory
                let lot = c.lot;
                let q_i = (self.vault.q.abs() * 1e6).round() as i64;
                let req_i = ((self.vp.frac * self.vault.q.abs() * 1e6) as i64 / lot * lot)
                    .max(((self.vp.min_ntl / mark * 1e6).ceil() as i64 + lot - 1) / lot * lot).min(q_i);
                let req = req_i as f64 / 1e6;
                let lim = ((mark * if sell { 1.0 - self.vp.limit } else { 1.0 + self.vp.limit }) * 1e6).round() as i64;
                let lim = if sell { lim.max(0) } else { lim };
                if req_i > 0 {
                    let (fills, _) = self.book.match_order_u(!sell, lim, req_i, c.vault_uid);
                    for &(_, mu, _, fsz) in &fills { self.move_pos(c.vault_uid, mu, !sell, fsz); }
                    let mut filled = 0.0;
                    for (_, mu, fpx, fsz) in fills {
                        if c.endogenous {
                            c.apply_fill(&Fill { taker: c.vault_uid, maker: mu, taker_buy: !sell, px: fpx as f64 / 1e6, sz: fsz as f64 / 1e6, taker_fee_rate: None });
                        }
                        let (p, z) = (fpx as f64 / 1e6, fsz as f64 / 1e6);
                        self.vault.trade(!sell, p, z);
                        self.vault.unwound_ntl += p * z;
                        self.vault.fees += p * z * self.vault_fee_rate;
                        if let Some(o) = self.own.as_mut() { o.trade_f(ms, p, z, true); }
                        filled += z;
                        self.last_px = Some(fpx);
                    }
                    self.vault_orders.push((hh, req, filled));
                }
                // VAULT_FAIR=1: then take every resting order at or better than the external price (sell: bids
                // >= E; buy: asks <= E), never below fair value
                let ext = c.ext;
                if self.vp.fair && self.vault.q != 0.0 && ext > 0.0 {
                    let sell = self.vault.q > 0.0;
                    let q_i = ((self.vault.q.abs() * 1e6).round() as i64) / lot * lot;
                    let lim = if sell { (ext * 1e6).ceil() as i64 } else { (ext * 1e6).floor() as i64 };
                    if q_i > 0 {
                        let (fills, _) = self.book.match_order_u(!sell, lim, q_i, c.vault_uid);
                        for &(_, mu, _, fsz) in &fills { self.move_pos(c.vault_uid, mu, !sell, fsz); }
                        for (_, mu, fpx, fsz) in fills {
                            if c.endogenous {
                                c.apply_fill(&Fill { taker: c.vault_uid, maker: mu, taker_buy: !sell, px: fpx as f64 / 1e6, sz: fsz as f64 / 1e6, taker_fee_rate: None });
                            }
                            let (p, z) = (fpx as f64 / 1e6, fsz as f64 / 1e6);
                            self.vault.trade(!sell, p, z);
                            self.vault.unwound_ntl += p * z;
                            self.vault.fees += p * z * self.vault_fee_rate;
                            if let Some(o) = self.own.as_mut() { o.trade_f(ms, p, z, true); }
                            self.last_px = Some(fpx);
                            self.vault_fair_ntl += p * z;
                        }
                    }
                }
            }
            self.liq_done_h = Some(hh);
        }
    }

    /// What trade.xyz's relayer publishes at this update: the two values (m1, m2), the attacks and own-mark rules that
    /// act on them, and the per-update clamp of the mark they feed. Returns the record the rest of the update reads.
    fn publish(&mut self, ev: &Row, hh: i64, clr: &mut Option<&mut Clearing>) -> OrcRec {
        let (mut m1, mut m2) = (ev.x, ev.px);
        // EXT_SPIKE: the external price the relayer reads is off by frac during [ms, ms + secs)
        let mut ext_px: Px = match self.atk2.spike {
            Some((a, b, f)) if ev.filled >= a && ev.filled < b => ((ev.e_bid as f64) * (1.0 + f)).round() as Px,
            _ => ev.e_bid,
        };
        // EXT_RAMP="ms;ramp_secs;frac;hold_secs": a walking feed, off by frac x min(elapsed / ramp, 1), then back
        if let Some((a, r, f, h)) = self.atk2.ramp {
            if ev.filled >= a && ev.filled < a + r + h {
                let k = ((ev.filled - a) as f64 / r.max(1) as f64).min(1.0);
                ext_px = ((ext_px as f64) * (1.0 + f * k)).round() as Px;
            }
        }
        // EXT_FREEZE="ms;secs": the feed is stuck at its last value before ms for secs
        match self.atk2.freeze {
            Some((a, b)) if ev.filled >= a && ev.filled < b && self.atk2.freeze_px > 0 => ext_px = self.atk2.freeze_px,
            _ => self.atk2.freeze_px = ext_px,
        }
        // EXT_PERSIST: after the scenarios above (a walked or frozen feed is what the rule has to face)
        if let Some((band, w)) = self.atk2.persist {
            let h = &mut self.atk2.persist_hist;
            h.push_back((ev.filled, ext_px));
            while h.len() > 1 && h[0].0 < ev.filled - w { h.pop_front(); }
            let mut v: Vec<Px> = h.iter().map(|x| x.1).collect();
            v.sort_unstable();
            let k = v.len();
            let med = if k % 2 == 1 { v[k / 2] as f64 } else { 0.5 * (v[k / 2 - 1] as f64 + v[k / 2] as f64) };
            let (lo, hi) = ((med * (1.0 - band)).ceil() as Px, (med * (1.0 + band)).floor() as Px);
            if ext_px < lo { ext_px = lo; self.atk2.persist_bound += 1; } else if ext_px > hi { ext_px = hi; self.atk2.persist_bound += 1; }
        }
        let (t, mid) = (self.ms(hh), self.mid());
        let in_win = ev.filled >= self.w0 && ev.filled < self.w1;
        if let Some(r) = self.relayer.as_mut() {
            r.book(t, mid);
            let pm = self.orc.last().and_then(|o| mark_of(o)).map(|m| (m * 1e6).round() as Px);
            (m1, m2) = r.update(ev.filled, ext_px, ev.e_ask as u8, (ev.x, ev.px), in_win, pm);
        }
        if let Some((a, b, fr, ntl)) = self.atk2.wash_own {
            if ev.filled >= a && ev.filled < b {
                let p = *self.atk2.wash_own_px.get_or_insert(((ext_px as f64 * (1.0 + fr)) / 10000.0).round() as Px * 10000);
                let (fb, fa) = self.wash_trade(p, ntl, clr.as_deref_mut());
                self.atk2.wash_done.0 += fa; self.atk2.wash_done.1 += fb;
            }
        }
        // MARK3_PURE=1: with the three-vote mark, the earlier candidate's own-mark rules (its hold on an impossible
        // jump of the external price) do not touch the published inputs: the relayer's values stand
        let pure3 = self.atk2.mark3.is_some() && mark3_pure();
        if self.own.is_some() && !pure3 {
            let loc = match (self.book.best_bid(), self.book.best_ask(), self.last_px) { (Some(b), Some(a), Some(l)) => Some(median3(b, a, l) as f64 / 1e6), _ => None };
            let cap = self.relayer.as_ref().map_or(0.0, |r| r.ext_cap());
            let pm = self.orc.last().and_then(|o| mark_of(o));
            let o = self.own.as_mut().unwrap();
            if let Some((a, b)) = o.update(ev.filled, ext_px as f64 / 1e6, pm, loc, &self.book, cap, clr.as_deref()) {
                (m1, m2) = ((a * 1e6).round() as Px, (b * 1e6).round() as Px);
            }
        }
        if let Some((mode, r)) = self.atk2.mark3 {
            if self.relayer.as_ref().map_or(false, |x| x.last_internal) && mark3_int() {
                // MARK3_INT=1 (pkgm3kSSS): one formula in every regime. When the feed is not live (closed venue,
                // or unchanged for two updates) its vote is the relayer's internal oracle (m1) instead of E; the
                // anchor is NOT restarted, it keeps averaging toward that vote. So a walked-then-held feed
                // (overnight E is unchanged on three updates out of four) cannot reset the anchor to the
                // walked level, and a feed frozen for hours (SKHX) still lets the mark follow xyz's market.
                let v = m1 as f64;
                let a0 = self.atk2.mark3_anchor.unwrap_or(v);
                let a = if mode == 0 { a0 + (v - a0).clamp(-r * a0, r * a0) }
                        else { let dt = (ev.filled - self.atk2.mark3_ms).max(0) as f64 / 1000.0; a0 + (1.0 - (-dt / r).exp()) * (v - a0) };
                let a = ratchet(a, v, &self.orc, ev.filled);
                let (vb, a) = band(&mut self.atk2.mark3_pure, v, a, (ev.filled - self.atk2.mark3_ms).max(0) as f64 / 1000.0, r, self.relayer.as_ref().map_or(0.0, |x| x.ext_cap()));
                self.atk2.mark3_anchor = Some(a);
                self.atk2.mark3_ms = ev.filled;
                if vb != v { m1 = vb.round() as Px; }
                m2 = a.round() as Px;
            } else if self.relayer.as_ref().map_or(false, |x| x.last_internal) {
                // the feed carries no information (closed venue, or unchanged for two updates): its vote drops
                // out and the relayer's internal-oracle inputs stand, as in the lead. The anchor restarts from
                // them, so when the feed returns the mark walks to it at the anchor's pace: no hand-over jump
                self.atk2.mark3_anchor = Some(m2 as f64);
                self.atk2.mark3_ms = ev.filled;
            } else {
                let e = ext_px as f64;
                let a0 = self.atk2.mark3_anchor.unwrap_or(e);
                let a = if mode == 0 { a0 + (e - a0).clamp(-r * a0, r * a0) }
                        else { let dt = (ev.filled - self.atk2.mark3_ms).max(0) as f64 / 1000.0; a0 + (1.0 - (-dt / r).exp()) * (e - a0) };
                let a = ratchet(a, e, &self.orc, ev.filled);
                let (vb, a) = band(&mut self.atk2.mark3_pure, e, a, (ev.filled - self.atk2.mark3_ms).max(0) as f64 / 1000.0, r, self.relayer.as_ref().map_or(0.0, |x| x.ext_cap()));
                self.atk2.mark3_anchor = Some(a);
                self.atk2.mark3_ms = ev.filled;
                m1 = if vb != e { vb.round() as Px } else { ext_px };
                // The anchor is exempt from trade.xyz's discovery bound (decided 2026-11-10): the median always lies
                // between E and A, so the mark is never further from the feed than the feed's own 30 min move, and
                // bounding A inside E(1 +- 1/maxLev) gives the walk back (data/scen/tests_1110d). MARK3_D=1: bound on.
                let d = if mark3_d() { self.relayer.as_ref().map_or(0.0, |r| r.ext_cap()) } else { 0.0 };
                m2 = (if d > 0.0 { a.clamp(e * (1.0 - d), e * (1.0 + d)) } else { a }).round() as Px;
            }
        }
        if let Some((a, b, ntl)) = self.atk2.wash {
            if ev.filled >= a && ev.filled < b {
                if let Some(bb) = self.book.best_bid() {
                    let p = bb + tick_of(bb);
                    if self.book.best_ask().map_or(true, |x| x > p) {
                        if self.atk2.cap.is_some() {
                            let (_, fa) = self.wash_trade(p, ntl, clr.as_deref_mut());
                            self.atk2.wash_done.0 += fa;
                        } else {
                            self.last_px = Some(p);
                            if let Some(o) = self.own.as_mut() { o.trade(ev.filled, p as f64 / 1e6, ntl / (p as f64 / 1e6)); }
                        }
                    }
                }
            }
        }
        if let Some((a, b)) = self.atk2.out {
            if ev.filled >= a && ev.filled < b {
                if ev.filled - a < 10_000 {
                    if let Some(st) = self.atk2.stale { (m1, m2) = st; }
                } else if let (Some(bb), Some(aa), Some(l)) = (self.book.best_bid(), self.book.best_ask(), self.last_px) {
                    let lm = median3(bb, aa, l);
                    (m1, m2) = (lm, lm);
                }
            } else {
                self.atk2.stale = Some((m1, m2));
            }
        }
        let (lo, hi) = match (hl_cap(), self.orc.last().and_then(|o| mark_of(o))) {
            (true, Some(pm)) => {
                let st = self.cap_step as f64;
                (((pm * 0.99 * 1e6 / st).round() * st) as Px, ((pm * 1.01 * 1e6 / st).round() * st) as Px)
            }
            _ => (0, Px::MAX),
        };
        let rec = OrcRec { h: hh, m1, m2, bid: self.book.best_bid(), ask: self.book.best_ask(), last: self.last_px, ms: ev.filled, ext: ext_px, lag: ev.e_ask as u8, lo, hi };
        // gate on the mark itself: same book component, real vs simulated relayer components
        if self.relayer.is_some() && in_win {
            if let (Some(a), Some(b)) = (mark_of(&rec), mark_of(&OrcRec { m1: ev.x, m2: ev.px, ..rec })) {
                self.tick("relayer_mark_exact", (a - b).abs() < 1e-9, hh);
            }
        }
        self.orc.push(rec);
        rec
    }

    /// Gate: simulated firings vs real trigger takers (first real fill block), and fill sizes.
    fn trig_report(&self, t: &TrigBook) {
        for (label, lo, hi) in [("all day", i64::MIN, i64::MAX), ("18:00-22:00", self.w0, self.w1)] {
            let inw = |h: i64| { let m = self.ms(h); m >= lo && m < hi };
            let sim: AHashMap<Oid, i64> = t.fired.iter().filter(|x| inw(x.1)).map(|&(o, h)| (o, h)).collect();
            let real: AHashMap<Oid, i64> = self.trig_real.iter().filter(|x| inw(x.1 .0)).map(|(&o, &(h, _))| (o, h)).collect();
            let both = real.iter().filter(|(o, h)| sim.get(o) == Some(h)).count();
            let other_blk = real.iter().filter(|(o, h)| sim.get(o).map_or(false, |s| s != *h)).count();
            let real_only = real.keys().filter(|o| !sim.contains_key(o)).count();
            // sim-only firings: market triggers (as taker) that never had a real taker fill
            let sim_only = sim.keys().filter(|o| !real.contains_key(o)).count();
            let (mut rs, mut ss) = (0i64, 0i64);
            for (o, _) in &real {
                rs += self.trig_real[o].1;
                ss += self.sim_tr.iter().filter(|(k, _)| k.0 == *o).map(|(_, v)| *v).sum::<i64>();
            }
            println!("triggers ({label}): real fired as taker {}  sim fired {}  same block {}  other block {}  real only {}  sim only {} | taker size real {:.1} sim {:.1}",
                     real.len(), sim.len(), both, other_blk, real_only, sim_only, rs as f64 / 1e6, ss as f64 / 1e6);
        }
        println!("triggers dropped (reduce-only with no position to reduce): {}", t.dropped_reduce);
        if let Ok(f) = std::env::var("TRIG_FIRED_OUT") {
            let mut w = String::from("h,ms,oid,taker_sz\n");
            for &(o, h) in &t.fired {
                let sz: i64 = self.sim_tr.iter().filter(|(k, _)| k.0 == o).map(|(_, v)| *v).sum();
                w += &format!("{h},{},{o},{}\n", self.ms(h), sz as f64 / 1e6);
            }
            std::fs::write(f, w).unwrap();
        }
        if let Some((a, b)) = self.atk2.trig_win {
            let fired: Vec<Oid> = t.fired.iter().filter(|x| { let m = self.ms(x.1); m >= a && m < b }).map(|x| x.0).collect();
            let sz: i64 = self.sim_tr.iter().filter(|(k, _)| fired.contains(&k.0)).map(|(_, v)| *v).sum();
            println!("TRIG WINDOW: fired {} taker size {:.1}", fired.len(), sz as f64 / 1e6);
        }
    }

    /// SIMTR_OUT: every simulated user-taker fill (taker oid, maker oid, size).
    pub fn dump_sim_tr(&self) {
    }

    pub fn report(&self, dir: &str) {
        // same lines as before the counters were packed: the whole day, then the in-window count under "<name>_win"
        for (name, (y, nn, yw, nw)) in &self.chk.c {
            let line = |k: &str, y: u64, n: u64| println!("  {:36} ok {:9}  bad {:8}  rate {:.4}", k, y, n, y as f64 / ((y + n).max(1)) as f64);
            line(name, *y, *nn);
            if *yw + *nw > 0 { line(&format!("{name}_win"), *yw, *nw); }
        }
        let rf = format!("{dir}/real_fills.arrow");
        let (t, m, s, ms) = (load::<Int64Type>(&rf, "t_oid"), load::<Int64Type>(&rf, "m_oid"), load::<Int64Type>(&rf, "sz"), load::<Int64Type>(&rf, "ms"));
        for (label, lo, hi) in [("all day", i64::MIN, i64::MAX), ("18:00-22:00", self.w0, self.w1)] {
            let mut real: AHashMap<(Oid, Oid), Sz> = AHashMap::new();
            for k in 0..t.len() {
                if ms[k] >= lo && ms[k] < hi {
                    *real.entry((t[k], m[k])).or_default() += s[k];
                }
            }
            let takers: AHashSet<Oid> = real.keys().map(|k| k.0).collect();
            let both: i64 = real.iter().map(|(k, v)| (*v).min(*self.sim_tr.get(k).unwrap_or(&0))).sum();
            let tot_r: i64 = real.values().sum();
            let tot_s: i64 = self.sim_tr.iter().filter(|(k, _)| takers.contains(&k.0)).map(|(_, v)| *v).sum();
            println!("  {label}: real size {:.1}, matched {:.4} of real, sim extra {:.4} of sim", tot_r as f64 / 1e6, both as f64 / tot_r as f64, (tot_s - both) as f64 / (tot_s.max(1)) as f64);
        }
        println!("pruned: {:?}", self.pruned);
        println!("1-min L2 snapshots: {:?}", self.l2c);
    }
}

/// Attack injections beyond the market sweep:
///   ATTACK_PULL="u1,u2;ms;secs": those makers' resting orders are cancelled at ms and their new orders dropped for secs
///   ATTACK_FREEZE="ms;secs": the book stands still: every recorded order, modify and cancel is dropped for secs, so
///                          resting orders stay as they were and the book does not follow the external price
///   RELAYER_OUT="ms;secs": no setOracle for secs: the published inputs stay stale, and after 10 s HyperCore's
///                          fallback makes the mark the local book mark
///   ATTACK_WALL="ms;secs;ntl": a resting ask of ntl one tick above the best bid, re-placed every block
///   ATTACK_WASH="ms;secs;ntl": at every relayer update, a self-trade of ntl one tick above the best bid (own accounts,
///                          inside the spread): a trade print for MARK=own_* and the last price
///   TRIG_WIN="ms0,ms1": report simulated trigger firings (count, taker size) in that window
///   EXT_SPIKE="ms;secs;frac": the external price fed to the relayer is multiplied by (1 + frac) for secs (a bad print)
///   EXT_RAMP="ms;ramp_secs;frac;hold_secs": a walking feed: off by frac x min(elapsed / ramp, 1) for ramp + hold, then back
#[derive(Default)]
pub struct Atk2 {
    pull: Option<(Vec<Uid>, i64, i64)>,
    pull_done: bool,
    still: Option<(i64, i64)>,
    frozen_n: u64,
    out: Option<(i64, i64)>,
    wall: Option<(i64, i64, f64)>,
    wash: Option<(i64, i64, f64)>,
    trig_win: Option<(i64, i64)>,
    spike: Option<(i64, i64, f64)>,
    /// EXT_RAMP: (start ms, ramp ms, frac, hold ms)
    ramp: Option<(i64, i64, f64, i64)>,
    freeze: Option<(i64, i64)>,
    freeze_px: Px,
    /// EXT_PERSIST="band;window_secs": the feed the relayer follows is the external price kept within `band` of its own
    /// median over the last window. A move of up to `band` passes at once; the part beyond it passes once the price has
    /// stayed there for half the window (the median then moves). It uses the external price only: nothing traded or
    /// quoted on xyz can start, extend or end it. (band, window ms), and the window of raw prices.
    /// MARK3="a;r" | "e;tau_s": the three-vote mark (a light test). The relayer's two published inputs become the
    /// external price itself and a slow anchor; Hyperliquid's own book is the third input of its median. When the feed
    /// and xyz's market agree the mark moves at once; when they disagree it moves at the anchor's pace, whichever of
    /// the two is being pushed. Anchor: toward the feed by at most r per update (a), or an average with time constant
    /// tau (e); r = 0 freezes it. (mode, parameter), the anchor and its last update.
    mark3: Option<(u8, f64)>,
    mark3_anchor: Option<f64>,
    /// MARK3_BAND: the plain average of the feed's vote (never ratcheted), the centre of the band
    mark3_pure: Option<f64>,
    mark3_ms: i64,
    persist: Option<(f64, i64)>,
    persist_hist: std::collections::VecDeque<(i64, Px)>,
    pub persist_bound: u64,
    stale: Option<(Px, Px)>,
    pub log: Vec<String>,
    /// ATTACK_PROP="ms;secs;frac;ntl": prop the book. Every block in the window a fresh attacker account sends a buy limit at
    /// P0 = mid at start x (1 + frac) for ntl: it lifts every ask at or below P0 and rests the rest as a bid at P0 (re-placed
    /// each block), so every seller fills against it. Tracks the attacker's position and cash.
    /// frac < 0: the mirror, a sell limit at P0 below the mid (hits every bid at or above P0, rests the rest as an ask).
    prop: Option<(i64, i64, f64, f64)>,
    /// ATTACK_PROP 5th field: the attacker's collateral (USD). Set: the attacker is an ordinary cross account in the clearing
    /// (margin-checked, liquidated, taken over); unset: the old unlimited phantom buyer
    prop_cap: Option<f64>,
    /// ATTACK_CAP: collateral (USD) of each other synthetic attacker (sweeper, ask wall, wash accounts). Set: they are
    /// ordinary cross accounts in the clearing (orders capped by free margin, liquidated and taken over like anyone);
    /// wash prints become real trades between two of them on the book. Unset: the old phantom attackers.
    pub cap: Option<f64>,
    /// WASH (faithful, with ATTACK_CAP): (start ms, end ms, frac above ext, notional per relayer update) and its price
    wash_own: Option<(i64, i64, f64, f64)>,
    wash_own_px: Option<Px>,
    /// faithful wash totals: (shares traded between the attacker's accounts, shares B bought from the real book)
    pub wash_done: (f64, f64),
    /// synthetic attacker fills not yet booked in the clearing: (account, buy, px, sz, as taker)
    prop_fills: Vec<(Uid, bool, f64, f64, bool)>,
    pub prop_alo_rejected: u64,
    prop_px: Option<Px>,
    pub prop_q: f64,
    pub prop_cash: f64,
    pub prop_max_q: f64,
}

impl Atk2 {
    fn from_env() -> Self {
        let parts = |k: &str| std::env::var(k).ok().map(|v| v.split(';').map(|x| x.to_string()).collect::<Vec<_>>());
        let ms = |s: &str| s.parse::<i64>().unwrap();
        let secs = |s: &str| (s.parse::<f64>().unwrap() * 1000.0) as i64;
        Atk2 {
            pull: parts("ATTACK_PULL").map(|p| (p[0].split(',').map(|u| u.parse().unwrap()).collect(), ms(&p[1]), ms(&p[1]) + secs(&p[2]))),
            still: parts("ATTACK_FREEZE").map(|p| (ms(&p[0]), ms(&p[0]) + secs(&p[1]))),
            out: parts("RELAYER_OUT").map(|p| (ms(&p[0]), ms(&p[0]) + secs(&p[1]))),
            wall: parts("ATTACK_WALL").map(|p| (ms(&p[0]), ms(&p[0]) + secs(&p[1]), p[2].parse().unwrap())),
            wash: parts("ATTACK_WASH").map(|p| (ms(&p[0]), ms(&p[0]) + secs(&p[1]), p[2].parse().unwrap())),
            spike: parts("EXT_SPIKE").map(|p| (ms(&p[0]), ms(&p[0]) + secs(&p[1]), p[2].parse().unwrap())),
            freeze: parts("EXT_FREEZE").map(|p| (ms(&p[0]), ms(&p[0]) + secs(&p[1]))),
            ramp: parts("EXT_RAMP").map(|p| (ms(&p[0]), secs(&p[1]), p[2].parse().unwrap(), secs(&p[3]))),
            persist: parts("EXT_PERSIST").map(|p| (p[0].parse().unwrap(), secs(&p[1]))),
            mark3: parts("MARK3").map(|p| (if p[0] == "e" { 1 } else { 0 }, p[1].parse().unwrap())),
            prop: parts("ATTACK_PROP").map(|p| (ms(&p[0]), ms(&p[0]) + secs(&p[1]), p[2].parse().unwrap(), p[3].parse().unwrap())),
            prop_cap: parts("ATTACK_PROP").and_then(|p| p.get(4).map(|x| x.parse().unwrap())), prop_fills: Vec::new(), prop_alo_rejected: 0, cap: std::env::var("ATTACK_CAP").ok().map(|v| v.parse().unwrap()),
            wash_own: std::env::var("ATTACK_CAP").ok().and(std::env::var("WASH").ok()).map(|v| { let x: Vec<f64> = v.split(';').map(|a| a.parse().unwrap()).collect(); (x[0] as i64, x[0] as i64 + (x[1] * 1000.0) as i64, x[2], x[3]) }), wash_own_px: None, wash_done: (0.0, 0.0),
            trig_win: std::env::var("TRIG_WIN").ok().map(|v| { let x: Vec<i64> = v.split(',').map(|a| a.parse().unwrap()).collect(); (x[0], x[1]) }),
            ..Default::default()
        }
    }
    fn frozen(&self, t: i64) -> bool { self.still.map_or(false, |(a, b)| t >= a && t < b) }
    fn pulled(&self, u: Uid, t: i64) -> bool { self.pull.as_ref().map_or(false, |(us, a, b)| t >= *a && t < *b && us.contains(&u)) }
}

fn tick_of(px: Px) -> Px {
    let x = px as f64 / 1e6;
    let d = (4 - x.abs().log10().floor() as i32).max(0);
    (10f64.powi(-d) * 1e6).round() as Px
}

const WALL_OID: Oid = i64::MAX - 77;
const PROP_OID: Oid = i64::MAX - 78;
const PROP_U: Uid = u32::MAX - 9;
const SWEEP_U: Uid = u32::MAX - 7;
const WASH_A: Uid = u32::MAX - 10;   // faithful wash: the account that rests the ask
const WASH_B: Uid = u32::MAX - 11;   // faithful wash: the account that lifts it
const WASH_OID: Oid = i64::MAX - 21;
const WALL_U: Uid = u32::MAX - 8;

/// Own-book marks for out-of-market hours (MARK=own_a|own_b|own_c, from OWN_FROM_MS; before it the relayer as today).
/// All three publish markPxs from the xyz book only, so HyperCore's mark is median(markPx1, markPx2, local book):
///   own_a: markPxs = [impact mid at OWN_N notional, time-averaged over the update interval; trade VWAP over OWN_W_S s]
///   own_b: own_a's mark, but a step may cross at most OWN_L0 notional of liquidation prices (margined accounts, base
///          MM rate) per update, and always moves at least OWN_MIN_STEP toward it: both markPxs = that price
///   own_c: own_a, except when the external price confirms the move (same direction, at least half as far from the
///          previous mark as the instantaneous impact mid): both markPxs = the instantaneous impact mid
///   own_et: markPxs = [ext, P], P = volume-weighted median price of the last OWN_V notional of voluntary trades
///          (liquidation, backstop and vault fills excluded) no older than OWN_TMAX_S s (none: ext), so the mark is
///          median(ext, P, local book): no book input of ours. OWN_VF > 0 scales the window with activity:
///          V = max(OWN_VMIN, OWN_VF x voluntary notional traded in the last 60 s)
///          OWN_SELF=1 (no dollar or age constants): over a horizon H = OWN_H_S (HL's 30 s partial-liquidation
///          cooldown by default), V = max(voluntary volume of the last H, the day's average voluntary volume per H),
///          and the window goes back as far as needed to collect V (no age limit)
/// All keep the external-price cap (discovery bound) and HL's 1% per update.
pub struct OwnMark {
    pub mode: u8,
    pub from_ms: i64,
    n: f64,
    w_ms: i64,
    l0: f64,
    min_step: f64,
    imp: std::collections::VecDeque<(i64, f64)>, // impact mid timeline (from ms, value)
    trades: std::collections::VecDeque<(i64, f64, f64, bool)>, // (ms, px, sz, forced)
    v: f64,
    selfcal: bool,
    h_ms: i64,
    vol_tot: f64,  // voluntary notional since the first trade seen
    vol_t0: i64,
    vf: f64,
    vmin: f64,
    pub v_peak: f64,
    tmax_ms: i64,
    last_upd: i64,
    pub stats: [u64; 3], // updates handled, own_b steps limited, own_c confirmed
    /// P3: centre the discovery bound on the median of the last `anchor_n` external prices (0 = instantaneous ext)
    anchor_n: usize,
    ext_hist: std::collections::VecDeque<f64>,
    /// P4: the bound's centre follows ext only while |ext - P| <= d ext, else it holds its last value
    gate: bool,
    centre_prev: Option<f64>,
    /// OWN_SKIP="a;b": regular hours [a, b) keep today's relayer formula (own mark returns None)
    skip: Option<(i64, i64)>,
    pub gate_held: u64,
    /// WASH="start_ms;secs;frac;ntl": synthetic voluntary prints (attacker wash trades) of `ntl` per relayer update at the
    /// external price at the start x (1 + frac), held fixed, for `secs` seconds. They only enter P (the book is untouched).
    wash: Option<(i64, i64, f64, f64)>,
    wash_px: Option<f64>,
    pub wash_ntl: f64,
    /// OWN_GATE=2: the band holds only if the book's impact mid (OWN_N notional) also disagrees with ext by more than d, on P's side
    gate_book: bool,
    /// OWN_HOLD_S: the band may hold at most this long; then its centre catches up with ext (and may hold again from there)
    hold_ms: i64,
    held_since: Option<i64>,
    hold_step: bool,
    /// OWN_P_EMA_S: the published trade input is a time-based EMA of P with this time constant (trade.xyz's mark EMA: 150 s),
    /// so a push must last minutes to move the mark; the hold decision keeps the raw P
    p_ema_ms: f64,
    /// OWN_ONLY_HOLD=1: publish P4d's inputs only while a hold is active; otherwise the relayer's own (today's formula)
    only_hold: bool,
    p_ema: Option<(i64, f64)>,
    /// OWN_P_EMA_HOLD_RAW=1: during a hold (the feed distrusted) the published trade input is the raw P, not its EMA
    p_ema_hold_raw: bool,
    held_now: bool,
    /// OWN_HOLD_CAP=1: while the band holds, the mark may not go beyond the held centre on the side away from ext
    hold_cap: bool,
    held_side: f64,
    /// centre when the current hold began (kept across OWN_HOLD_STEP steps; cleared when the hold ends)
    hold_r0: Option<f64>,
    /// centre at the last update where ext and the xyz price agreed (|ext - P| <= d ext)
    agree_c: Option<f64>,
    ext_last: f64,
    /// ext changed since the previous update (a live feed; a stuck feed is not capped)
    ext_live: bool,
    ext_change_ms: i64,
    /// OWN_HOLD_TRIG=1: a hold may start only when ext jumped by more than d within the trade window (a bad print) or has
    /// not changed for the whole window (a stuck feed); a gradual, live move never starts one. Once started it continues as P4d.
    hold_trig: bool,
    /// OWN_FROZEN_UPD=n: the feed counts as stuck after n consecutive updates without a change (instead of the 30 s window);
    /// a hold still needs xyz to disagree with it by more than d
    frozen_upd: u32,
    /// OWN_FROZEN_GAP=g: with the feed stuck, a hold starts once xyz disagrees by more than g (fraction; today's clamp 0.005)
    /// instead of d; the book must disagree on the same side by more than g too
    frozen_gap: f64,
    /// OWN_JUMP_GAP=g: after a single-update jump of ext by more than d, a hold starts once xyz disagrees by more than g, and a
    /// hold started by a feed failure (jump or stuck) continues while xyz and the book disagree by more than g
    jump_gap: f64,
    fail_hold: bool,
    unchanged_n: u32,
    /// OWN_HOLD_TRIG=2: the jump must happen between two consecutive updates (a bad print is a step; a real move, even a crash, spreads over several)
    trig_step: bool,
    ext_win: std::collections::VecDeque<(i64, f64)>,
    holding: bool,
    pub trig_blocked: u64,
    pub hold_expired: u64,
    /// OWN_DIVERGE: divergence gap (fraction, 0 = off) and the holds it started
    diverge: f64,
    pub diverge_starts: u64,
    /// OWN_NO_FROZEN=1: a frozen feed never starts a hold (B: the relayer's internal oracle prices a stale E instead)
    no_frozen: bool,
    /// OWN_N_SELF=1: the hold's book checks at max(OWN_N, V) (C); V of the last trade-median call
    n_self: bool,
    v_last: f64,
    /// OWN_STEP_STALE: step toward ext only while xyz's trade price is stale; steps skipped
    step_stale: bool,
    /// 1 = fresh by trade count (dust can keep it fresh), 2 = fresh by volume, 3 = never step
    step_stale_mode: u8,
    pub steps_skipped: u64,
    /// OWN_CLOSED="a;b,a;b": the venue's scheduled closures (ms). A quiet feed there is expected, not a failure: the
    /// frozen trigger does not fire inside them (a jump still can). Written by sim/prep/closed_windows.py from data/venue_hours.json
    closed: Vec<(i64, i64)>,
}

impl OwnMark {
    fn from_env() -> Option<Self> {
        let v = std::env::var("MARK").ok()?;
        let mode = match v.as_str() { "own_a" => 0, "own_b" => 1, "own_c" => 2, "own_et" => 3,
            // an unknown design must stop: falling back to today's formula would report as the design that was asked for
            other => panic!("unknown MARK={other}: own_a | own_b | own_c | own_et, or unset for today's formula"), };
        let f = |k: &str, d: f64| std::env::var(k).map_or(d, |v| v.parse().unwrap_or_else(|_| panic!("{k}: cannot read {v:?} as a number")));
        Some(OwnMark { mode, from_ms: f("OWN_FROM_MS", 0.0) as i64, n: f("OWN_N", 100_000.0), w_ms: (f("OWN_W_S", 10.0) * 1000.0) as i64,
            l0: f("OWN_L0", 1_000_000.0), min_step: 0.001, imp: Default::default(), trades: Default::default(), last_upd: 0, stats: [0; 3],
            v: f("OWN_V", 1_000_000.0), selfcal: f("OWN_SELF", 0.0) != 0.0, h_ms: (f("OWN_H_S", 30.0) * 1000.0) as i64, vol_tot: 0.0, vol_t0: -1, vf: f("OWN_VF", 0.0), vmin: f("OWN_VMIN", 250_000.0), v_peak: 0.0, tmax_ms: (f("OWN_TMAX_S", 60.0) * 1000.0) as i64,
            anchor_n: f("OWN_ANCHOR_N", 0.0) as usize, ext_hist: Default::default(),
            gate: f("OWN_GATE", 0.0) != 0.0, gate_book: f("OWN_GATE", 0.0) == 2.0, hold_ms: (f("OWN_HOLD_S", 0.0) * 1000.0) as i64, held_since: None, hold_expired: 0, hold_step: f("OWN_HOLD_STEP", 0.0) != 0.0, only_hold: f("OWN_ONLY_HOLD", 0.0) != 0.0, p_ema_ms: f("OWN_P_EMA_S", 0.0) * 1000.0, p_ema: None, p_ema_hold_raw: f("OWN_P_EMA_HOLD_RAW", 0.0) != 0.0, held_now: false, hold_cap: f("OWN_HOLD_CAP", 0.0) != 0.0, held_side: 0.0, hold_r0: None, agree_c: None, ext_last: f64::NAN, ext_live: false, ext_change_ms: -1, hold_trig: f("OWN_HOLD_TRIG", 0.0) != 0.0, frozen_upd: f("OWN_FROZEN_UPD", 0.0) as u32, frozen_gap: f("OWN_FROZEN_GAP", 0.0), jump_gap: f("OWN_JUMP_GAP", 0.0), fail_hold: false, unchanged_n: 0, trig_step: f("OWN_HOLD_TRIG", 0.0) == 2.0, ext_win: std::collections::VecDeque::new(), holding: false, trig_blocked: 0, centre_prev: None, gate_held: 0,
            wash: std::env::var("WASH").ok().filter(|_| std::env::var("ATTACK_CAP").is_err()).map(|v| { let x: Vec<f64> = v.split(';').map(|a| a.parse().unwrap()).collect(); (x[0] as i64, (x[1] * 1000.0) as i64, x[2], x[3]) }), wash_px: None, wash_ntl: 0.0,
            skip: std::env::var("OWN_SKIP").ok().map(|v| { let x: Vec<i64> = v.split(';').map(|a| a.parse().unwrap()).collect(); (x[0], x[1]) }),
            diverge: f("OWN_DIVERGE", 0.0), diverge_starts: 0, no_frozen: f("OWN_NO_FROZEN", 0.0) != 0.0, n_self: f("OWN_N_SELF", 0.0) != 0.0, v_last: 0.0, step_stale: f("OWN_STEP_STALE", 0.0) != 0.0, step_stale_mode: f("OWN_STEP_STALE", 0.0) as u8, steps_skipped: 0, closed: std::env::var("OWN_CLOSED").ok().map(|v| v.split(',').filter(|w| !w.is_empty()).map(|w| { let x: Vec<i64> = w.split(';').map(|a| a.parse().unwrap()).collect(); (x[0], x[1]) }).collect()).unwrap_or_default() })
    }

    /// Impact mid: the midpoint of the average prices to sell and to buy `n` notional on the book (None if a side lacks it).
    fn impact_mid(book: &Book, n: f64) -> Option<f64> {
        let side = |buy: bool| {
            let (mut ntl, mut q) = (0.0, 0.0);
            for (p, z) in book.levels(buy, 400) {
                let (p, z) = (p as f64 / 1e6, z as f64 / 1e6);
                let take = ((n - ntl) / p).min(z);
                ntl += take * p; q += take;
                if ntl >= n - 1e-6 { return Some(ntl / q); }
            }
            None
        };
        Some((side(true)? + side(false)?) / 2.0)
    }

    fn sample(&mut self, t: i64, book: &Book) {
        if t < self.from_ms - 60_000 { return; }
        if let Some(v) = Self::impact_mid(book, self.n) {
            if self.imp.back().map_or(true, |x| x.1 != v) { self.imp.push_back((t, v)); }
        }
        while self.imp.len() > 2 && self.imp[1].0 < t - 120_000 { self.imp.pop_front(); }
    }

    fn trade(&mut self, t: i64, px: f64, sz: f64) { self.trade_f(t, px, sz, false) }

    fn trade_f(&mut self, t: i64, px: f64, sz: f64, forced: bool) {
        if self.selfcal {
            if !forced { if self.vol_t0 < 0 { self.vol_t0 = t; } self.vol_tot += px * sz; }
            self.trades.push_back((t, px, sz, forced));
            while self.trades.len() > 200_000 { self.trades.pop_front(); }
            return;
        }
        if t < self.from_ms - 120_000 { return; }
        self.trades.push_back((t, px, sz, forced));
        let keep = self.w_ms.max(self.tmax_ms);
        while self.trades.front().map_or(false, |x| x.0 < t - keep) { self.trades.pop_front(); }
    }

    /// volume-weighted median price of the newest voluntary trades up to `v` notional, no older than tmax
    fn trade_median(&mut self, ms: i64) -> Option<f64> {
        let v = if self.selfcal {
            let recent: f64 = self.trades.iter().rev().take_while(|x| x.0 >= ms - self.h_ms).filter(|x| !x.3 && x.0 <= ms).map(|x| x.1 * x.2).sum();
            let avg = if self.vol_t0 >= 0 && ms > self.vol_t0 { self.vol_tot * self.h_ms as f64 / (ms - self.vol_t0) as f64 } else { 0.0 };
            recent.max(avg)
        } else if self.vf > 0.0 {
            let vol: f64 = self.trades.iter().filter(|x| !x.3 && x.0 >= ms - 60_000 && x.0 <= ms).map(|x| x.1 * x.2).sum();
            (self.vf * vol).max(self.vmin)
        } else { self.v };
        if v > self.v_peak { self.v_peak = v; }
        self.v_last = v;
        let mut xs: Vec<(f64, f64)> = Vec::new();
        let mut ntl = 0.0;
        for &(t, p, z, forced) in self.trades.iter().rev() {
            if !self.selfcal && t < ms - self.tmax_ms { break; }
            if forced || t > ms { continue; }
            xs.push((p, p * z)); ntl += p * z;
            if ntl >= v { break; }
        }
        if xs.is_empty() { return None; }
        xs.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        let half = ntl / 2.0;
        let mut c = 0.0;
        for (p, w) in &xs { c += w; if c >= half { return Some(*p); } }
        xs.last().map(|x| x.0)
    }

    /// Impact notional for the hold's book checks: OWN_N, or with OWN_N_SELF=1 the larger of OWN_N and the trade window's
    /// self-calibrated volume V (a pushed book must hold the price over as much depth as recently traded)
    fn hold_n(&self) -> f64 { if self.n_self { self.n.max(self.v_last) } else { self.n } }

    /// Is xyz's trade price fresh at ms? By count: at least one voluntary trade in the trade window (OWN_STEP_STALE=1).
    /// By volume: voluntary notional in the window reached the day's average per window (OWN_STEP_STALE=2), so dust
    /// trades cannot keep it fresh.
    fn p_fresh(&self, ms: i64, by_volume: bool) -> bool {
        let w = self.trades.iter().rev().take_while(|x| x.0 >= ms - self.h_ms).filter(|x| !x.3 && x.0 <= ms);
        if !by_volume { return w.count() > 0; }
        let recent: f64 = w.map(|x| x.1 * x.2).sum();
        let avg = if self.vol_t0 >= 0 && ms > self.vol_t0 { self.vol_tot * self.h_ms as f64 / (ms - self.vol_t0) as f64 } else { 0.0 };
        recent > 0.0 && recent >= avg
    }

    /// time-weighted impact mid over [a, b]
    fn imp_avg(&self, a: i64, b: i64) -> Option<f64> {
        let (mut num, mut den) = (0.0, 0.0);
        for (k, &(t, v)) in self.imp.iter().enumerate() {
            let t1 = self.imp.get(k + 1).map_or(b, |x| x.0).min(b);
            let t0 = t.max(a);
            if t1 > t0 { num += v * (t1 - t0) as f64; den += (t1 - t0) as f64; }
        }
        if den > 0.0 { Some(num / den) } else { self.imp.back().map(|x| x.1) }
    }

    /// markPxs for an update at `ms` (µ-units), or None before from_ms.
    fn update(&mut self, ms: i64, ext: f64, prev: Option<f64>, local: Option<f64>, book: &Book, ext_cap: f64, clr: Option<&Clearing>) -> Option<(f64, f64)> {
        let a = self.last_upd.max(ms - 3_000);
        self.last_upd = ms;
        if self.anchor_n > 0 { self.ext_hist.push_back(ext); while self.ext_hist.len() > self.anchor_n { self.ext_hist.pop_front(); } }
        if ms < self.from_ms { return None; }
        if let Some((a, b)) = self.skip { if ms >= a && ms < b { self.centre_prev = None; return None; } }
        if let Some((w0, wd, wf, wn)) = self.wash {
            if ms >= w0 && ms < w0 + wd {
                let px = *self.wash_px.get_or_insert(ext * (1.0 + wf));
                self.trade_f(ms, px, wn / px, false);
                self.wash_ntl += wn;
            }
        }
        let pm3 = if self.mode == 3 { Some(self.trade_median(ms)) } else { None };
        let centre = if self.gate {
            let p = pm3.flatten().unwrap_or(ext);
            let book_ok = !self.gate_book || Self::impact_mid(book, self.hold_n()).map_or(false, |b| (b - ext).abs() > ext_cap * ext && (b - ext).signum() == (p - ext).signum());
            let mut want = ext_cap > 0.0 && (ext - p).abs() > ext_cap * ext && book_ok;
            if self.hold_trig {
                self.ext_win.push_back((ms, ext));
                while self.ext_win.len() > 1 && self.ext_win[0].0 < ms - self.h_ms { self.ext_win.pop_front(); }
                let (lo, hi) = self.ext_win.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |a, x| (a.0.min(x.1), a.1.max(x.1)));
                let jumped = if self.trig_step { self.ext_last.is_finite() && (ext - self.ext_last).abs() > ext_cap * ext } else { hi - lo > ext_cap * ext };
                if self.ext_last.is_finite() && ext != self.ext_last { self.ext_change_ms = ms; }
                if self.ext_last.is_finite() { if ext == self.ext_last { self.unchanged_n += 1 } else { self.unchanged_n = 0 } }
                let frozen = !self.no_frozen && (if self.frozen_upd > 0 { self.unchanged_n >= self.frozen_upd } else { self.ext_change_ms >= 0 && ms - self.ext_change_ms >= self.h_ms })
                    && !self.closed.iter().any(|&(a, b)| ms >= a && ms < b);
                if want && !self.holding && !(jumped || frozen) { want = false; self.trig_blocked += 1; }
                if self.jump_gap > 0.0 {
                    let g = self.jump_gap;
                    let book_g = Self::impact_mid(book, self.hold_n()).map_or(false, |b| (b - ext).abs() > g * ext && (b - ext).signum() == (p - ext).signum());
                    let dis = (ext - p).abs() > g * ext && book_g;
                    if !self.holding { self.fail_hold = false; }
                    if !want && dis && ((!self.holding && jumped) || (self.holding && self.fail_hold)) { want = true; }
                    if want && !self.holding && (jumped || frozen) { self.fail_hold = true; }
                }
                // OWN_DIVERGE=g: a hold may also start, at any speed, when xyz's trades and book both disagree with ext by
                // more than g (a walking or manipulated feed); it continues like a feed-failure hold
                if self.diverge > 0.0 && !self.holding && !want && !self.closed.iter().any(|&(a, b)| ms >= a && ms < b) {
                    let g = self.diverge;
                    let book_g = Self::impact_mid(book, self.hold_n()).map_or(false, |b| (b - ext).abs() > g * ext && (b - ext).signum() == (p - ext).signum());
                    if (ext - p).abs() > g * ext && book_g { want = true; self.fail_hold = true; self.diverge_starts += 1; }
                }
                if !want && frozen && self.frozen_gap > 0.0 {
                    let g = self.frozen_gap;
                    let book_g = Self::impact_mid(book, self.hold_n()).map_or(false, |b| (b - ext).abs() > g * ext && (b - ext).signum() == (p - ext).signum());
                    if (ext - p).abs() > g * ext && book_g { want = true; }
                }
                self.holding = want;
            }
            let expired = want && self.hold_ms > 0 && self.held_since.map_or(false, |t0| ms - t0 >= self.hold_ms);
            if expired { self.hold_expired += 1; }
            // a live feed: ext changed within the trade window (OWN_H_S, the same window P uses); a stuck feed stops being
            // capped after one window, so the mark can follow xyz away from it
            if self.ext_last.is_finite() && ext != self.ext_last { self.ext_change_ms = ms; }
            self.ext_live = self.ext_change_ms >= 0 && ms - self.ext_change_ms <= self.h_ms;
            self.ext_last = ext;
            let agree = ext_cap > 0.0 && (ext - p).abs() <= ext_cap * ext;
            self.held_side = if want && self.centre_prev.is_some() { (p - ext).signum() } else { 0.0 };
            // R0: the centre of the last update where ext and xyz agreed, not the hold's first update (which may already
            // carry a bad print if the book condition confirmed the hold one update late)
            if self.held_side != 0.0 { if self.hold_r0.is_none() { self.hold_r0 = self.agree_c.or(self.centre_prev); } } else { self.hold_r0 = None; }
            // OWN_STEP_STALE=1: at expiry the held centre steps toward ext only when xyz has no voluntary trades in the trade
            // window (P is stale); while xyz trades, the hold lasts until xyz's own market agrees with ext again
            // mode 3: never step (what the first version did in practice: P reaches back without a time limit)
            let p_stale = match self.step_stale_mode { 0 => true, 3 => false, m => !self.p_fresh(ms, m == 2) };
            let c = match self.centre_prev {
                Some(c0) if want && !expired => { self.gate_held += 1; self.held_since.get_or_insert(ms); c0 }
                Some(c0) if want && self.hold_step && self.step_stale && !p_stale => { self.gate_held += 1; self.held_since = Some(ms); self.steps_skipped += 1; c0 }
                // OWN_HOLD_STEP=1: at expiry the centre steps toward ext by at most d (its own width) and the hold restarts
                Some(c0) if want && self.hold_step => { self.gate_held += 1; self.held_since = Some(ms); c0 + (ext - c0).clamp(-ext_cap * c0, ext_cap * c0) }
                _ => { self.held_since = None; ext }
            };
            self.centre_prev = Some(c);
            self.held_now = want;
            if agree { self.agree_c = Some(c); }
            c
        } else if self.anchor_n > 0 {
            let mut v: Vec<f64> = self.ext_hist.iter().copied().collect();
            v.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let k = v.len();
            if k % 2 == 1 { v[k / 2] } else { 0.5 * (v[k / 2 - 1] + v[k / 2]) }
        } else { ext };
        self.stats[0] += 1;
        // held with OWN_HOLD_CAP: on the side away from ext the band ends at the centre the hold began from (R0), so a hold
        // can stop the mark following ext but never push it further away than where it stood; steps toward ext still apply
        let (mut lo_b, mut hi_b) = (centre * (1.0 - ext_cap), centre * (1.0 + ext_cap));
        if self.hold_cap && self.ext_live { if let Some(r0) = self.hold_r0 {
            if self.held_side > 0.0 { hi_b = hi_b.min(r0).max(lo_b); } else if self.held_side < 0.0 { lo_b = lo_b.max(r0).min(hi_b); }
        } }
        let clampx = |v: f64| { let mut v = v; if ext_cap > 0.0 { v = v.max(lo_b).min(hi_b); }
            if let Some(p0) = prev { v = v.max(p0 * 0.99).min(p0 * 1.01); } v };
        if self.mode == 3 {
            let pm = pm3.flatten();
            if pm.is_none() { self.stats[2] += 1; }
            let mut p = pm.unwrap_or(ext);
            if self.p_ema_ms > 0.0 {
                let e = match self.p_ema { Some((t0, v)) => { let a = 1.0 - (-((ms - t0).max(0) as f64) / self.p_ema_ms).exp(); v + a * (p - v) } None => p };
                self.p_ema = Some((ms, e));
                if !(self.p_ema_hold_raw && self.held_now) { p = e; }
            }
            if self.only_hold && !self.held_now { return None; }
            return Some((clampx(ext), clampx(p)));
        }
        let inst = Self::impact_mid(book, self.n);
        let ia = self.imp_avg(a, ms).or(inst)?;
        self.trades.retain(|x| x.0 >= ms - self.w_ms);
        let (qn, q): (f64, f64) = self.trades.iter().fold((0.0, 0.0), |s, x| (s.0 + x.1 * x.2, s.1 + x.2));
        let vw = if q > 0.0 { qn / q } else { ia };
        let med = |x: f64, y: f64, z: f64| x.max(y).min(x.min(y).max(z));
        let (mut m1, mut m2) = (ia, vw);
        match self.mode {
            1 => if let (Some(p0), Some(c)) = (prev, clr) {
                let target = med(ia, vw, local.unwrap_or(ia));
                // liquidation prices crossed between p0 and target, nearest first
                let r0 = 0.5 / c.max_lev();
                let (lo, hi) = (p0.min(target), p0.max(target));
                let mut lq: Vec<(f64, f64)> = c.acc.values().filter(|d| d.margined() && d.q != 0.0 && ((target < p0) == (d.q > 0.0)))
                    .filter_map(|d| d.liq_px(r0).filter(|&lp| lp > lo && lp < hi).map(|lp| ((lp - p0).abs(), d.q.abs() * lp))).collect();
                lq.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
                let mut cum = 0.0;
                let mut stop = (target - p0).abs();
                for (dist, n) in lq { cum += n; if cum > self.l0 { stop = dist; break; } }
                let stop = stop.max(self.min_step * p0).min((target - p0).abs());
                if stop < (target - p0).abs() { self.stats[1] += 1; }
                let v = p0 + (target - p0).signum() * stop;
                m1 = v; m2 = v;
            },
            2 => if let (Some(p0), Some(i)) = (prev, inst) {
                if (ext - p0).signum() == (i - p0).signum() && (ext - p0).abs() >= 0.5 * (i - p0).abs() {
                    self.stats[2] += 1;
                    m1 = i; m2 = i;
                }
            },
            _ => {}
        }
        Some((clampx(m1), clampx(m2)))
    }
}

/// MARK3_RATCHET=1 (pkgm3rSSS): the anchor never lags behind what the mark has already accepted. After its averaging step it
/// is brought inside [vote, previous mark]: once xyz's market has confirmed a feed move (the mark followed it), a later push
/// of the book cannot take the mark back to the old level (the book push during a crash). In a walk the mark has not
/// followed the feed, so nothing changes. `a`, `v` in price micro-units, `pm` the previous mark in price units.
/// MARK3_BAND=d | h | <fraction>: both published inputs are kept within a band around the plain 30-minute average of the
/// feed's vote (d = 1 / maxLev, h = half of it). Since the median of three lies between the two inputs, the mark can then
/// never sit further than the band from that average, whatever xyz's book does: feed and book together move it by the
/// band at most. Cost: a real move larger than the band is followed only as fast as the average. Unset: no band.
/// The band's width, read once: `Some(k)` means k / maxLev, `None` an outright fraction.
fn band_w() -> &'static Option<(f64, f64)> {
    static W: std::sync::OnceLock<Option<(f64, f64)>> = std::sync::OnceLock::new();
    W.get_or_init(|| match std::env::var("MARK3_BAND").as_deref() {
        Ok("d") => Some((1.0, 0.0)),
        Ok("h") => Some((0.5, 0.0)),
        Ok(x) => Some((0.0, x.parse().unwrap_or_else(|_| panic!("MARK3_BAND: cannot read {x:?}: d | h | a fraction")))),
        Err(_) => None,
    })
}

fn band(pure: &mut Option<f64>, v: f64, a: f64, dt: f64, tau: f64, d: f64) -> (f64, f64) {
    let b = band_w().map_or(0.0, |(k, x)| k * d + x);
    if b <= 0.0 { return (v, a); }
    let p0 = pure.unwrap_or(v);
    let p = p0 + (1.0 - (-dt / tau).exp()) * (v - p0);
    *pure = Some(p);
    (v.clamp(p * (1.0 - b), p * (1.0 + b)), a.clamp(p * (1.0 - b), p * (1.0 + b)))
}

/// The ratchet's mode, read once and checked.
fn ratchet_mode() -> &'static str {
    static M: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    M.get_or_init(|| {
        let v = std::env::var("MARK3_RATCHET").unwrap_or_default();
        assert!(v.is_empty() || v == "1" || v == "b" || v.strip_prefix('w').map_or(false, |n| n.parse::<f64>().is_ok()),
            "unknown MARK3_RATCHET={v}: 1 | b | wN (N seconds)");
        v
    })
}

fn ratchet(a: f64, v: f64, orc: &[OrcRec], now: i64) -> f64 {
    // MARK3_RATCHET: 1 = [vote, previous mark] | b = the same, skipped when xyz's book was the deciding vote of the previous
    // mark (strictly between the two published inputs) | wN = [vote, every mark of the last N seconds]: the anchor only
    // follows a move the mark has held for N seconds, so a book push shorter than N does not carry it
    let mode = ratchet_mode();
    let Some(last) = orc.last() else { return a };
    if mode == "1" || mode == "b" {
        let Some(m) = mark_of(last) else { return a };
        if mode == "b" {
            if let Some(bk) = book_px(last) {
                if bk > last.m1.min(last.m2) && bk < last.m1.max(last.m2) { return a; }
            }
        }
        let m = m * 1e6;
        return a.clamp(v.min(m), v.max(m));
    }
    if let Some(n) = mode.strip_prefix('w').and_then(|x| x.parse::<f64>().ok()) {
        let (mut lo, mut hi, mut any) = (v, v, false);
        for (k, o) in orc.iter().rev().enumerate() {
            if k > 0 && (now - o.ms) as f64 > n * 1000.0 { break; }
            if let Some(m) = mark_of(o) { let m = m * 1e6; lo = lo.min(m); hi = hi.max(m); any = true; }
        }
        return if any { a.clamp(lo, hi) } else { a };
    }
    a
}

/// The switches read inside the update loop. Each is read from the environment once per process and kept: an env lookup
/// locks the environment and allocates, and these sit on the path that runs at every relayer update.
macro_rules! once_flag {
    ($name:ident, $k:literal, $on:expr) => {
        fn $name() -> bool {
            static V: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
            *V.get_or_init(|| { let v = std::env::var($k); let v = v.as_deref(); $on(v) })
        }
    };
}
once_flag!(mark3_int, "MARK3_INT", |v| v == Ok("1"));
once_flag!(mark3_pure, "MARK3_PURE", |v| v == Ok("1"));
once_flag!(mark3_d, "MARK3_D", |v| v == Ok("1"));
once_flag!(hl_cap, "HL_CAP", |v| v != Ok("0"));

/// MARKDBG: read once.
fn markdbg() -> bool {
    static V: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *V.get_or_init(|| std::env::var("MARKDBG").is_ok())
}

pub fn median3(a: i64, b: i64, c: i64) -> i64 {
    a.max(b).min(a.min(b).max(c))
}

/// Mark = median(m1, m2, book price) at each relayer update, the book price as clearing::book_px defines it;
/// compare with the real liquidation marks.
pub fn mark_check(orc: &[OrcRec], dir: &str) {
    let lf = format!("{dir}/liqmarks.arrow");
    let (lh, lm) = (load::<Int64Type>(&lf, "h"), load::<Int64Type>(&lf, "mk"));
    let hs: Vec<i64> = orc.iter().map(|o| o.h).collect();
    let (mut ok, mut n, mut ex) = (0, 0, 0);
    for (h, mk) in lh.iter().zip(lm.iter()) {
        let i = hs.partition_point(|x| x <= h);
        if i == 0 { continue; }
        let o = orc[i - 1];
        if let Some(bk) = book_px(&o) {
            let sim = median3(o.m1, o.m2, bk).clamp(o.lo, o.hi);
            n += 1;
            if (sim - mk).abs() < 5000 { ok += 1; }
            if sim == *mk { ex += 1; }
            if markdbg() { println!("MARKROW h={} real={} sim={} m1={} m2={} loc={} ext={} clamped={}", h, mk, sim, o.m1, o.m2, bk, o.ext, (median3(o.m1, o.m2, bk) != sim) as u8); }
            if sim != *mk && markdbg() { println!("MARKMISS h={} ms={} real={} sim={} m1={} m2={} bid={:?} ask={:?} last={:?} lo={} hi={} ext={}", h, o.ms, mk, sim, o.m1, o.m2, o.bid, o.ask, o.last, o.lo, o.hi, o.ext); }
        } else if markdbg() {
            // no book price at a liquidation block (both sides empty, or ONE_SIDED=hold): what did Hyperliquid's mark do?
            println!("MARKONE h={} ms={} real={} m1={} m2={} bid={:?} ask={:?} last={:?} lo={} hi={} ext={}", h, o.ms, mk, o.m1, o.m2, o.bid, o.ask, o.last, o.lo, o.hi, o.ext);
        }
    }
    println!("mark reproduced at liquidation blocks: {ok}/{n} (exact {ex})");
}
