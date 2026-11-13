import polars as pl, datetime as dt
X='xyzdata/'
E=321.673; MMR=1/40; BS=MMR*2/3
c=pl.read_parquet(X+'candles1028.parquet').filter(pl.col('coin')=='xyz:GOOGL').with_columns(pl.col('timestamp').dt.replace_time_zone(None).alias('t'),pl.col('close').cast(float)).sort('t')
L=pl.read_parquet(X+'liquidations/date=2026-10-28/fills.parquet').filter(pl.col('coin')=='xyz:GOOGL').with_columns(pl.col('timestamp').dt.replace_time_zone(None).alias('t'),pl.col('liquidation_mark_px').cast(float).alias('mk'))
marks=L.filter(pl.col('t').is_between(dt.datetime(2026,10,28,20,0),dt.datetime(2026,10,28,20,2,47))).group_by('t').agg(pl.col('mk').first()).sort('t')
print('observed marks:',[(r[0].strftime('%H:%M:%S.%f')[:-3],r[1]) for r in marks.iter_rows()])
def book(t): return c.filter(pl.col('t')<=t)['close'][-1]
def mark(t):
  m=marks.filter(pl.col('t')<=t)
  return (m['mk'][-1],'obs') if m.height and t>=dt.datetime(2026,10,28,20,2,25) else (book(t),'proxy')
# margin path (anchored at takeover: margin = transfer loss), realized losses + fees deducted, no release on reduce
M3=247705.2141; r2=(158814.0358,140.0725); r1=(112482.2146,111.1958); v=(71082.5582,85.4538)
M_r2=M3; M_r1=M3+sum(r2); M_v=M_r1+sum(r1); M0=M_v+sum(v)
print('margin before vol close',round(M0),' check from snapshot+opens+funding: 303862+298758-5213 =',303862+298758-5213)
T=lambda h,m,s,ms=0: dt.datetime(2026,10,28,h,m,s,ms*1000)
steps=[(T(19,50,0),37577.467,M0,'10 min before'),(T(19,55,0),37577.467,M0,''),(T(20,0,0),37577.467,M0,'close / earnings due'),
(T(20,1,55),37577.467,M0,'last second before drop'),(T(20,2,0),37577.467,M0,'drop starts (book)'),(T(20,2,10),37577.467,M0,''),
(T(20,2,25,665),37577.467,M0,'first GOOGL liquidation (any user)'),(T(20,2,31,0),37577.467,M0,''),
(T(20,2,37,709),37577.467,M0,'BEFORE whale own sell'),(T(20,2,37,710),32612.663,M_v,'AFTER whale sells 4,965 @307.36'),
(T(20,2,40,745),32612.663,M_v,'BEFORE liq round 1'),(T(20,2,40,746),26090.131,M_r1,'AFTER round 1 (20%) @304.43'),
(T(20,2,43,804),26090.131,M_r1,'BEFORE round 2'),(T(20,2,43,805),17820.519,M_r2,'AFTER round 2 (32%) @302.47'),
(T(20,2,46,731),17820.519,M_r2,'TAKEOVER by backstop @307.773')]
rows=[]
for t,Q,M,ev in steps:
  mk,src=mark(t); b=book(t); ntl=Q*mk; up=(mk-E)*Q; eq=M+up
  rows.append(dict(time=t.strftime('%H:%M:%S.%f')[:-3],mark=mk,src=src,book=b,pos=Q,ntl=round(ntl),margin=round(M),upnl=round(up),equity=round(eq),eq_pct=round(eq/ntl*100,2),MM=round(ntl*MMR),MM23=round(ntl*BS),eq_at_book=round(M+(b-E)*Q),liq_mark=round((E-M/Q)/(1-MMR),2),bs_mark=round((E-M/Q)/(1-BS),2),event=ev))
pl.Config.set_tbl_width_chars(300); pl.Config.set_tbl_rows(40); pl.Config.set_tbl_cols(20)
print(pl.DataFrame(rows))
