# -*- coding: utf-8 -*-
"""재분류 결과를 앱의 .dc.html 에 반영한다.

    python -m pipeline.apply_categories           # 미리보기만 (기본)
    python -m pipeline.apply_categories --write   # 실제로 고침

**이 스크립트만 다른 레포(앱)의 파일을 고친다.** 그래서 기본은 미리보기이고,
`--write` 를 줘야 실제로 쓴다.

무엇을 반영할지는 tourapi.py 의 `apply_decision()` 이 이미 정해 두었다
(`categories.json` 의 `apply` 필드). 여기서는 판단하지 않고 그대로 따른다.

앱은 장소 1,171곳을 24,000줄짜리 HTML 안에 JS 객체 리터럴로 들고 있다.
장소 id 로 레코드를 찾아 그 안의 `cat:'...'` 하나만 바꾼다. 줄 단위로 고치면
같은 줄의 다른 장소까지 건드릴 수 있어서, 레코드 경계를 잡고 그 안에서만 바꾼다.
"""
import json
import os
import re
import shutil
import sys
from collections import Counter

from .common import APP_HTML, DERIVED, NFC


def load_targets():
    path = os.path.join(DERIVED, "categories.json")
    if not os.path.exists(path):
        sys.exit("data/derived/categories.json 이 없습니다. "
                 "먼저 `python -m pipeline.tourapi` 를 돌려 주세요.")
    rows = json.load(open(path, encoding="utf-8"))["places"]
    return [r for r in rows if r.get("apply")]


def patch(src, targets):
    """{id: 새 카테고리} 를 HTML에 적용. (새 소스, 적용 목록, 실패 목록)."""
    done, failed = [], []
    for r in targets:
        pid, want = r["id"], r["catOfficial"]
        # 레코드는 {...} 하나. id 를 포함한 중괄호 블록을 찾는다.
        m = re.search(r"\{[^{}]*\bid:'" + re.escape(pid) + r"'[^{}]*\}", src)
        if not m:
            failed.append((pid, r["nameKo"], "레코드를 찾지 못함"))
            continue
        rec = m.group(0)
        cm = re.search(r"\bcat:'([a-z]+)'", rec)
        if not cm:
            failed.append((pid, r["nameKo"], "cat 필드가 없음"))
            continue
        if cm.group(1) != r["catApp"]:
            # categories.json 을 만든 뒤에 앱이 바뀐 것이다. 덮어쓰면 남의 수정을
            # 지우게 되므로 건너뛴다.
            failed.append((pid, r["nameKo"],
                           f"앱의 현재 값이 다름 ('{cm.group(1)}' ≠ '{r['catApp']}')"))
            continue
        new_rec = rec[:cm.start()] + f"cat:'{want}'" + rec[cm.end():]
        src = src[:m.start()] + new_rec + src[m.end():]
        done.append(r)
    return src, done, failed


def main():
    write = "--write" in sys.argv
    if not os.path.exists(APP_HTML):
        sys.exit(f"앱 파일을 찾을 수 없습니다: {APP_HTML}\n"
                 f"APP_REPO 환경변수로 앱 레포 경로를 주세요.")

    targets = load_targets()
    src = open(APP_HTML, encoding="utf-8").read()
    before = len(re.findall(r"\bcat:'[a-z]+'", src))

    new_src, done, failed = patch(src, targets)
    after = len(re.findall(r"\bcat:'[a-z]+'", new_src))

    print(f"반영 대상 {len(targets)}곳 → 적용 {len(done)}곳 / 실패 {len(failed)}곳")
    print(f"앱의 cat 필드 수 {before} → {after}"
          f"  {'✓ 유지됨' if before == after else '✗ 개수가 달라졌다'}")

    flow = Counter((r["catApp"], r["catOfficial"]) for r in done)
    print("\n  변경 내역")
    for (a, b), c in flow.most_common():
        print(f"    {a:9} → {b:9} {c:3}곳")

    if failed:
        print(f"\n  적용하지 못한 {len(failed)}곳")
        for pid, name, why in failed[:20]:
            print(f"    {pid:8} {name[:20]:22} {why}")
        if len(failed) > 20:
            print(f"    … 외 {len(failed) - 20}곳")

    if before != after:
        sys.exit("\n✗ cat 필드 개수가 달라졌습니다. 쓰지 않고 중단합니다.")

    if not write:
        print("\n미리보기입니다. 실제로 고치려면 --write 를 붙여 주세요.")
        return

    backup = APP_HTML + ".bak"
    shutil.copy2(APP_HTML, backup)
    open(APP_HTML, "w", encoding="utf-8").write(new_src)
    print(f"\n반영 완료 → {APP_HTML}")
    print(f"백업       → {backup}")
    print("앱 레포에서 `git diff` 로 확인한 뒤 커밋하세요.")


if __name__ == "__main__":
    main()
