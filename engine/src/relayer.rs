//! Relayer simulation (MARK_SOURCE=simulate): rebuilds the trade.xyz relayer's setOracle outputs from its inputs.
//!
//! Fitted on GOOGL 2026-10-28 (SIMULATOR_SPEC.md, "Relayer reconstruction"), extended on CL / BRENTOIL / SILVER 2026-09-10/10-22:
//!   oracle = clamp(ext, R)             R = the oracle the relayer last saw on-chain, S[n-k] (read lag k from prep)
//!   m1     = clamp(oracle, M)          M = the mark on-chain at the previous update (trade.xyz: the 50 bp per-update clamp
//!                                      applies to the oracle and to the mark component). Binds only when the book sits
//!                                      > 50 bp from ext (oil: 50-120 bp under E all day); stocks and metals: m1 = oracle
//!   internal session (RELAYER_INTERNAL="a;b,..." ms, or $PREP/internal_windows.txt, from sim/prep/closed_windows.py --internal):
//!                                      oracle = o + (1 - exp(-dt*/tau)) (mid - o), dt* = min(dt, tau / 10), tau = INTERNAL_TAU
//!                                      (trade.xyz's internal oracle, 30 min; the book mid stands in for its impact price)
//!   m2          = clamp(ext + e, R)    e = EMA_tau(mid - ext), sampled every EMA_P ms; the relayer sees the book as of
//!                                      the update it last saw on-chain (the same read lag k: (k-1) updates back)
//!   clamp(x, R) = x rounded to the price grid, inside [R(1-c), R(1+c)] with both edges rounded inward
//! Prices are on HL's perp grid: 5 significant figures, at most 6 - szDecimals decimals.
//! m2's band is the hull of the bands around the lagged oracle and around m2's own lagged value (`M2_REF=hull`, default;
//! `M2_REF=oracle` = the oracle band only): every real m2 of GOOGL / INTC / AMZN in 18:00-22:00 lies in it (14,396 / 14,396),
//! while 47 lie outside the oracle band alone (INTC: 12 ticks below it all through the 20:01 descent).
//! External-price cap (fitted on the INTC / AMZN crashes of 2026-10-29): both outputs also stay within d = 1 / maxLeverage
//! of ext, rounded toward ext, and the cap overrides the clamp band: INTC (10x) published exactly ext * 1.10 and AMZN (20x)
//! ext * 1.05 for ~25 updates while ext ran ahead of the 50 bp steps. `ORACLE_CAP` (fraction) overrides d; 0 disables it.
//! Before `from_ms` the real outputs are replayed; the EMA state is seeded from the last real m2 - ext.
//!
//! Residual (RELAYER_RESID_OUT / RELAYER_RESID_IN): the relayer samples its own view of the book, which drifts ±1 tick
//! from ours. A baseline run at real parameters writes r_n = (real m2 - ext) - e_n at every update where the real m2 is
//! strictly inside the (rounded) clamp band; where the real m2 sits on a band edge, r is the smallest residual that lands
//! on the same edge (0 when the plain simulation already does). A run that reads it publishes clamp(ext + e_n + r_n). At real parameters this
//! reproduces m2 exactly; in scenarios the relayer's view error at each update is kept as it was. The file also carries the read lag where the real m2 shows it (prep can only infer it from a clamped
//! oracle): column 2, 0 = keep prep's lag.

