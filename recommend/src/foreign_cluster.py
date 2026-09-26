import pandas as pd, numpy as np, json
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
df=pd.read_pickle('df.pkl'); d=df[df.Q1==1].copy(); w=d.weight.values
sel=lambda c: d[c].notna().astype(float)
A={'식도락':'Q8a01','쇼핑':'Q8a02','자연경관':'Q8a03','휴양·웰니스':'Q8a04','고궁·역사':'Q8a05','전통문화체험':'Q8a06','박물관·전시':'Q8a07','K팝·한류·촬영지':'Q8a08','공연 관람':'Q8a09','지역 축제':'Q8a10','뷰티·미용':'Q8a13','치료·건강검진':'Q8a14'}
X=pd.DataFrame({k:sel(v) for k,v in A.items()})
comp={'혼자':'Q7a_dk','배우자/파트너':'Q7a2','자녀':'Q7a4','친구':'Q7a6'}
for k,v in comp.items(): X['동반_'+k]=sel(v)*0.7
for a,l in [(1,'10대'),(2,'20대'),(3,'30대'),(4,'40대'),(5,'50대'),(6,'60대+')]: X['연령_'+l]=(d.D_AGE==a).astype(float)*0.5
X['단체여행']=(d.TYP==3).astype(float)*0.7
X['1일$500+']=(d.RDAY전체TOT_RAW61==5).astype(float)*0.7
X['지방방문']=d.KWONB2.notna().astype(float)*0.7
Xv=X.values
rng=np.random.default_rng(0); idx=rng.choice(len(Xv),4000,replace=False)
res={}
for k in range(4,10):
    km=KMeans(k,n_init=10,random_state=0).fit(Xv,sample_weight=w)
    res[k]=(silhouette_score(Xv[idx],km.labels_[idx]),km)
    print(k,round(res[k][0],3))
k=6; km=res[k][1]; lab=km.labels_
raw=X.copy()
for c in raw.columns:
    if c.startswith('동반_'): raw[c]/=0.7
    if c.startswith('연령_'): raw[c]/=0.5
    if c in ('단체여행','1일$500+','지방방문'): raw[c]/=0.7
base=np.average(raw.values,axis=0,weights=w)
prof=[]
for c in range(k):
    m=lab==c; share=w[m].sum()/w.sum()
    rate=np.average(raw.values[m],axis=0,weights=w[m])
    lift=rate/np.where(base>0,base,1)
    order=np.argsort(-lift)
    top=[(raw.columns[i],round(rate[i]*100,1),round(lift[i],2)) for i in order[:7]]
    reg={}
    for r,v in {'서울':'Q9_2a01','부산':'Q9_2a13','제주':'Q9_2a17','강원':'Q9_2a04','경북':'Q9_2a09'}.items():
        reg[r]=round(float(np.average(d[v].notna().values[m],weights=w[m]))*100,1)
    spend=float(np.average(d.MDAY전체TOT_RAW61.fillna(d.MDAY전체TOT_RAW61.median()).values[m],weights=w[m]))
    fem=float(np.average((d.D_SEX==2).values[m],weights=w[m]))
    nat=d.D_NAT[m].value_counts().head(3).to_dict()
    prof.append(dict(c=c,share=share,top=top,reg=reg,spend=spend,fem=fem,rate={raw.columns[i]:float(rate[i]) for i in range(len(rate))}))
    print(c,round(share*100,1),top,reg,round(spend),round(fem,2),nat)
json.dump(dict(base={raw.columns[i]:float(base[i]) for i in range(len(base))},prof=prof,sil={k:float(v[0]) for k,v in res.items()}),open('fb.json','w'),ensure_ascii=False)
pd.Series(lab,index=d.index).to_pickle('labels.pkl')
