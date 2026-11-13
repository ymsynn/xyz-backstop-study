"""Counterfactual replay of xyz backstop events under a dynamic maintenance margin.
Mark and book paths are exogenous (observed); liquidation engine rules per HL docs:
  equity<MM -> market liquidation (20% if ntl>100k and not in 30s cooldown, else full)
  equity<2/3 MM -> backstop takeover at px = E - M/Q (trader zeroed)
Isolated longs only; cross accounts held at actual outcome."""
import polars as pl, datetime as dt, json, math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recon import recon, MAXLEV
X='xyzdata/'
EV={'GOOGL':('2026-10-28','xyz:GOOGL'),'INTC':('2026-10-29','xyz:INTC'),'AMZN':('2026-10-29','xyz:AMZN')}
def load(c):
    day,coin=EV[c]; dd=day.replace('-','')[4:]
    t0=dt.datetime.fromisoformat(day+' 19:50'); t1=dt.datetime.fromisoformat(day+' 21:45')
    cdl=pl.read_parquet(X+f'candles{dd}.parquet').filter(pl.col('coin')==coin).with_columns(pl.col('timestamp').dt.replace_time_zone(None).alias('t'),pl.col('close').cast(float)).filter(pl.col('t').is_between(t0-dt.timedelta(minutes=5),t1)).sort('t').select('t','close')
    L=pl.read_parquet(X+f'liquidations/date={day}/fills.parquet').filter(pl.col('coin')==coin).with_columns(pl.col('timestamp').dt.replace_time_zone(None).alias('t'),pl.col('liquidation_mark_px').cast(float).alias('mk'),pl.col('price').cast(float),pl.col('size').cast(float),pl.col('start_position').cast(float))
    A=pl.scan_parquet(X+f'all{dd}.parquet').filter(pl.col('coin')==coin).with_columns(pl.col('timestamp').dt.replace_time_zone(None).alias('t')).filter(pl.col('t').is_between(t0,t1)).select('address','t','side','price','size','direction','liquidation_method').collect().with_columns(pl.col('price').cast(float),pl.col('size').cast(float))
    return day,coin,t0,t1,cdl,L,A
def book_fn(cdl):
    ts=cdl['t'].to_list(); px=cdl['close'].to_list()
    import bisect
    def b(t):
        i=bisect.bisect_right(ts,t)-1; return px[max(i,0)]
    return b
def mark_path(cdl,L,t0,t1):
    b=book_fn(cdl)
    obs=L.filter(pl.col('t').is_between(t0,t1)).group_by('t').agg(pl.col('mk').first()).sort('t')
    ot=obs['t'].to_list(); om=obs['mk'].to_list()
    # pre-drop reference: book 60s before first obs drop... use first obs and back-extrapolate 0.5%/3s, capped at book
    t_first=ot[0]; m_first=om[0]
    ticks=[]; t=t_first
    k=0
    def bmax(t):
        return max(b(t-dt.timedelta(seconds=x)) for x in range(0,61,3))
    while t>t0: t-=dt.timedelta(seconds=3); k+=1; ticks.append((t, min(bmax(t), m_first*1.005**k)))
    ticks=ticks[::-1]
    # forward: observed when present, else clamp toward book
    path=list(ticks)
    m=m_first; t=t_first; j=0
    path.append((t,m))
    while t<t1:
        t2=t+dt.timedelta(seconds=3)
        # snap to observed tick if one falls in (t, t2+1.5s]
        while j<len(ot) and ot[j]<=t: j+=1
        if j<len(ot) and ot[j]<=t2+dt.timedelta(seconds=1.5):
            t=ot[j]; m=om[j]; j+=1
        else:
            t=t2; tgt=b(t); m=min(max(tgt,m*0.995),m*1.005)
        path.append((t,m))
    # pre-drop: before the stepping started the mark tracks the book; ensure ticks before onset use book
    return path,b