//!
//! MARK=band (a redesign, deployer-controlled): HyperCore's mark is median(markPxs, local book mark), so two markPxs
//! a < b make it the local mark clamped to [a, b]. This mode publishes a = C - w, b = C + w around a centre that is
//! costly to move: C = ext + P, P = EMA_{BAND_TAU s}(mid - ext) capped at +-BAND_PMAX (bp), sampled like e. w = BAND_W
//! (bp). No per-update clamp on C: only HyperCore's 1% per update from the previous mark (applied to both outputs, which
//! is the same as clamping the final mark) and the external-price cap.
//!
//! MARK=venues: publish two independent venues' prices, markPxs = [ext, venue] (VENUE_PX: arrow file with ms, px in
//! µ-units, e.g. Binance's stock perp), so HyperCore's mark is median(ext, venue, local book): the book picks a point
//! between the two venues, and moving the mark takes moving two of the three markets. A venue silent for more than
//! VENUE_STALE_MS (default 10 s) is replaced by ext. MARK=ext: markPxs = [ext, ext], the mark is ext.
//! Both keep the external-price cap and HL's 1% per update.

use crate::book::Px;
use crate::io::load;
use arrow_array::types::Int64Type;

pub struct RelayerParams {
    pub clamp_bps: f64,
    /// CLAMP_O_BPS: per-update clamp of the oracle input (m1) only; default = CLAMP_BPS (today). Large: m1 follows E at once,
    /// while the book input (m2) keeps its clamp
    pub clamp_o_bps: f64,
    pub clamp_m2: bool,
    pub tau_s: f64,
    pub sample_ms: i64,
    pub from_ms: i64,
}

impl RelayerParams {
    pub fn from_env(w0: i64) -> Self {
        let f = |k: &str, d: f64| std::env::var(k).map_or(d, |v| v.parse().unwrap_or_else(|_| panic!("{k}: cannot read {v:?} as a number")));
        RelayerParams {
            clamp_bps: f("CLAMP_BPS", 50.0),
            clamp_o_bps: f("CLAMP_O_BPS", f("CLAMP_BPS", 50.0)),
            clamp_m2: f("CLAMP_M2", 1.0) != 0.0,
            tau_s: f("EMA_TAU", 150.0),
            sample_ms: f("EMA_P", 500.0) as i64,
            from_ms: w0 - f("RELAYER_WARMUP_S", 900.0) as i64 * 1000,
        }
    }
}

pub struct Relayer {
    pub p: RelayerParams,
    max_dec: i32,
    e: f64,
    ts: Option<i64>,               // last EMA sample time
    tl: std::collections::VecDeque<(i64, f64)>, // book mid timeline: (from ms, mid)
    upd_ms: Vec<i64>,              // time of each update
    hist: Vec<Px>, // oracle published at each update (real before from_ms, simulated after)
    hist2: Vec<Px>, // m2 published at each update
    hist_o: Vec<Px>, // oracle at each update (= m1 unless the mark clamp binds)
    /// ORACLE_CORROB: the oracle jumps to ext only within the hull of its last value and xyz's book mid (each +- c)
    corrob: bool,
    /// RELAYER_STALE_INTERNAL: updates of unchanged ext after which the internal oracle prices it (0 = off)
    stale_n: u32,
    unch: u32,
    /// the capped internal oracle's own unrounded value (see int_state in update): Some while the feed is not live
    int_state: Option<f64>,
    last_ext: Option<Px>,
    /// internal-session windows (ms): the oracle is trade.xyz's internal EMA of the book; tau (s)
    internal: Vec<(i64, i64)>,
    internal_tau: f64,
    /// INTERNAL_CAP: cap on the internal oracle's book input, as a fraction of the oracle (0 = none, today)
    internal_cap: f64,
    /// the last update was priced by the internal oracle (closed venue, or a stale feed): the feed carried no information
    pub last_internal: bool,
    m2_hull: bool,
    /// M2_REF=ext: the book input is clamped around the current external price (not the lagged oracle)
    m2_ext: bool,
    // gate counters in the scoring window: (n, m1 exact, m2 exact, m2 within one tick)
    pub score: [u64; 4],
    resid_in: Option<Vec<(f64, u8, f64)>>,
    resid_out: Option<Vec<(f64, u8, f64)>>,
    ext_cap: f64, // d: outputs within [ext (1 - d), ext (1 + d)]; 0 = no cap
    /// MARK=band: (half-width, premium cap) as fractions, premium EMA tau (s), premium state
    band: Option<(f64, f64, f64)>,
    pb: f64,
    /// MARK=venues / ext: the second venue's (ms, px) series and its staleness limit; `ext_only` for MARK=ext
    venue: Option<(Vec<i64>, Vec<i64>, i64)>,
    ext_only: bool,
    /// INTERNAL_FLOAT: the capped internal oracle keeps its own unrounded value between updates (default on; see update)
    int_float: bool,
    /// HL_CLAMP: also apply HyperCore's own 1% per-update clamp to the published values (see update)
    hl_clamp: bool,
}

