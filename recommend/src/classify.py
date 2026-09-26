import csv, re, json, collections
import os
from pathlib import Path
R = ''  # run_all.py가 작업 폴더를 data/derived로 맞춤
# 앱 레포 루트. 이 폴더가 data-server/recommend/ 로 옮겨오면서 상위 폴더가 더 이상
# 앱 레포가 아니게 됐다. data-server 와 나란히 있는 Tour-Navigator-App 을 기본값으로
# 보고, 다른 위치면 APP_REPO 환경변수로 지정한다.
_here = Path(__file__).resolve()
A = os.environ.get('APP_REPO',
                   str(_here.parents[3] / 'Tour-Navigator-App')).rstrip('/') + '/'
CODE = {'herit': '역사·문화', 'heal': '힐링·생태', 'activity': '테마파크·액티비티', 'food': '로컬·먹거리', 'sea': '해양·자연', 'stay': '숙박'}
CATS = ['역사·문화', '힐링·생태', '테마파크·액티비티', '로컬·먹거리', '해양·자연']
THEMES = [('왕과 사는 남자', 'Kings Warden Route'), ('케이팝 데몬 헌터스', 'KPop Demon Hunters Route'), ('RESCENE Route', 'RESCENE Route'),
          ('제주 K-Drama', 'Jeju K-Drama Route'), ('부산 영화 기행', 'Busan Cinema Route')]

SEA_NAME = re.compile(r'해수욕장|해변|해안|포구|등대|방파제|해상|몽돌|갯벌|해녀|용궁|바다|오션|해중|비치|곶|항$|항\s|항·|태종대|오륙도|동백섬|일출봉|용두암|해식')
ISLAND = re.compile(r'섬($|\s|·)|도$')
SEA_DESC = re.compile(r'바다|해안|해변|파도|수평선|갯벌|포구|항구|등대|섬')
KW = {
    '역사·문화': r'사$|사찰|암$|궁|릉|능$|성$|산성|읍성|서원|향교|고택|한옥|유적|박물관|문화재|탑|성당|기념관|왕|조선|신라|백제|고려|역사|관아|종가|마을',
    '힐링·생태': r'숲|공원|수목원|계곡|폭포|호수|둘레길|오름|휴양림|온천|정원|산책|강변|생태|꽃|습지|산$|봉$',
    '로컬·먹거리': r'시장|골목|먹자|맛집|카페|식당|빵|음식|거리$|노포|야시장',
    '테마파크·액티비티': r'테마파크|랜드|월드|케이블카|레일바이크|체험|과학관|짚라인|루지|전망대|타워|아쿠아리움|동물원|스카이|경기장|미디어아트|놀이',
}
NIGHT = re.compile(r'야경|야시장|대교|타워|야간|조명|불빛|밤|night', re.I)
INDOOR = re.compile(r'박물관|미술관|과학관|전시|아쿠아리움|백화점|기념관|실내|공연장|영화의전당|몰$|아트센터|미디어아트|센텀')
FILM = re.compile(r'촬영|드라마|영화|뮤직비디오|MV|장면|씬')
WALK_HI = re.compile(r'(산|봉)$|오름|둘레길|등산|트레킹|올레|정상|계단|능선')
WALK_MID = re.compile(r'공원|산책|길$|길\s|해안|숲|수목원|마을|섬|성곽|골목')

