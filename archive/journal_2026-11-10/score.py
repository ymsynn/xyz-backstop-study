"""Scorecard of one three-vote variant folder: python score.py LETTER (k | r | n). Run from the backstop root."""
import polars as pl, os, json, sys, numpy as np
X=sys.argv[1]; MK=f"pkgm3{X}1800"; DS=f"lead3{X}1800"; F="data/scen/tests_1110f"; K=f"{F}/{X}"
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
def tot(rows,keys): return {k:round(sum(r[k] for r in rows),1) for k in keys}
print("crashes", tot([vault(f"{K}/crash",f"{c}_{d}_{DS}",ML[c]) for c,d in (("GOOGL","1028"),("INTC","1029"),("AMZN","1029"))],("need_k","adl_k","ntl_k")))
print("SKHX", vault(f"{K}/skhx",f"SKHX_0727_{DS}",10))
print("iso ADL k", [(c,vault(f"{K}/iso",f"{c}_{d}_{DS}",10)["ntl_k"]) for c,d in (("NOW","1028"),("LITE","1028"),("MRVL","1028"),("RDDT","1029"),("NET","1105"))])
print("quiet inherited k", round(sum(vault(f"{K}/quiet",f"{c}_{d}_{DS}",ML[c])["ntl_k"] for c,d in (("GOOGL","1020"),("INTC","1020"),("AMZN","1020"),("GOOGL","1021"),("INTC","1021"),("AMZN","1021"))),1))
s=0
for c in ("GOOGL","INTC","AMZN"):
    f=f"{K}/freeze/tk_{c}_freeze_{MK}.csv"
    if os.path.getsize(f)>0: tk=pl.read_csv(f); s+=float((tk["q"].abs()*tk["px"]).sum())
print("stuck feed inherited M", round(s/1e6,2))
print("oos", tot([vault(f"{K}/oos",f"{c}_{d}_{MK}",ML[c]) for c,d in (("GOOGL","1022"),("META","1022"),("SILVER","1022"),("GOLD","1030"),("SPCX","1030"),("BRENTOIL","0910"),("CL","0910"))],("tk","ntl_k","need_k","adl_k")))
def lift(T,c,tg,lo=False):
    j=marks(T,f"{c}_{MK}_{tg}").join(marks(T,f"{c}_{MK}_base"),on="h",suffix="_b").with_columns(g=(pl.col("mk")/pl.col("mk_b")-1)*1e4)
    return round(float(j["g"].min() if lo else j["g"].max())), j.filter(pl.col("g").abs()>100).height*3
T=f"{K}/spike"
for tg in ("a30s","a3s","q30s"): print("bad print",tg,"mark bp",min(lift(T,c,tg,True)[0] for c in ("GOOGL","AMZN")),"extra tk k",round(sum(ntl(T,f"{c}_{MK}_{tg}")-ntl(T,f"{c}_{MK}_base") for c in ("GOOGL","AMZN"))/1e3))
for c,L in (("CL",20),("GOLD",25)):
    T=f"{F}/closed_{c}"; print(c,"closed: lift bp",[lift(T,c,tg)[0] for tg in ("c1e6_f0.06_d60","c5e6_f0.06_d900")],"takeover M",[round(ntl(T,f"{c}_{MK}_{tg}")/1e6,2) for tg in ("base","c1e6_f0.06_d900","c5e6_f0.06_d900")])
T=f"{F}/push"
if os.path.exists(f"{T}/orc_GOOGL_{MK}_base.csv"):
    for tg in ("c1e6_f0.06_d60","c5e6_f0.06_d60","c5e6_f0.06_d300"):
        v=vault(T,f"GOOGL_{MK}_{tg}",20); l=lift(T,"GOOGL",tg); print("crash push",tg,"lift bp",l[0],"secs>100bp",l[1],"inherited M",round(v["ntl_k"]/1e3,1),"need M",round(v["need_k"]/1e3,2),"adl M",round(v["adl_k"]/1e3,2))
