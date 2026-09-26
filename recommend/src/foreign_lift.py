import pandas as pd, numpy as np, math, json, pickle
df=pd.read_pickle('df.pkl'); vl=pickle.load(open('vl.pkl','rb'))
d=df[df.Q1==1].copy(); w=d['weight']
sel=lambda c: d[c].notna()
d['C7']=sel('Q8a08'); d['C8']=sel('Q8a13')|sel('Q8a14')
lab=pd.read_pickle('labels.pkl')  # foreign_cluster.py k=6 결과
d['C9']=lab==2; d['C10']=lab.isin([1,3,5])
def wmean(mask,sub=None):
    m=mask if sub is None else mask[sub]; ww=w if sub is None else w[sub]
    return float((ww*m).sum()/ww.sum())
def score(l): return 0 if l<=0 else max(0,min(3,math.floor(2*math.log2(l)+.5)))
out={'n':int(len(d)),'n_all':int(len(df))}
out['share']={c:wmean(d[c]) for c in ['C7','C8','C9','C10']}
out['overlap']=wmean(d.C7&d.C8)
# option masks
age=d.D_AGE
opts={}
for k,l in [(1,'10대'),(2,'20대'),(3,'30대'),(4,'40대'),(5,'50대'),(6,'60대 이상')]: opts[('Q1',l)]=age==k
opts[('Q2','혼자')]=sel('Q7a_dk'); opts[('Q2','친구와')]=sel('Q7a6'); opts[('Q2','연인·배우자와')]=sel('Q7a2'); opts[('Q2','아이와 가족')]=sel('Q7a4'); opts[('Q2','부모님과')]=sel('Q7a3')
A={'식도락':'Q8a01','쇼핑':'Q8a02','자연경관':'Q8a03','휴양·웰니스':'Q8a04','고궁·역사':'Q8a05','전통문화체험':'Q8a06','박물관·전시':'Q8a07','K팝·한류·촬영지':'Q8a08','공연 관람':'Q8a09','지역 축제':'Q8a10','뷰티·미용':'Q8a13','치료·건강검진':'Q8a14','레포츠 참가':'Q8a16'}
for k,v in A.items(): opts[('활동',k)]=sel(v)
r=d.RDAY전체TOT_RAW61
for k,l in [(1,'1일 $50 이하'),(2,'$50~100'),(3,'$100~300'),(4,'$300~500'),(5,'$500 초과')]: opts[('1일 지출',l)]=r==k
inet=d.Q4a1==1; sns=inet&d.Q4_1a1.isin([5,6])
opts[('Q9','재방문(가 본 경험)')]=d.RVIT>1
opts[('Q9','지인 추천')]=d.Q4a1==4; opts[('Q9','인터넷·앱')]=inet&~sns; opts[('Q9','SNS·유튜브')]=sns; opts[('Q9','정보 없이')]=d.Q4a1==9
opts[('여행형태','개별여행')]=d.TYP==1; opts[('여행형태','단체여행')]=d.TYP==3
opts[('성별','여성')]=d.D_SEX==2
res=[]
for (q,o),m in opts.items():
    base=wmean(m); row={'q':q,'opt':o,'all':base}
    for c in ['C7','C8','C9','C10']:
        pc=wmean(m,d[c]); l=pc/base if base>0 else 0; row[c]=pc; row[c+'_lift']=l; row[c+'_score']=score(l)
    res.append(row)
out['opts']=res
# regions
R={'서울':'Q9_2a01','경기':'Q9_2a02','인천':'Q9_2a03','강원':'Q9_2a04','경북':'Q9_2a09','경남':'Q9_2a10','대구':'Q9_2a11','부산':'Q9_2a13','전북':'Q9_2a15','전남':'Q9_2a16','제주':'Q9_2a17'}
out['reg']={k:{'all':wmean(sel(v)),**{c:wmean(sel(v),d[c]) for c in ['C7','C8','C9','C10']}} for k,v in R.items()}
# nationality
nat={}
for k,l in vl['D_NAT'].items():
    m=d.D_NAT==k
    if m.sum()<150: continue
    nat[l.replace(' ','')]={'n':int(m.sum()),**{c:wmean(d[c],m) for c in ['C7','C8','C9','C10']}}
out['nat']=nat
# mean spend
out['spend']={c:float(np.average(d.loc[d[c]&d.MDAY전체TOT_RAW61.notna(),'MDAY전체TOT_RAW61'],weights=w[d[c]&d.MDAY전체TOT_RAW61.notna()])) for c in ['C7','C8','C9','C10']}
mm=d.MDAY전체TOT_RAW61.notna(); out['spend']['all']=float(np.average(d.loc[mm,'MDAY전체TOT_RAW61'],weights=w[mm]))
json.dump(out,open('fa.json','w'),ensure_ascii=False,indent=0)
print(out['n'],out['share'],out['overlap'],out['spend'])
for r in res: print(r['q'],r['opt'],round(r['all']*100,1),*[(c,round(r[c+'_lift'],2),r[c+'_score']) for c in ['C9','C10']])
for k,v in out['reg'].items(): print(k,{c:round(v[c]/v['all'],2) for c in ['C7','C8','C9','C10']})
for k,v in sorted(nat.items(),key=lambda x:-x[1]['n']): print(k,v['n'],*[round(v[c]*100,1) for c in ['C7','C8','C9','C10']])