impl Relayer {
    pub fn new(p: RelayerParams, sz_decimals: i32) -> Self {
        Relayer { p, int_state: None, last_internal: false, max_dec: 6 - sz_decimals, e: 0.0, ts: None, tl: Default::default(), upd_ms: Vec::new(), hist: Vec::new(), hist2: Vec::new(), hist_o: Vec::new(), corrob: std::env::var("ORACLE_CORROB").map_or(false, |v| v == "1"), stale_n: std::env::var("RELAYER_STALE_INTERNAL").ok().and_then(|v| v.parse().ok()).unwrap_or(0), unch: 0, last_ext: None, internal: Vec::new(), internal_tau: std::env::var("INTERNAL_TAU").ok().and_then(|v| v.parse().ok()).unwrap_or(1800.0), internal_cap: std::env::var("INTERNAL_CAP").ok().and_then(|v| v.parse().ok()).unwrap_or(0.0), m2_hull: std::env::var("M2_REF").map_or(true, |v| v != "oracle" && v != "ext"), m2_ext: std::env::var("M2_REF").map_or(false, |v| v == "ext"), score: [0; 4],
            resid_in: std::env::var("RELAYER_RESID_IN").ok().map(|f| {
                std::fs::read_to_string(&f).unwrap_or_else(|e| panic!("{f}: {e}")).lines().map(|l| {
                    let mut it = l.split(' ');
                    (it.next().unwrap().parse().unwrap(), it.next().map_or(0, |k| k.parse().unwrap()), it.next().map_or(f64::NAN, |r| r.parse().unwrap()))
                }).collect()
            }),
            resid_out: std::env::var("RELAYER_RESID_OUT").ok().map(|_| Vec::new()), ext_cap: 0.0,
            band: (std::env::var("MARK").ok().as_deref() == Some("band")).then(|| {
                let f = |k: &str, d: f64| std::env::var(k).map_or(d, |v| v.parse().unwrap_or_else(|_| panic!("{k}: cannot read {v:?} as a number")));
                (f("BAND_W", 25.0) / 1e4, f("BAND_PMAX", 50.0) / 1e4, f("BAND_TAU", 1800.0))
            }),
            pb: 0.0,
            venue: (std::env::var("MARK").ok().as_deref() == Some("venues")).then(|| {
                let f = std::env::var("VENUE_PX").expect("MARK=venues needs VENUE_PX");
                (load::<Int64Type>(&f, "ms"), load::<Int64Type>(&f, "px"),
                 10_000)
            }),
            ext_only: std::env::var("MARK").ok().as_deref() == Some("ext"),
            int_float: std::env::var("INTERNAL_FLOAT").as_deref() != Ok("0"),
            hl_clamp: std::env::var("HL_CLAMP").as_deref() == Ok("1") }
    }

    pub fn ext_cap(&self) -> f64 { self.ext_cap }

    /// Internal-session windows: RELAYER_INTERNAL="a;b,a;b" (ms) or the prep's internal_windows.txt (same format).
    pub fn set_internal(&mut self, prep_dir: &str) {
        let v = std::env::var("RELAYER_INTERNAL").ok().or_else(|| std::fs::read_to_string(format!("{prep_dir}/internal_windows.txt")).ok());
        self.internal = v.map(|v| v.trim().split(',').filter(|w| !w.is_empty()).map(|w| {
            let x: Vec<i64> = w.split(';').map(|a| a.trim().parse().unwrap()).collect(); (x[0], x[1]) }).collect()).unwrap_or_default();
        if !self.internal.is_empty() { println!("relayer internal-session windows: {} (tau {} s)", self.internal.len(), self.internal_tau); }
    }

