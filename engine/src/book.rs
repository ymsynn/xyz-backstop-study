//! Order-level limit order book for one coin: integer prices/sizes (1e6 scale), price-time priority.
//! Same semantics as replay_v1/book.py, with lazy deletion: orders live in a slab, a level keeps a queue of slab
//! indices plus a live count, removed orders are flagged dead and skipped (popped when they reach the front).

use ahash::AHashMap;
use std::collections::{BTreeMap, VecDeque};

pub type Px = i64;
pub type Sz = i64;
pub type Oid = i64;
pub type Uid = u32;

#[derive(Clone, Debug)]
pub struct Order {
    pub oid: Oid,
    pub user: Uid,
    pub buy: bool,
    pub px: Px,
    pub sz: Sz,
    pub cloid: u64,
    pub live: bool,
    pub ro: bool,
    /// priority rank (HL priority bid): {"p": 0} 0, "na" 1, {"p": N} N + 1
    pub prio: i32,
    /// arrival time (ms): the priority window is measured from it
    pub t_ms: i64,
}

#[derive(Default)]
pub struct Level {
    pub q: VecDeque<u32>,
    pub live: u32,
}

#[derive(Default)]
pub struct Book {
    pub slab: Vec<Order>,
    pub bids: BTreeMap<Px, Level>,
    pub asks: BTreeMap<Px, Level>,
    pub by_oid: AHashMap<Oid, u32>,
    pub by_cloid: AHashMap<(Uid, u64), Oid>,
    pub by_user: AHashMap<Uid, Vec<u32>>,
    /// Maker oids that got a fill, whatever the path (tape, matching, liquidation, vault), when `log_fills` is set:
    /// drained by the trigger book to activate normalTpsl children.
    pub log_fills: bool,
    pub cloid_unique: bool,
    pub cloid_evicted: u64,
    pub filled_log: Vec<Oid>,
    /// priority rank by oid (prio.arrow; absent = 1): {"p": 0} 0, "na" 1, {"p": N} N + 1
    pub prio: AHashMap<Oid, i32>,
    /// HL queues by arrival with a bid window: a new order goes ahead of the lower-bid orders at its price that arrived
    /// less than `prio_window_ms` before it (GOOGL 2026-10-28: every real jump within 398.8 ms, FIFO kept from 399.1 ms);
    /// otherwise strict FIFO. 0 = plain price-time.
    pub prio_window_ms: i64,
    /// current time (ms), set by the replay before placing
    pub now_ms: i64,
}

impl Book {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn best_bid(&self) -> Option<Px> {
        self.bids.keys().next_back().copied()
    }
    pub fn best_ask(&self) -> Option<Px> {
        self.asks.keys().next().copied()
    }

    /// Top-n levels (px, total size, n orders), best first.
    pub fn levels(&self, buy: bool, n: usize) -> Vec<(Px, Sz)> {
        let side = if buy { &self.bids } else { &self.asks };
        let it: Box<dyn Iterator<Item = (&Px, &Level)>> = if buy { Box::new(side.iter().rev()) } else { Box::new(side.iter()) };
        let mut out = Vec::with_capacity(n);
        for (px, lv) in it {
            let s: Sz = lv.q.iter().map(|&k| &self.slab[k as usize]).filter(|o| o.live).map(|o| o.sz).sum();
            if s > 0 {
                out.push((*px, s));
                if out.len() >= n {
                    break;
                }
            }
        }
        out
    }

    pub fn rest(&mut self, oid: Oid, user: Uid, buy: bool, px: Px, sz: Sz, cloid: u64) {
        self.rest_ro(oid, user, buy, px, sz, cloid, false);
    }

    #[allow(clippy::too_many_arguments)]
    pub fn rest_ro(&mut self, oid: Oid, user: Uid, buy: bool, px: Px, sz: Sz, cloid: u64, ro: bool) {
        let k = self.slab.len() as u32;
        let prio = self.prio.get(&oid).copied().unwrap_or(1);
        let (now, w) = (self.now_ms, self.prio_window_ms);
        self.slab.push(Order { oid, user, buy, px, sz, cloid, live: true, ro, prio, t_ms: now });
        let side = if buy { &mut self.bids } else { &mut self.asks };
        let lv = side.entry(px).or_default();
        // pass the trailing lower-bid orders that arrived within the window (dead entries count as passed)
        let mut at = lv.q.len();
        while at > 0 && w > 0 {
            let o = &self.slab[lv.q[at - 1] as usize];
            if o.live && !(o.prio < prio && now - o.t_ms < w) { break; }
            at -= 1;
        }
        if at == lv.q.len() { lv.q.push_back(k); } else { lv.q.insert(at, k); }
        lv.live += 1;
        self.by_oid.insert(oid, k);
        if cloid != 0 {
            if let Some(old) = self.by_cloid.insert((user, cloid), oid) {
                // a cloid is unique among a user's open orders: an older order still holding it is gone
                if self.cloid_unique && old != oid {
                    if let Some(k2) = self.by_oid.remove(&old) { self.kill(k2); self.cloid_evicted += 1; }
                    self.by_cloid.insert((user, cloid), oid);
                }
            }
        }
        self.by_user.entry(user).or_default().push(k);
    }

