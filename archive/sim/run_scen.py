import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import polars as pl
from sim_mm import run
rows=[]
for c,levs in [('GOOGL',[20,15,10,7,5]),('INTC',[10,7,5,3]),('AMZN',[20,15,10,7,5])]:
    base=run(c,book='cap')
    for L in levs:
        for resp in (['min'] if L==levs[0] else ['min','im']):
            for bk in ['cap','dead']:
                r=run(c,Lnew=L,resp=resp,book=bk)
                rows.append(dict(event=c,maxLev=L,MM=f'{100/(2*L):.2f}%',resp=resp if L!=levs[0] else 'base',book=bk,bs_take_M=round(r['take']/1e6,2),bs_pnl_k=round(r['pnl']/1e3,1),n_taken=r['n'],forced_reduce_M=round(r['forced']/1e6,2),topup_M=round(r['topup']/1e6,2)))
df=pl.DataFrame(rows); df.write_csv('scen_results.csv')
pl.Config.set_tbl_rows(80); pl.Config.set_tbl_width_chars(200)
print(df.filter(pl.col('book')=='cap'))
print(df.filter(pl.col('book')=='dead').select('event','maxLev','resp','bs_take_M','bs_pnl_k'))