    /// m1: the oracle clamped within the per-update clamp of the mark M (CLAMP_O_BPS), then the cap around ext
    fn mark_clamp(&self, o: Px, m: Option<f64>, ext: f64) -> Px {
        let Some(m) = m else { return o };
        let c = self.p.clamp_o_bps / 1e4;
        let (lo, hi) = (self.round(m * (1.0 - c), 1), self.round(m * (1.0 + c), -1));
        let v = if lo <= hi { o.max(lo).min(hi) } else { o };
        if self.ext_cap > 0.0 { let d = self.ext_cap; v.max(self.round(ext * (1.0 - d), 1)).min(self.round(ext * (1.0 + d), -1)) } else { v }
    }

    /// The external-price cap d = 1 / maxLeverage (ORACLE_CAP overrides).
    pub fn set_max_lev(&mut self, max_lev: f64) {
        self.ext_cap = std::env::var("ORACLE_CAP").ok().and_then(|v| v.parse().ok()).unwrap_or(1.0 / max_lev);
    }

    fn tick(&self, x: f64) -> f64 {
        let d = (4 - x.abs().log10().floor() as i32).min(self.max_dec);
        10f64.powi(-d)
    }

    /// Round to the grid: 0 nearest, -1 down, +1 up.
    fn round(&self, x: f64, mode: i8) -> Px {
        let t = self.tick(x);
        let q = x / t;
        let r = match mode {
            -1 => (q + 1e-9).floor(),
            1 => (q - 1e-9).ceil(),
            _ => q.round(),
        };
        (r * t * 1e6).round() as Px
    }

    /// clamp(x, r) inside the band around r, then inside the external-price cap around `ext`.
    fn clamp(&self, x: f64, r: f64, ext: f64) -> Px {
        self.clamp_h(x, r, r, ext)
    }

    /// the oracle input's clamp (CLAMP_O_BPS), then the cap around ext
    fn clamp_o(&self, x: f64, r: f64, ext: f64) -> Px {
        let c = self.p.clamp_o_bps / 1e4;
        let (lo, hi) = (r * (1.0 - c), r * (1.0 + c));
        let v = if x < lo { self.round(lo, 1) } else if x > hi { self.round(hi, -1) } else { self.round(x, 0) };
        if self.ext_cap > 0.0 { let d = self.ext_cap; v.max(self.round(ext * (1.0 - d), 1)).min(self.round(ext * (1.0 + d), -1)) } else { v }
    }

    /// clamp inside the band spanning references [ra, rb] (the hull of their bands), then inside the cap around `ext`.
    fn clamp_h(&self, x: f64, ra: f64, rb: f64, ext: f64) -> Px {
        let c = self.p.clamp_bps / 1e4;
        let (lo, hi) = (ra.min(rb) * (1.0 - c), ra.max(rb) * (1.0 + c));
        let v = if x < lo {
            self.round(lo, 1)
        } else if x > hi {
            self.round(hi, -1)
        } else {
            self.round(x, 0)
        };
        if self.ext_cap > 0.0 {
            let d = self.ext_cap;
            v.max(self.round(ext * (1.0 - d), 1)).min(self.round(ext * (1.0 + d), -1))
        } else {
            v
        }
    }

    /// Published edges (rounded inward) around the reference r, intersected with the cap around ext (the cap wins when
    /// the two do not overlap).
    fn band(&self, r: f64, ext: f64) -> (Px, Px) {
        self.band_h(r, r, ext)
    }

