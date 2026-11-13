import json,urllib.request,time,sys
A='0x4000000000000000000000000000000000000001'
def q(b):
  r=urllib.request.Request('https://api.hyperliquid.xyz/info',json.dumps(b).encode(),{'content-type':'application/json'});return json.load(urllib.request.urlopen(r))
def paged(typ,key='time'):
  out=[];t=1690000000000
  while True:
    b={'type':typ,'user':A,'startTime':t}
    if typ=='userFillsByTime': b['aggregateByTime']=False
    r=q(b)
    if not r: break
    out+=r; nt=max(x[key] for x in r)+1
    if nt<=t or len(r)<500 and typ!='userFillsByTime': 
      if len(r)<500: break
    t=nt; time.sleep(0.3)
    if len(r)<2000 and typ=='userFillsByTime': break
  return out
f=paged('userFillsByTime'); json.dump(f,open('bs_fills.json','w'))
l=paged('userNonFundingLedgerUpdates'); json.dump(l,open('bs_ledger.json','w'))
p=q({'type':'portfolio','user':A}); json.dump(p,open('bs_portfolio.json','w'))
print('fills',len(f),'ledger',len(l))