    fn kill(&mut self, k: u32) {
        let (buy, px, user, cloid, oid) = {
            let o = &mut self.slab[k as usize];
            if !o.live {
                return;
            }
            o.live = false;
            (o.buy, o.px, o.user, o.cloid, o.oid)
        };
        let side = if buy { &mut self.bids } else { &mut self.asks };
        if let Some(lv) = side.get_mut(&px) {
            lv.live -= 1;
            while let Some(&f) = lv.q.front() {
                if self.slab[f as usize].live {
                    break;
                }
                lv.q.pop_front();
            }
            if lv.live == 0 {
                side.remove(&px);
            }
        }
        if cloid != 0 && self.by_cloid.get(&(user, cloid)) == Some(&oid) {
            self.by_cloid.remove(&(user, cloid));
        }
    }

    /// Remove by oid (the order currently indexed under that oid). Returns true if an order was removed.
    pub fn remove(&mut self, oid: Oid) -> bool {
        match self.by_oid.remove(&oid) {
            Some(k) => {
                self.kill(k);
                true
            }
            None => false,
        }
    }

    fn remove_idx(&mut self, k: u32) {
        let oid = self.slab[k as usize].oid;
        if self.by_oid.get(&oid) == Some(&k) {
            self.by_oid.remove(&oid);
        }
        self.kill(k);
    }

    pub fn would_cross(&self, buy: bool, px: Px) -> bool {
        if buy {
            self.best_ask().map_or(false, |a| px >= a)
        } else {
            self.best_bid().map_or(false, |b| px <= b)
        }
    }

    /// Externally given fill (engine taker / tape) on a resting maker.
    pub fn fill_maker(&mut self, oid: Oid, sz: Sz) -> bool {
        match self.by_oid.get(&oid).copied() {
            None => false,
            Some(k) => {
                if self.log_fills { self.filled_log.push(oid); }
                let o = &mut self.slab[k as usize];
                o.sz -= sz;
                if o.sz <= 0 {
                    self.remove_idx(k);
                }
                true
            }
        }
    }

    /// resting (px, size) of a user's live orders
    pub fn user_orders(&self, user: Uid) -> Vec<(Px, Sz)> {
        self.slab.iter().filter(|o| o.live && o.user == user).map(|o| (o.px, o.sz)).collect()
    }

    pub fn cancel_user(&mut self, user: Uid) {
        if let Some(ks) = self.by_user.remove(&user) {
            for k in ks {
                if self.slab[k as usize].live {
                    self.remove_idx(k);
                }
            }
        }
    }

    /// Live orders of a level in priority order (slab indices).
    pub fn level_orders(&self, buy_side: bool, px: Px) -> Vec<u32> {
        let side = if buy_side { &self.bids } else { &self.asks };
        match side.get(&px) {
            Some(lv) => lv.q.iter().copied().filter(|&k| self.slab[k as usize].live).collect(),
            None => vec![],
        }
    }

    /// Level prices of a side, best first, within the taker limit.
    pub fn reachable_levels(&self, taker_buy: bool, limit: Px) -> Vec<Px> {
        if taker_buy {
            self.asks.range(..=limit).map(|(p, _)| *p).collect()
        } else {
            self.bids.range(limit..).rev().map(|(p, _)| *p).collect()
        }
    }


    /// Pure price-time match without touching the book (own orders skipped, as STP would expire them):
    /// fills (maker oid, maker user, px, sz) and the remaining size.
    pub fn dry_match(&self, buy: bool, px: Px, mut sz: Sz, taker: Uid) -> (Vec<(Oid, Uid, Px, Sz)>, Sz) {
        let mut fills = Vec::new();
        for lvl in self.reachable_levels(buy, px) {
            for k in self.level_orders(!buy, lvl) {
                if sz == 0 { return (fills, 0); }
                let o = &self.slab[k as usize];
                if o.user == taker { continue; }
                let f = sz.min(o.sz);
                fills.push((o.oid, o.user, lvl, f));
                sz -= f;
            }
        }
        (fills, sz)
    }