    fn band_h(&self, ra: f64, rb: f64, ext: f64) -> (Px, Px) {
        let c = self.p.clamp_bps / 1e4;
        let (mut lo, mut hi) = (self.round(ra.min(rb) * (1.0 - c), 1), self.round(ra.max(rb) * (1.0 + c), -1));
        if self.ext_cap > 0.0 {
            let d = self.ext_cap;
            let (cl, ch) = (self.round(ext * (1.0 - d), 1), self.round(ext * (1.0 + d), -1));
            lo = lo.max(cl).min(ch);
            hi = hi.min(ch).max(cl);
        }
        (lo, hi)
    }

    /// The book mid from `t_ms` on (call when the best bid / ask may have changed).
    pub fn book(&mut self, t_ms: i64, mid: Option<f64>) {
        let Some(m) = mid else { return };
        match self.tl.back_mut() {
            Some(x) if x.0 == t_ms => x.1 = m,
            Some(x) if x.1 == m => {}
            _ => self.tl.push_back((t_ms, m)),
        }
    }

    fn mid_at(&self, t: i64) -> Option<f64> {
        let i = self.tl.partition_point(|x| x.0 <= t);
        (i > 0).then(|| self.tl[i - 1].1)
    }

    /// One relayer update. Returns (m1, m2) to publish. `ext`, `real` in µ-units; `lag` = read lag k.
    pub fn update(&mut self, ms: i64, ext: Px, lag: u8, real: (Px, Px), score: bool, prev_mark: Option<Px>) -> (Px, Px) {
        let n = self.hist.len();
        if ms < self.p.from_ms || n == 0 {
            if let Some(v) = self.resid_out.as_mut() { v.push((f64::NAN, 0, f64::NAN)); }
            // the real oracle is not in the prep: rebuild it from ext (clamp around the previous one), m1 at the start
            let o = if n == 0 { real.0 } else { self.clamp(ext as f64 / 1e6, self.hist_o[n - 1] as f64 / 1e6, ext as f64 / 1e6) };
            self.hist_o.push(o);
            self.hist.push(real.0);
            self.hist2.push(real.1);
            self.upd_ms.push(ms);
            self.e = (real.1 - ext) as f64 / 1e6;
            self.pb = self.e;
            self.ts = Some(ms - ms.rem_euclid(self.p.sample_ms));
            return real;
        }
        if self.venue.is_some() || self.ext_only {
            let x = ext as f64 / 1e6;
            let v = self.venue.as_ref().and_then(|(t, p, stale)| {
                let i = t.partition_point(|&m| m <= ms);
                (i > 0 && ms - t[i - 1] <= *stale).then(|| p[i - 1] as f64 / 1e6)
            }).unwrap_or(x);
            let (mut a, mut b) = (self.round(x, 0), self.round(v, 0));
            if self.ext_cap > 0.0 {
                let d = self.ext_cap;
                let (cl, ch) = (self.round(x * (1.0 - d), 1), self.round(x * (1.0 + d), -1));
                a = a.max(cl).min(ch);
                b = b.max(cl).min(ch);
            }
            if let Some(pm) = prev_mark {
                let pm = pm as f64 / 1e6;
                let (pl, ph) = (self.round(pm * 0.99, 1), self.round(pm * 1.01, -1));
                a = a.max(pl).min(ph);
                b = b.max(pl).min(ph);
            }
            self.upd_ms.push(ms);
            self.hist.push(a);
            self.hist2.push(b);
            self.hist_o.push(a);
            if let Some(v) = self.resid_out.as_mut() { v.push((f64::NAN, 0, f64::NAN)); }
            return (a, b);
        }
        if let Some((w, pmax, tau)) = self.band {
            // external-anchored band: premium EMA on the book as of now (the relayer reads it directly)
            let x = ext as f64 / 1e6;
            let (p, beta) = (self.p.sample_ms, (-(self.p.sample_ms as f64) / 1000.0 / tau).exp());
            let mut ts = self.ts.unwrap();
            while ts + p <= ms {
                ts += p;
                if let Some(m) = self.mid_at(ts) { self.pb = beta * self.pb + (1.0 - beta) * (m - x); }
            }
            self.ts = Some(ts);
            while self.tl.len() > 2 && self.tl[1].0 < ms - 120_000 { self.tl.pop_front(); }
            self.upd_ms.push(ms);
            let c = x + self.pb.clamp(-pmax * x, pmax * x);
            let (mut lo, mut hi) = (self.round(c * (1.0 - w), 1), self.round(c * (1.0 + w), -1));
            if self.ext_cap > 0.0 {
                let d = self.ext_cap;
                let (cl, ch) = (self.round(x * (1.0 - d), 1), self.round(x * (1.0 + d), -1));
                lo = lo.max(cl).min(ch);
                hi = hi.min(ch).max(cl);
            }
            if let Some(pm) = prev_mark {
                let pm = pm as f64 / 1e6;
                let (pl, ph) = (self.round(pm * 0.99, 1), self.round(pm * 1.01, -1));
                lo = lo.max(pl).min(ph);
                hi = hi.min(ph).max(pl);
            }
            self.hist.push(lo);
            self.hist2.push(hi);
            self.hist_o.push(lo);
            if let Some(v) = self.resid_out.as_mut() { v.push((f64::NAN, 0, f64::NAN)); }
            return (lo, hi);
        }
        let x = ext as f64 / 1e6;
        let rin = self.resid_in.as_ref().map(|rv| rv.get(n).copied().unwrap_or((f64::NAN, 0, f64::NAN)));
        let lag = match rin { Some((_, k, _)) if k > 0 => k, _ => lag.max(1) };
        // EMA samples since the last update, on the book as the relayer saw it ((lag-1) updates back), netted
        // against this update's external price
        let back = ms - self.upd_ms[n.saturating_sub(lag as usize - 1).min(n - 1)].min(ms);
        let back = if lag > 1 { back } else { 0 };
        let (p, beta) = (self.p.sample_ms, (-(self.p.sample_ms as f64) / 1000.0 / self.p.tau_s).exp());
        let mut ts = self.ts.unwrap();
        while ts + p <= ms {
            ts += p;
            if let Some(m) = self.mid_at(ts - back) { self.e = beta * self.e + (1.0 - beta) * (m - x); }
        }
        self.ts = Some(ts);
        let mid_now = self.mid_at(ms - back);
        while self.tl.len() > 2 && self.tl[1].0 < ms - 120_000 { self.tl.pop_front(); }
        let dt_s = (ms - self.upd_ms[n - 1]) as f64 / 1000.0;
        self.upd_ms.push(ms);
        let refp = |k: u8| self.hist_o[n.saturating_sub(k as usize)] as f64 / 1e6;
        let r = refp(lag);
        // m2's references: the lagged oracle and (hull) m2's own lagged value
        let r2 = if self.m2_hull { self.hist2[n.saturating_sub(lag as usize)] as f64 / 1e6 } else { r };
        // RELAYER_STALE_INTERNAL=n: E unchanged for n updates counts as not live and is priced like a closure (B)
        self.unch = if self.last_ext == Some(ext) { self.unch + 1 } else { 0 };
        self.last_ext = Some(ext);
        let internal = self.internal.iter().any(|&(a, b)| ms >= a && ms < b) || (self.stale_n > 0 && self.unch >= self.stale_n);
        self.last_internal = internal;
        // The capped internal oracle (INTERNAL_CAP > 0, our rule) keeps its own unrounded value between updates and publishes
        // it rounded. Stepping from the published (rounded) oracle, as today's uncapped rule is replayed, makes the capped
        // step tick-dependent: on SKHX (tick 0.1 at 1,237) a step of 0.02 rounds back and the oracle never moves; on GOOGL
        // (tick 0.01 at 300) a step of 0.005 rounds to a full tick and it moves twice too fast. INTERNAL_FLOAT=0: old behaviour.
        let float_state = self.internal_cap > 0.0 && self.int_float;
        let int_prev = if internal && float_state { self.int_state } else { None };
        self.int_state = if internal && float_state {
            let o0 = int_prev.unwrap_or(self.hist_o[n - 1] as f64 / 1e6);
            let a = 1.0 - (-(dt_s.min(0.1 * self.internal_tau)) / self.internal_tau).exp();
            let gap = (mid_now.unwrap_or(o0) - o0).clamp(-self.internal_cap * o0, self.internal_cap * o0);
            let v = o0 + a * gap;
            // the same bound as the published value: within 1 / maxLev of the external price
            Some(if self.ext_cap > 0.0 { v.clamp(x * (1.0 - self.ext_cap), x * (1.0 + self.ext_cap)) } else { v })
        } else { None };
        let oracle_of = |rr: f64| -> Px {
            if internal {
                // trade.xyz's internal oracle: EMA of the book toward which the oracle moves, dt capped at tau / 10
                let o0 = int_prev.unwrap_or(self.hist_o[n - 1] as f64 / 1e6);
                let tau = self.internal_tau;
                let a = 1.0 - (-(dt_s.min(0.1 * tau)) / tau).exp();
                // INTERNAL_CAP=c: the book input may sit at most c from the current oracle (0 = trade.xyz's rule, no cap)
                let gap = mid_now.unwrap_or(o0) - o0;
                let gap = if self.internal_cap > 0.0 { gap.clamp(-self.internal_cap * o0, self.internal_cap * o0) } else { gap };
                let v = o0 + a * gap;
                if self.p.clamp_o_bps == self.p.clamp_bps { self.clamp(v, rr, x) } else { self.clamp_o(v, rr, x) }
            } else if self.corrob {
                // ORACLE_CORROB=1: follow ext at once only as far as xyz's own book already is; beyond it, today's clamp c
                // per update. xyz's book can only speed up following ext, never move the oracle away from it.
                match mid_now { Some(m) => self.clamp_h(x, rr, m, x), None => self.clamp(x, rr, x) }
            } else if self.p.clamp_o_bps == self.p.clamp_bps { self.clamp(x, rr, x) } else { self.clamp_o(x, rr, x) }
        };
        let o = oracle_of(r);
        // m1: the oracle within the clamp of the mark the relayer read (the previous update's mark; RELAYER_RESID col 3
        // carries the relayer's view error of it)
        let pm = prev_mark.map(|v| v as f64 / 1e6);
        let m_ref = pm.map(|m| m + rin.map_or(0.0, |(_, _, r1)| if r1.is_nan() { 0.0 } else { r1 }));
        let m1 = self.mark_clamp(o, m_ref, x);
        if self.resid_out.is_some() {
            let (lo, hi) = self.band_h(r, r2, x);
            let m2r = real.1;
            // inside the band: the residual is observed. On an edge: the smallest residual that lands on the same edge
            // (the relayer's view was at least that far out). Outside the band: unexplained, NaN.
            let to = |px: Px| (px as f64 / 1e6 - x) - self.e;
            let mut entry = if !self.p.clamp_m2 || (m2r > lo && m2r < hi) {
                (to(m2r), 0)
            } else if m2r == lo {
                (to(lo).min(0.0), 0)
            } else if m2r == hi {
                (to(hi).max(0.0), 0)
            } else {
                (f64::NAN, 0)
            };
            // the real m2 outside the band of prep's lag: the relayer read an older oracle; find the lag that explains it
            if self.p.clamp_m2 && (m2r < lo || m2r > hi) {
                if let Some(k) = (1..=4u8).find(|&k| { let (l2, h2) = self.band(refp(k), x); m2r >= l2 && m2r <= h2 && self.mark_clamp(oracle_of(refp(k)), pm, x) == real.0 }) {
                    let (l2, h2) = self.band(refp(k), x);
                    entry = (if m2r > l2 && m2r < h2 { (m2r as f64 / 1e6 - x) - self.e } else { f64::NAN }, k);
                }
            }
            // m1's residual: the shift of the mark reference that reproduces the real m1 (0 if the plain one does).
            // Real m1 below the oracle: it sits on the upper edge M (1 + c); above: on the lower edge; equal: the
            // smallest shift that puts the oracle inside the band.
            let r1 = match pm {
                Some(m) if self.mark_clamp(o, Some(m), x) != real.0 => {
                    let (c, t) = (self.p.clamp_o_bps / 1e4, self.tick(real.0 as f64 / 1e6));
                    let (m1r, of) = (real.0 as f64 / 1e6, o as f64 / 1e6);
                    let mm = if m1r < of { (m1r + 0.5 * t) / (1.0 + c) } else if m1r > of { (m1r - 0.5 * t) / (1.0 - c) }
                             else if of > m * (1.0 + c) { of / (1.0 + c) } else { of / (1.0 - c) };
                    mm - m
                }
                _ => 0.0,
            };
            let entry = (entry.0, entry.1, r1);
            self.resid_out.as_mut().unwrap().push(entry);
        }
        let e = self.e + rin.map_or(0.0, |(r, _, _)| if r.is_nan() { 0.0 } else { r });
        let (r, r2) = if self.m2_ext { (x, x) } else { (r, r2) };
        let mut m2 = if self.p.clamp_m2 { self.clamp_h(x + e, r, r2, x) } else { self.round(x + e, 0) };
        let mut m1 = m1;
        // HL_CLAMP=1: HyperCore's 1% per update from the previous mark (never binds under the 50 bp clamp; needed when
        // the clamp is widened or removed)
        if self.hl_clamp {
            if let Some(pm) = prev_mark {
                let pm = pm as f64 / 1e6;
                let (pl, ph) = (self.round(pm * 0.99, 1), self.round(pm * 1.01, -1));
                m1 = m1.max(pl).min(ph);
                m2 = m2.max(pl).min(ph);
            }
        }
        self.hist.push(m1);
        self.hist2.push(m2);
        self.hist_o.push(o);
        if score {
            let t = (self.tick(real.1 as f64 / 1e6) * 1e6).round() as i64;
            self.score[0] += 1;
            self.score[1] += (m1 == real.0) as u64;
            self.score[2] += (m2 == real.1) as u64;
            self.score[3] += ((m2 - real.1).abs() <= t) as u64;
        }
        (m1, m2)
    }

    pub fn report(&self) {
        if let (Ok(f), Some(v)) = (std::env::var("RELAYER_RESID_OUT"), self.resid_out.as_ref()) {
            std::fs::write(&f, v.iter().map(|(x, k, r1)| format!("{x} {k} {r1}\n")).collect::<String>()).unwrap();
            let known = v.iter().filter(|x| !x.0.is_nan()).count();
            let lags = v.iter().filter(|x| x.1 > 0).count();
            let m1r = v.iter().filter(|x| x.2 != 0.0 && !x.2.is_nan()).count();
            println!("relayer residuals written: {} updates, {} with an observed residual, {} lag overrides, {} m1 reference shifts -> {f}", v.len(), known, lags, m1r);
        }
        let [n, a, b, c] = self.score;
        let d = n.max(1) as f64;
        println!("relayer (simulated{}, clamp {}bp tau {}s sample {}ms, scored 18:00-22:00): updates {n}  m1 exact {:.4}  m2 exact {:.4}  m2 within 1 tick {:.4}",
                 if self.resid_in.is_some() { " + residual" } else { "" }, self.p.clamp_bps, self.p.tau_s, self.p.sample_ms, a as f64 / d, b as f64 / d, c as f64 / d);
    }
}
