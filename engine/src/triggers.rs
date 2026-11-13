//! Trigger (TP/SL) orders, simulated (TRIGGERS=simulate) instead of injecting their real fills.
//!
//! Fitted on GOOGL 2026-10-28 (SIMULATOR_SPEC.md, "Trigger orders"): a trigger fires at the first relayer update whose mark
//! crosses triggerPx (687 / 694 fired triggers exactly), before that update's liquidations:
//!   buy tp / sell sl: mark <= triggerPx        sell tp / buy sl: mark >= triggerPx
//! It then executes as an order of its own: IOC at the user's limit price for isMarket, GTC otherwise. The triggered
//! orders of one update run smallest size first (the whale's 37,577-share stop ran after 21 smaller ones).
//! normalTpsl children (waitingForFill) only become active once their parent order fills; they are dropped if the parent
//! is cancelled first. Size 0 means the whole position (positionTpsl and "close all" orders).

use crate::book::{Oid, Px, Sz, Uid};
use ahash::AHashMap;

pub const F_MARKET: i64 = 1;
pub const F_TP: i64 = 2;
pub const F_REDUCE: i64 = 4;
pub const F_WAIT_FILL: i64 = 32;

#[derive(Clone, Copy, Debug)]
pub struct Trig {
    pub oid: Oid,
    pub u: Uid,
    pub buy: bool,
    pub px: Px,
    pub sz: Sz,
    pub tpx: Px,
    pub flags: i64,
    pub parent: Oid,
    pub cl: u64,
    pub active: bool,
}

impl Trig {
    pub fn fires(&self, mark: Px) -> bool {
        if self.buy == (self.flags & F_TP != 0) { mark <= self.tpx } else { mark >= self.tpx }
    }
    pub fn tif(&self) -> u8 {
        if self.flags & F_MARKET != 0 { 2 } else { 1 }
    }
    pub fn reduce_only(&self) -> bool {
        self.flags & F_REDUCE != 0 || self.sz == 0
    }
}

#[derive(Default)]
pub struct TrigBook {
    by_oid: AHashMap<Oid, Trig>,
    by_cloid: AHashMap<(Uid, u64), Oid>,
    children: AHashMap<Oid, Vec<Oid>>,
    pub fired: Vec<(Oid, i64)>, // (oid, block) in firing order
    pub dropped_reduce: u64,
    pub log: Vec<(Trig, i64, Px, i64, Sz, i64)>, // fired trigger, block, mark, position (MIN = unknown), placed size, rested
}

impl TrigBook {
    pub fn add(&mut self, t: Trig) {
        if t.cl != 0 {
            self.by_cloid.insert((t.u, t.cl), t.oid);
        }
        if t.parent >= 0 && !t.active {
            self.children.entry(t.parent).or_default().push(t.oid);
        }
        self.by_oid.insert(t.oid, t);
    }

    pub fn remove(&mut self, oid: Oid) -> bool {
        match self.by_oid.remove(&oid) {
            Some(t) => {
                if t.cl != 0 { self.by_cloid.remove(&(t.u, t.cl)); }
                true
            }
            None => false,
        }
    }

    pub fn remove_cloid(&mut self, u: Uid, cl: u64) -> bool {
        match self.by_cloid.get(&(u, cl)).copied() {
            Some(o) => self.remove(o),
            None => false,
        }
    }

    /// scheduleCancel: every order of the user, triggers included.
    pub fn cancel_user(&mut self, u: Uid) {
        let v: Vec<Oid> = self.by_oid.values().filter(|t| t.u == u).map(|t| t.oid).collect();
        for o in v { self.remove(o); }
    }

    /// The parent order got a fill: its waiting children become live.
    pub fn parent_filled(&mut self, parent: Oid) {
        if let Some(ch) = self.children.remove(&parent) {
            for c in ch {
                if let Some(t) = self.by_oid.get_mut(&c) { t.active = true; }
            }
        }
    }

    /// The parent was modified into a new order: its waiting children follow the new oid.
    pub fn reparent(&mut self, old: Oid, new: Oid) {
        if let Some(ch) = self.children.remove(&old) {
            for c in &ch {
                if let Some(t) = self.by_oid.get_mut(c) { t.parent = new; }
            }
            self.children.entry(new).or_default().extend(ch);
        }
    }

    /// The parent was cancelled before any fill: its waiting children go with it.
    pub fn parent_cancelled(&mut self, parent: Oid) {
        if let Some(ch) = self.children.remove(&parent) {
            for c in ch { self.remove(c); }
        }
    }

    /// Live triggers whose condition holds at `mark`, removed from the book, in oid (placement) order.
    pub fn due(&mut self, mark: Px, h: i64) -> Vec<Trig> {
        let mut v: Vec<Trig> = self.by_oid.values().filter(|t| t.active && t.fires(mark)).copied().collect();
        v.sort_by_key(|t| t.oid);
        for t in &v {
            self.remove(t.oid);
            self.fired.push((t.oid, h));
        }
        v
    }
}