    /// Price-time match with reduce-only makers capped at their position (`pos`, signed, micro-units): a reduce-only
    /// maker only fills what reduces its position, and is cancelled when it would not reduce at all (HL's
    /// reduceOnlyCanceled). Self-trade prevention expires the maker. Returns (fills, remaining, reduce-only cancels).
    /// `ntl_cap`: optional cap on the taker's filled notional (1e6 * $), its margin limit at match time.
    pub fn match_order_caps(&mut self, buy: bool, px: Px, mut sz: Sz, taker: Uid, pos: &AHashMap<Uid, i64>, ntl_cap: Option<i64>) -> (Vec<(Oid, Uid, Px, Sz)>, Sz, u64) {
        let mut fills = Vec::new();
        let mut ntl_left: i128 = ntl_cap.map_or(i128::MAX, |c| c as i128);
        let mut delta: AHashMap<Uid, i64> = AHashMap::new();
        let mut ro_cancel = 0u64;
        while sz > 0 {
            let lvl = if buy { self.best_ask() } else { self.best_bid() };
            let lvl = match lvl {
                Some(l) if (buy && l <= px) || (!buy && l >= px) => l,
                _ => break,
            };
            let mut progressed = false;
            for k in self.level_orders(!buy, lvl) {
                if sz == 0 { break; }
                let (u, msz, moid, mro, mbuy) = { let o = &self.slab[k as usize]; (o.user, o.sz, o.oid, o.ro, o.buy) };
                if u == taker { self.remove_idx(k); progressed = true; continue; }
                let mut allow = msz;
                if mro {
                    let p = pos.get(&u).copied().unwrap_or(0) + delta.get(&u).copied().unwrap_or(0);
                    let room = if mbuy { (-p).max(0) } else { p.max(0) };
                    if room == 0 { self.remove_idx(k); ro_cancel += 1; progressed = true; continue; }
                    allow = msz.min(room);
                }
                let f = sz.min(allow).min((ntl_left.saturating_mul(1_000_000) / lvl.max(1) as i128).min(i64::MAX as i128) as i64);
                if f <= 0 { sz = 0; break; }   // margin exhausted: the rest of the order is cancelled
                ntl_left -= (f as i128 * lvl as i128) / 1_000_000;
                if self.log_fills { self.filled_log.push(moid); }
                fills.push((moid, u, lvl, f));
                *delta.entry(u).or_default() += if mbuy { f } else { -f };
                sz -= f;
                self.slab[k as usize].sz -= f;
                progressed = true;
                if self.slab[k as usize].sz == 0 { self.remove_idx(k); }
            }
            if !progressed { break; }
        }
        (fills, sz, ro_cancel)
    }

    /// Same as match_order, also returning each maker's user: (maker oid, maker user, px, sz).
    pub fn match_order_u(&mut self, buy: bool, px: Px, mut sz: Sz, taker: Uid) -> (Vec<(Oid, Uid, Px, Sz)>, Sz) {
        let mut fills = Vec::new();
        while sz > 0 {
            let lvl = if buy { self.best_ask() } else { self.best_bid() };
            let lvl = match lvl {
                Some(l) if (buy && l <= px) || (!buy && l >= px) => l,
                _ => break,
            };
            for k in self.level_orders(!buy, lvl) {
                if sz == 0 {
                    break;
                }
                let (u, msz, moid) = {
                    let o = &self.slab[k as usize];
                    (o.user, o.sz, o.oid)
                };
                if u == taker {
                    self.remove_idx(k);
                    continue;
                }
                let f = sz.min(msz);
                if self.log_fills { self.filled_log.push(moid); }
                fills.push((moid, u, lvl, f));
                sz -= f;
                self.slab[k as usize].sz -= f;
                if self.slab[k as usize].sz == 0 {
                    self.remove_idx(k);
                }
            }
        }
        (fills, sz)
    }

    /// Remove every order on `buy_side` strictly better than px. Returns the number removed.
    pub fn prune_better(&mut self, buy_side: bool, px: Px) -> usize {
        let lv: Vec<Px> = if buy_side {
            self.bids.range(px + 1..).map(|(p, _)| *p).collect()
        } else {
            self.asks.range(..px).map(|(p, _)| *p).collect()
        };
        let mut n = 0;
        for p in lv {
            for k in self.level_orders(buy_side, p) {
                self.remove_idx(k);
                n += 1;
            }
        }
        n
    }
}