def calib(coin,L,cdl,bs_fills,b):
    m=L.filter(pl.col('liquidation_method')=='market')
    s_liq=((m['price']/pl.Series([b(t-dt.timedelta(seconds=1)) for t in m['t']])-1)*m['price']*m['size']).sum()/(m['price']*m['size']).sum()
    v=bs_fills.filter(pl.col('coin')==coin,~pl.col('dir').str.starts_with('Liquidated'))
    s_v=((v['px']/pl.Series([b(t) for t in v['t']])-1)*v['px']*v['sz']).sum()/(v['px']*v['sz']).sum()
    return s_liq,s_v
def unwind_schedule(coin,day,bs_fills):
    f=bs_fills.filter(pl.col('coin')==coin,pl.col('t').dt.date()==dt.date.fromisoformat(day)).sort('t')
    tk=f.filter(pl.col('dir').str.starts_with('Liquidated')); u=f.filter(~pl.col('dir').str.starts_with('Liquidated'))
    t_start=tk['t'].min(); tot=u['sz'].sum()
    sch=[((r[0]-t_start).total_seconds(), r[1]/tot) for r in u.select('t','sz').iter_rows()]
    return sch
def universe(c,day,coin,t0,L,A,mmr):
    P,_=recon(day,coin,t0)
    P=P.filter(pl.col('Q')>0)
    liq_first=L.filter(pl.col('direction').str.contains('Long')).sort('t').group_by('address').agg(pl.col('mk').first().alias('mk1'),pl.col('direction').first().alias('d1'),pl.col('start_position').first().alias('q1'))
    cross_liq=set(L.filter(pl.col('direction')=='Liquidated Cross Long')['address'].to_list())
    acc={}
    for r in P.iter_rows(named=True):
        if r['address'] in cross_liq: continue
        if r['iso'] is True and r['M'] is not None: acc[r['address']]=dict(Q=r['Q'],E=r['E'],M=r['M'],lev=r['lev'],src='snap')
    # liquidated isolated accounts not covered: calibrate margin from first liquidation mark
    for r in liq_first.iter_rows(named=True):
        a=r['address']
        if a in cross_liq or a in acc: continue
        p=P.filter(pl.col('address')==a)
        if p.height==0: continue
        Q=p['Q'][0]; E=p['E'][0]; mk=r['mk1']
        M=Q*(E-mk*(1-mmr))+Q*mk*mmr*0.0  # equity==MM at trigger mark
        M=Q*(mmr*mk-(mk-E))
        acc[a]=dict(Q=Q,E=E,M=max(M,0.0),lev=p['lev'][0],src='liqcal')
    vol=A.filter(pl.col('address').is_in(list(acc.keys())),pl.col('liquidation_method').is_null()).sort('t')
    return acc,vol
