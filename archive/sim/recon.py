# Reconstruct isolated positions (size, entry, isolated margin) per address at T0 for an event coin.
import polars as pl, datetime as dt, sys
X='xyzdata/'
MAXLEV={'xyz:GOOGL':20,'xyz:AMZN':20,'xyz:INTC':10}
def recon(day, coin, T0):
    snapf={'2026-10-28':X+'snap1028/*.parquet','2026-10-29':X+'snap1029/*.parquet'}[day]
    allf={'2026-10-28':X+'all1028.parquet','2026-10-29':X+'all1029.parquet'}[day]
    s=pl.read_parquet(snapf).filter(pl.col('market')==coin).with_columns([pl.col(c).cast(float) for c in ['size','notional','entry_price','liquidation_price','leverage','account_value']])
    snap_ts=dt.datetime.fromtimestamp(int(pl.read_parquet(snapf).columns and __import__('glob').glob(snapf)[0].split('_')[-1].split('.')[0])/1000, dt.UTC).replace(tzinfo=None)
    mmr=1/(2*MAXLEV[coin])
    st={}
    for r in s.iter_rows(named=True):
        Q=r['size']; E=r['entry_price']; lp=r['liquidation_price']; iso=r['leverage_type']=='isolated'
        if iso and lp is not None and Q!=0:
            side=1 if Q>0 else -1; q=abs(Q)
            M=q*(mmr*lp - side*(lp-E))   # solves M + side*(lp-E)q = mmr*lp*q
        else: M=None
        st[r['user']]=dict(Q=Q,E=E,M=M,lev=r['leverage'],iso=iso,in_snap=True)
    f=pl.scan_parquet(allf).filter(pl.col('coin')==coin).with_columns(pl.col('timestamp').dt.replace_time_zone(None).alias('t')).filter(pl.col('t')>snap_ts,pl.col('t')<T0).select('address','t','side','price','size','direction','realized_pnl').collect().with_columns(pl.col('price').cast(float),pl.col('size').cast(float),pl.col('realized_pnl').cast(float)).sort('t')
    for r in f.iter_rows(named=True):
        a=r['address']; d=st.get(a)
        if d is None:
            d=st[a]=dict(Q=0.0,E=0.0,M=0.0,lev=float(MAXLEV[coin]),iso=None,in_snap=False)
        sgn=1 if r['side']=='buy' else -1; q=r['size']; p=r['price']
        Q0=d['Q']
        if Q0==0 or (Q0>0)==(sgn>0):   # open / add
            newQ=Q0+sgn*q
            d['E']=(abs(Q0)*d['E']+q*p)/abs(newQ)
            if d['M'] is not None: d['M']+=q*p/d['lev']
            d['Q']=newQ
        else:  # reduce (or flip)
            red=min(q,abs(Q0))
            if d['M'] is not None and abs(Q0)>0: d['M']*= (abs(Q0)-red)/abs(Q0)   # proportional margin release (assumption)
            d['Q']=Q0+sgn*q
            if abs(d['Q'])<1e-12: d['Q']=0.0
            elif (d['Q']>0)!=(Q0>0):  # flipped
                d['E']=p; d['M']=abs(d['Q'])*p/d['lev'] if d['M'] is not None else None
    rows=[dict(address=a,**v) for a,v in st.items() if v['Q']!=0]
    return pl.DataFrame(rows,infer_schema_length=None), snap_ts
if __name__=='__main__':
    for day,coin in [('2026-10-28','xyz:GOOGL'),('2026-10-29','xyz:INTC'),('2026-10-29','xyz:AMZN')]:
        P,ts=recon(day,coin,dt.datetime.fromisoformat(day+' 19:50:00'))
        P.write_parquet(f'pos_{coin.split(":")[1]}.parquet')
        L=P.filter(pl.col('Q')>0)
        print(coin,'snap',ts,'longs',L.height,'long ntl@E',round((L['Q']*L['E']).sum()/1e6,2),'M; iso known',L.filter(pl.col('iso')==True).height,'new (not in snap)',L.filter(~pl.col('in_snap')).height, 'new ntl',round((L.filter(~pl.col('in_snap'))['Q']*L.filter(~pl.col('in_snap'))['E']).sum()/1e6,2))
