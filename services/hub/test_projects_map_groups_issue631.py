#!/usr/bin/env python3
# test_projects_map_groups_issue631.py — Issue631 회귀 테스트
#   projects-map «프로젝트 그룹» 패널·팝업의 서버 측(pm-group --json·set desc·groups 읽기/쓰기 헬퍼)과 빌더 마크업
#
# 실행: python3 services/hub/test_projects_map_groups_issue631.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def make_base():
    base = tempfile.mkdtemp(prefix="pmg631-")
    os.makedirs(os.path.join(base, "data"))
    os.makedirs(os.path.join(base, "sh"))
    shutil.copy(os.path.join(REPO, "sh", "pm-group"), os.path.join(base, "sh", "pm-group"))
    with open(os.path.join(base, "Projects.md"), "w", encoding="utf-8") as f:
        f.write("| id | name |\n|---|---|\n| 1 | ___pm |\n| 2 | doc |\n| 3 | claude |\n| 9a | paper |\n")
    with open(os.path.join(base, "data", "groups.yml"), "w", encoding="utf-8") as f:
        f.write('groups:\n  alpha:\n    desc: "첫 그룹"\n    members: [1, 2]\n')
    return base


def pmg(base, *args):
    env = dict(os.environ, FPM_BASE=base)
    return subprocess.run([sys.executable, os.path.join(base, "sh", "pm-group"), *args],
                          capture_output=True, text=True, env=env)


print("== pm-group --json / set --desc")
base = make_base()
r = pmg(base, "--json")
data = json.loads(r.stdout) if r.returncode == 0 else {}
check("--json rc 0", r.returncode == 0)
check("--json groups.alpha.members", data.get("groups", {}).get("alpha", {}).get("members") == ["1", "2"])
check("--json projects 레지스트리", data.get("projects", {}).get("9a") == "paper")
r = pmg(base, "set", "alpha", "--desc", "바뀐 설명")
check("set --desc 만으로 설명 수정 rc 0", r.returncode == 0)
check("set --desc 구성원 보존", json.loads(pmg(base, "--json").stdout)["groups"]["alpha"]["members"] == ["1", "2"])
check("set --desc 반영", json.loads(pmg(base, "--json").stdout)["groups"]["alpha"]["desc"] == "바뀐 설명")

print("== server 헬퍼")
check("groups_read 존재", hasattr(server, "projects_map_groups_read"))
check("groups_apply 존재", hasattr(server, "projects_map_groups_apply"))
if hasattr(server, "projects_map_groups_apply"):
    st, body = server.projects_map_groups_read(base)
    check("read 200 + groups", st == 200 and "alpha" in body.get("groups", {}))
    st, body = server.projects_map_groups_apply(base, {"op": "add", "name": "beta", "members": ["2", "3"], "desc": "둘째"})
    check("add 200", st == 200)
    check("add 반영", server.projects_map_groups_read(base)[1]["groups"]["beta"]["members"] == ["2", "3"])
    st, body = server.projects_map_groups_apply(base, {"op": "set", "name": "beta", "members": ["3", "2", "9a"], "desc": "수정"})
    check("set 200·순서 유지", st == 200 and server.projects_map_groups_read(base)[1]["groups"]["beta"]["members"] == ["3", "2", "9a"])
    st, body = server.projects_map_groups_apply(base, {"op": "add", "name": "Bad Name", "members": ["1", "2"]})
    check("이름 규칙 위반 400 + 사유", st == 400 and "이름 규칙" in body.get("error", ""))
    st, body = server.projects_map_groups_apply(base, {"op": "add", "name": "gamma", "members": ["1"]})
    check("구성원 1개 400", st == 400)
    st, body = server.projects_map_groups_apply(base, {"op": "set", "name": "nope", "members": ["1", "2"]})
    check("없는 그룹 set 400", st == 400)
    st, body = server.projects_map_groups_apply(base, {"op": "rm", "name": "beta"})
    check("rm 200", st == 200 and "beta" not in server.projects_map_groups_read(base)[1]["groups"])
    st, body = server.projects_map_groups_apply(base, {"op": "drop", "name": "alpha"})
    check("알 수 없는 op 400", st == 400)
    st, body = server.projects_map_groups_apply(base, {"op": "add", "name": "--evil", "members": ["1", "2"]})
    check("플래그 주입 400", st == 400)
    st, body = server.projects_map_groups_apply(base, {"op": "add", "name": "ok", "members": ["1", "--desc"]})
    check("구성원 값 검증 400", st == 400)
shutil.rmtree(base, ignore_errors=True)

print("== 빌더 마크업")
src = open(os.path.join(REPO, ".claude", "skills", "projects-map", "build_projects_map.py"), encoding="utf-8").read()
check("groups 패널 id", 'id="groups-panel"' in src)
check("모달 id", 'id="group-modal"' in src)
check("GET 엔드포인트 참조", "/projects-map/groups" in src)
check(".agents 사본 동일", src == open(os.path.join(REPO, ".agents", "skills", "projects-map", "build_projects_map.py"), encoding="utf-8").read())

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