def run(c,Lnew=None,resp='min',book='works',switch_min=10,verbose=False,cache={}):
    if c not in cache:
        day,coin,t0,t1,cdl,L,A=load(c)
        bs=pl.DataFrame(json.load(open('bs_fills.json')),infer_schema_length=None).with_columns(pl.from_epoch('time',time_unit='ms').alias('t'),pl.col('px').cast(float),pl.col('sz').cast(float))
        path,b=mark_path(cdl,L,t0,t1)
        mmr0=1/(2*MAXLEV[coin])
        s_liq,s_v=calib(coin,L,cdl,bs,b)
        sch=unwind_schedule(coin,day,bs)
        acc,vol=universe(c,day,coin,t0,L,A,mmr0)
        mk=L.filter(pl.col('liquidation_method')=='market').group_by('t').agg((pl.col('price')*pl.col('size')).sum().alias('n'))
        cap={r[0]:r[1] for r in mk.iter_rows()}
        cap_default=float(mk['n'].median()) if mk.height else 0.0
        cache[c]=(day,coin,t0,t1,path,b,s_liq,s_v,sch,acc,vol,mmr0,cap,cap_default)
    day,coin,t0,t1,path,b,s_liq,s_v,sch,acc0,vol,mmr0,cap,cap_default=cache[c]
    L0=MAXLEV[coin]; Lx=Lnew or L0; mmr=1/(2*Lx)
    acc={a:dict(v) for a,v in acc0.items()}
    forced=0.0; topup=0.0
    ts=t0
    for a,d in acc.items():
        d['cool']=None; d['dead']=False
        p=b(ts); N=d['Q']*p; eq=d['M']+(p-d['E'])*d['Q']
        if Lx<L0:
            if resp=='min' and eq<mmr*N:            # forced partial liquidation in calm book down to eq=MM'
                newQ=max(eq,0)/(mmr*p); forced+=(d['Q']-newQ)*p
                d['M']-= (d['Q']-newQ)*(d['E']-p)   # realize PnL on the reduced part (stays in iso margin)
                d['Q']=newQ
            elif resp=='im' and eq<N/Lx:            # trader tops up to new initial margin
                topup+=N/Lx-eq; d['M']+=N/Lx-eq
    # event loop over mark ticks with voluntary trades interleaved
    vt=vol.iter_rows(named=True); nxt=next(vt,None)
    takes=[]; booksold=0.0
    for (t,m) in path:
        if t<ts: continue
        while nxt is not None and nxt['t']<=t:
            d=acc.get(nxt['address'])
            if d and not d['dead'] and d['Q']>0:
                q=nxt['size']; p=nxt['price']
                if nxt['side']=='sell':
                    q=min(q,d['Q']); d['M']-=q*(d['E']-p); d['Q']-=q
                else:
                    d['E']=(d['Q']*d['E']+q*p)/(d['Q']+q); d['M']+=q*p/min(d['lev'],Lx); d['Q']+=q
                if d['Q']<=1e-9: d['dead']=True
            nxt=next(vt,None)
        bp=b(t); want=[]
        for a,d in acc.items():
            if d['dead'] or d['Q']<=0: continue
            N=d['Q']*m; eq=d['M']+(m-d['E'])*d['Q']
            if eq<(2/3)*mmr*N:
                px=d['E']-d['M']/d['Q']
                takes.append((t,d['Q'],px,a)); d['dead']=True
            elif eq<mmr*N:
                incool=d['cool'] is not None and (t-d['cool']).total_seconds()<30
                q=d['Q'] if (N<=1e5 or incool) else 0.2*d['Q']
                if not incool and N>1e5: d['cool']=t
                want.append((d,q))
        if want and book!='dead':
            tot=sum(q for _,q in want)*bp
            C=float('inf') if book=='works' else cap.get(t, cap_default)
            phi=min(1.0, C/tot) if tot>0 else 0
            px=bp*(1+s_liq)
            for d,q in want:
                q*=phi; d['M']-=q*(d['E']-px); d['Q']-=q; booksold+=q*px
                if d['Q']<=1e-9: d['dead']=True
    if not takes: return dict(L=Lx,resp=resp,book=book,take=0,pnl=0,n=0,forced=forced,topup=topup,booksold=booksold)
    t_first=min(x[0] for x in takes)
    pnl=0.0; take=0.0
    for (t,q,px,a) in takes:
        take+=q*px
        for (off,fr) in sch:
            tu=t+dt.timedelta(seconds=off); pnl+=q*fr*(b(tu)*(1+s_v)-px)
    return dict(L=Lx,resp=resp,book=book,take=take,pnl=pnl,n=len(takes),forced=forced,topup=topup,booksold=booksold,whale=[x for x in takes if x[3].startswith('0x30afce')][:1])
if __name__=='__main__':
    for c in ['GOOGL','INTC','AMZN']:
        for bk in ['cap','works','dead']:
            r=run(c,book=bk); print(c,bk,{k:(round(v) if isinstance(v,float) else v) for k,v in r.items()})
