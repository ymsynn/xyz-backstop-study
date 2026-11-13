//! xyz HIP-3 market simulator engine.
//!
//! engine replay <prep_dir> [tape_walk|engine]                 block replay of the book + mark check (parity with replay_v1)
//! engine accounts <prep_dir> <maxlev> [rule=value ...]         replay (tape_walk) + account state + liquidation triggers
//! engine sim <prep_dir> <maxlev> [rule=value ...]              integrated: book + accounts + liquidation engine + vault

mod book;
mod clearing;
mod events;
mod io;
mod relayer;
mod replay;
mod triggers;
mod simreport;

use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let cmd = args.get(1).map(String::as_str).unwrap_or("");
    match cmd {
        "replay" => {
            let dir = &args[2];
            let mode = match args.get(3).map(String::as_str).unwrap_or("tape_walk") {
                "engine" => replay::Match::Engine,
                _ => replay::Match::TapeWalk,
            };
            let t0 = Instant::now();
            let mut r = replay::Replay::new(dir, mode);
            r.run(dir);
            r.report(dir);
            replay::mark_check(&r.orc, dir);
            eprintln!("elapsed {:.1}s", t0.elapsed().as_secs_f64());
        }
        "accounts" => {
            let dir = &args[2];
            let maxlev: f64 = args[3].parse().unwrap();
            let t0 = Instant::now();
            let mut r = replay::Replay::new(dir, replay::Match::TapeWalk);
            r.run(dir);
            replay::mark_check(&r.orc, dir);
            let t1 = Instant::now();
            let mut c = clearing::Clearing::new(dir, maxlev, clearing::Rules::from_args(&args[4..], maxlev));
            c.run(dir, &r.orc);
            eprintln!("elapsed book {:.1}s accounts {:.1}s", (t1 - t0).as_secs_f64(), t1.elapsed().as_secs_f64());
        }
        "sim" => {
            let dir = &args[2];
            let maxlev: f64 = args[3].parse().unwrap();
            let t0 = Instant::now();
            let mut r = replay::Replay::new(dir, if std::env::var("MATCH").as_deref() == Ok("engine") { replay::Match::Engine } else { replay::Match::TapeWalk });
            if let Some(rl) = r.relayer.as_mut() { rl.set_max_lev(maxlev); rl.set_internal(dir); }
            r.max_lev = maxlev;
            let mut c = clearing::Clearing::new(dir, maxlev, clearing::Rules::from_args(&args[4..], maxlev));
            c.integrated = true;
            c.endogenous = std::env::var("ENDO").map_or(true, |v| v != "0");
            r.endo = c.endogenous;
            r.run_with(dir, Some(&mut c));
            r.report(dir);
            replay::mark_check(&r.orc, dir);
            simreport::report(dir, &r, &c);
            eprintln!("elapsed {:.1}s", t0.elapsed().as_secs_f64());
        }
        _ => eprintln!("usage: engine replay <prep_dir> [tape_walk|engine] | engine accounts <prep_dir> <maxlev> [rule=value ...]"),
    }
}
