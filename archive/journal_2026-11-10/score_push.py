"""Crash book push (GOOGL 10-28): python score_push.py DIR MARK [MARK ...]. Lift vs the same mark without the push; vault capital need."""
import polars as pl, os, json, sys, numpy as np
T=sys.argv[1]; MKS=sys.argv[2:]
ML={u["name"][4:]:u["maxLeverage"] for u in json.load(open("data/xyzmeta.json"))[0]["universe"]}
def marks(T,n):
    o=pl.read_csv(f"{T}/orc_{n}.csv").drop_nulls(["bid","ask","last"]).sort("h")
    raw=np.median(np.stack([o["m1"].to_numpy(),o["m2"].to_numpy(),np.median(np.stack([o["bid"].to_numpy(),o["ask"].to_numpy(),o["last"].to_numpy()]),axis=0)]),axis=0)/1e6
    m=raw.copy()
    for i in range(1,len(m)): m[i]=min(max(raw[i],m[i-1]*0.99),m[i-1]*1.01)
    return o.select("h","ms").with_columns(mk=pl.Series(m))
def ntl(T,n): return float((lambda t:(t["q"].abs()*t["px"]).sum())(pl.read_csv(f"{T}/tk_{n}.csv"))) if os.path.getsize(f"{T}/tk_{n}.csv")>0 else 0.0
def vault(T,n,L,kind="liq"):
    nm=(lambda k: f"{T}/{k}_{n}.csv")
    tk=pl.read_csv(nm("tk")) if os.path.getsize(nm("tk"))>0 else None
    r=dict(tk=tk.height if tk is not None else 0, ntl_k=round(float((tk["q"].abs()*tk["px"]).sum())/1e3,1) if tk is not None and tk.height else 0.0, need_k=0.0, adl_k=0.0)
    lg=pl.read_csv(nm("log")) if os.path.exists(nm("log")) and os.path.getsize(nm("log"))>0 else None
    if lg is not None and lg.height:
        o=marks(T,n).rename({"mk":"mark"})
        f=lg.join(o.select("h","ms"),on="h",how="left").with_columns(pl.col("ms").forward_fill().backward_fill()).with_columns(q=pl.when(pl.col("buy")==1).then(pl.col("sz")).otherwise(-pl.col("sz"))).sort("ms").with_columns(cq=pl.col("q").cum_sum(), cash=(-pl.col("q")*pl.col("px")).cum_sum())
        g=o.select("ms","mark").sort("ms").join_asof(f.select("ms","cq","cash"),on="ms").with_columns(pl.col("cq").fill_null(0.0),pl.col("cash").fill_null(0.0))
        val=(g["cash"]+g["cq"]*g["mark"]).to_numpy(); mm=(g["cq"].abs()*g["mark"]/(2*L)).to_numpy()
        r.update(need_k=round(max(0.0,float((mm-val).max()))/1e3,1), adl_k=round(max(0.0,float((-val).max()))/1e3,1))
    return r
def lift(T,c,MK,tg):
    j=marks(T,f"{c}_{MK}_{tg}").join(marks(T,f"{c}_{MK}_base"),on="h",suffix="_b").with_columns(g=(pl.col("mk")/pl.col("mk_b")-1)*1e4)
    return round(float(j["g"].max())), j.filter(pl.col("g").abs()>100).height*3
for MK in MKS:
    for tg in ("base","c5e6_f0.06_d60","c5e6_f0.06_d300"):
        v=vault(T,f"GOOGL_{MK}_{tg}",20); l=lift(T,"GOOGL",MK,tg) if tg!="base" else (0,0)
        print(f"{MK:12} {tg:18} lift bp {l[0]:5} secs>100bp {l[1]:4} inherited M {v['ntl_k']/1e3:6.1f} need M {v['need_k']/1e3:5.2f} adl M {v['adl_k']/1e3:5.2f}")
