import json
CATS=['역사·문화','힐링·생태','테마파크·액티비티','로컬·먹거리','해양·자연']
H,L,A,F,S=CATS
d=json.load(open('classified.json'))
W={'C1':[.1,.1,.3,.3,.2],'C2':[.1,.2,.1,.3,.3],'C3':[.1,.1,.5,.1,.2],'C4':[.5,.3,.05,.15,0],'C5':[.1,.6,0,.1,.2],'C6':[.2,.05,.05,.7,0],'C7':[.21,.03,.35,.27,.14],'C8':[.08,.26,0,.44,.23],'C9':[.02,.33,.07,.21,.36],'C10':[.31,.19,.19,.13,.18]}  # C9·C10: 외래 원자료 군집(k=6)의 카테고리 lift 비율  # C7·C8: 외래관광객조사 원자료 활동 lift로 보정
# hypothetical: (name, primary, secondary, night)
HYP={'[가상] 통영·남해 섬 로맨스':[('소매물도',S,L,0),('한산도 제승당',H,S,0),('동피랑 벽화마을',L,H,1),('통영 케이블카',A,S,0),('남해 다랭이마을',L,S,0),('남해 독일마을',H,L,0),('상주은모래비치',S,L,0),('통영 중앙시장',F,S,0),('강구안 야경 산책',S,F,1),('이순신공원',L,S,0),('남해 보리암',H,S,0),('미조항',F,S,0)],
'[가상] 키즈 애니 어드벤처':[('에버랜드',A,'',1),('한국민속촌',H,A,0),('레고랜드',A,'',0),('국립과천과학관',A,'',0),('헤이리 예술마을',L,A,0),('파주 퍼스트가든',A,L,1),('남이섬',L,A,0),('춘천 애니메이션박물관',A,H,0),('춘천 닭갈비골목',F,'',0),('국립수목원',L,'',0)],
'[가상] 대구·안동 먹방 예능 로드':[('서문시장 야시장',F,'',1),('안지랑 곱창골목',F,'',1),('김광석 다시그리기길',H,L,0),('안동 찜닭골목',F,'',0),('안동구시장',F,H,0),('하회마을',H,L,0),('월영교',L,'',1),('동성로',F,A,1),('83타워',A,'',1),('헛제사밥 까치구멍집',F,H,0)]}
def prof(pl):
  w=dict.fromkeys(CATS,0.);nt=0
  for _,p,s,n in pl:
    if s: w[p]+=.6;w[s]+=.4
    else: w[p]+=1
    nt+=n
  return [w[c]/len(pl) for c in CATS],nt/len(pl)
P={}
for t,v in d['prof'].items(): P[t]=dict(share=v['new'],old=v['old'],night=v['night'])
for t,pl in HYP.items():
  s,n=prof(pl); P[t]=dict(share=s,night=n,places=[[a,b,c,'야경' if e else ''] for a,b,c,e in pl])
for t in P: P[t]['fit']={k:sum(a*b for a,b in zip(w,P[t]['share'])) for k,w in W.items()}
# old fits for current themes
for t in d['prof']: P[t]['fit_old']={k:sum(a*b for a,b in zip(w,P[t]['old'])) for k,w in W.items()}
users=[('A 60대·배우자·천천히 (역사+자연)','C4',[0,1],0,5),('B 40대·아이 가족 (체험+바다)','C3',[2,4],0,3),('C 50대·친구·미식 (맛집+역사)','C6',[3,0],0,4),('D 20대·연인·핫플 (바다+야경)','C2',[4],1,1),('E 해외 20대·혼자·K팝 (K팝+공연)','C7',[],0,'C7'),('F 해외 30대·친구·뷰티 (맛집)','C8',[3],0,'C8'),('G 해외 30대·가족·자연 (자연+바다)','C9',[1,4],0,'C9'),('H 해외 60대·배우자·역사 (역사+체험)','C10',[0,2],0,'C10')]
SV=json.load(open('survey.json'));RL=SV['RL']
reg=lambda t,ai: max(-.05,min(.05,.1*(RL[t][ai]-1)))
FA=json.load(open('fa.json'))['reg']
def freg(t,c):
    rs=SV['TREG'][t]; a=sum(FA[r]['all'] for r in rs if r in FA); b=sum(FA[r][c] for r in rs if r in FA)
    return max(-.05,min(.05,.1*(b/a-1)))
U={}
for name,c,ints,night,ai in users:
  r=[(t,P[t]['fit'][c],.5*(sum(P[t]['share'][i] for i in ints)+(P[t]['night'] if night else 0)),(freg(t,ai) if isinstance(ai,str) else reg(t,ai))) for t in P]
  r.sort(key=lambda x:-(x[1]+x[2]+x[3])); U[name]=[(t,round(f,2),round(b,2),round(g,3),round(f+b+g,2)) for t,f,b,g in r]
  print(name); [print('  ',x) for x in U[name][:8]]
for t in P: print(t,[round(x,2) for x in P[t]['share']],round(P[t]['night'],2),{k:round(v,2) for k,v in P[t]['fit'].items()})
json.dump(dict(P=P,U=U,userc={u[0]:u[1] for u in users},cats=CATS),open('calc2.json','w'),ensure_ascii=False)