def classify(name, cur, desc, in_theme):
    text = name + ' ' + desc
    notes = []
    if cur == '숙박' or (not cur and re.search(r'숙소|호텔|리조트|스테이|펜션|게스트하우스', name)):
        return dict(primary='숙박', secondary='', tags='', walk='', changed='', review='', note='숙박 — 테마 계산 제외')
    primary, secondary, review = cur, '', ''
    sea_d = bool(SEA_DESC.search(desc))
    sea_n = bool(SEA_NAME.search(name)) or (bool(ISLAND.search(name)) and bool(re.search(r'바다|해안|해변|포구|항구|배를|여객선|파도', desc)))
    if not cur:
        scores = {c: len(re.findall(p, text)) for c, p in KW.items()}
        if sea_n: primary = '해양·자연'
        elif max(scores.values()) > 0: primary = max(scores, key=scores.get)
        else: primary = '힐링·생태'
        review = 'Y'; notes.append('원래 분류 없음 → 규칙으로 채움')
    elif sea_n and cur in ('힐링·생태',):
        primary, secondary = '해양·자연', '힐링·생태'; notes.append('바닷가 장소 → 주 카테고리 해양으로 변경')
    if primary != '해양·자연' and not secondary and (sea_n or sea_d):
        secondary = '해양·자연'; notes.append('바다 관련 → 보조 해양')
        if not sea_n: review = 'Y'
    if not secondary:
        scores = {c: len(re.findall(p, text)) for c, p in KW.items() if c != primary}
        if scores and max(scores.values()) > 0:
            secondary = max(scores, key=scores.get); notes.append('키워드로 보조 지정')
    tags = []
    if primary == '해양·자연' or secondary == '해양·자연': tags.append('바다')
    if NIGHT.search(text): tags.append('야경')
    if INDOOR.search(text): tags.append('실내')
    if in_theme or FILM.search(desc): tags.append('촬영명소')
    walk = '상' if WALK_HI.search(name) else ('중' if WALK_MID.search(text) or primary in ('힐링·생태', '해양·자연') else '하')
    changed = 'Y' if cur and primary != cur else ''
    return dict(primary=primary, secondary=secondary, tags=', '.join(tags), walk=walk, changed=changed, review=review, note='; '.join(notes))

# theme records
theme_recs = {}
for tname, f in THEMES:
    s = open(A + f + '.dc.html', encoding='utf-8').read()
    recs = re.findall(r"ko:'([^']+)',en:'([^']*)',cat:'(\w+)',lat:([\d.]+),lng:([\d.]+)(.*?)\}", s)
    out = []
    for ko, en, cat, lat, lng, rest in recs:
        m = re.search(r"bKo:'([^']*)'", rest)
        out.append(dict(ko=ko, en=en, cat=CODE.get(cat, cat), lat=lat, lng=lng, desc=m.group(1) if m else ''))
    theme_recs[tname] = out
membership = collections.defaultdict(list)
for t, recs in theme_recs.items():
    for r in recs: membership[r['ko']].append(t)

rows, seen = [], set()
for x in csv.DictReader(open(A + 'assets/tour-places.csv', encoding='utf-8-sig')):
    n = x['장소명(한국어)']
    if n in seen: continue
    seen.add(n)
    rows.append(dict(src='장소 마스터', city=x['도시'], ko=n, en=x['장소명(영문)'], cur=x['분류'], lat=x['위도'], lng=x['경도'], desc=x['설명']))
for t, recs in theme_recs.items():
    for r in recs:
        if r['ko'] in seen: continue
        seen.add(r['ko'])
        rows.append(dict(src='테마 파일 (' + t + ')', city='', ko=r['ko'], en=r['en'], cur=r['cat'], lat=r['lat'], lng=r['lng'], desc=r['desc']))
for r in rows:
    r['themes'] = ', '.join(membership.get(r['ko'], []))
    r.update(classify(r['ko'], r['cur'], r['desc'], bool(r['themes'])))

# theme profiles (0.6 / 0.4), computed from theme files' own records
bycls = {r['ko']: r for r in rows}
def share_of(places):
    w = dict.fromkeys(CATS, 0.0); night = 0; n = 0
    for p in places:
        c = bycls[p]
        if c['primary'] == '숙박': continue
        n += 1
        if c['secondary']: w[c['primary']] += .6; w[c['secondary']] += .4
        else: w[c['primary']] += 1
        night += '야경' in c['tags']
    return [w[c] / n for c in CATS], night / n, n
def share_old(recs):
    w = dict.fromkeys(CATS, 0); n = 0
    for r in recs:
        if r['cat'] == '숙박': continue
        n += 1; w[r['cat']] += 1
    return [w[c] / n for c in CATS]
prof = {}
for t, recs in theme_recs.items():
    s, nt, n = share_of([r['ko'] for r in recs])
    prof[t] = dict(old=share_old(recs), new=s, night=nt, n=n)
json.dump(dict(rows=rows, prof=prof), open(R + 'classified.json', 'w'), ensure_ascii=False)
print(len(rows), collections.Counter(r['primary'] for r in rows), sum(r['changed'] == 'Y' for r in rows), sum(r['review'] == 'Y' for r in rows))
for t, v in prof.items(): print(t, v['n'], [round(x, 2) for x in v['old']], [round(x, 2) for x in v['new']], round(v['night'], 2))
