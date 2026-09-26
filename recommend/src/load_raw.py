"""외래관광객조사 원자료(SAV)를 읽어 df.pkl / vl.pkl 로 저장.
원자료는 저장소에 올리지 않습니다. data/raw/ 에 *.SAV 파일을 직접 넣어 주세요."""
import glob, pickle, sys, os
import pyreadstat
raw = glob.glob(os.path.join(os.path.dirname(__file__), '..', 'data', 'raw', '*.SAV')) + glob.glob(os.path.join(os.path.dirname(__file__), '..', 'data', 'raw', '*.sav'))
if not raw:
    sys.exit('data/raw/ 에 2025 외래관광객조사 원자료(.SAV)가 없습니다. 외래객 단계는 건너뜁니다.')
df, meta = pyreadstat.read_sav(raw[0])
df.to_pickle('df.pkl')
pickle.dump(meta.variable_value_labels, open('vl.pkl', 'wb'))
print('loaded', raw[0], df.shape)
