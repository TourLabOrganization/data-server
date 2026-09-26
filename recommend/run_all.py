"""전체 계산 파이프라인. 사용: python run_all.py  (외래객 원자료가 없으면 기존 fa.json/fb.json을 그대로 사용)"""
import os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'data' / 'derived'; OUT.mkdir(parents=True, exist_ok=True)
def run(name, optional=False):
    print(f'== {name}')
    r = subprocess.run([sys.executable, str(ROOT / 'src' / name)], cwd=OUT)
    if r.returncode and not optional: sys.exit(r.returncode)
    return r.returncode == 0
run('survey.py')                       # 국민여행조사 공표표 → survey.json
if run('load_raw.py', optional=True):  # 외래관광객조사 원자료 → df.pkl
    run('foreign_cluster.py')          # k-평균 → fb.json, labels.pkl
    run('foreign_lift.py')             # C7~C10 lift → fa.json
run('classify.py')                     # 장소 재분류 → classified.json
run('calc2.py')                        # 군집×테마 적합, 대표 사용자 → calc2.json
print('done →', OUT)
