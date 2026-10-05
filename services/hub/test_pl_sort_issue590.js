#!/usr/bin/env node
// Issue590 회귀 테스트 — hub Project List 컬럼 정렬·정렬 상태 영속·Domain 열 축약.
//
//   server.py 소스에서 정렬 순수 함수(plSortList·plNextSort·plLoadSort·plSaveSort)를 떼어
//   node vm 으로 실행한다 — hub 서버가 떠 있지 않아도 판정된다.
//
//   판정 ① 번호 자연 정렬: 0 < 2 < 9 < 9a < 10 (문자열 정렬이면 10 이 2 앞에 온다)
//   판정 ② 내림차순·동률은 원래 순서 유지(stable) · 정렬 없음이면 원 순서 그대로
//   판정 ③ 헤더 클릭 순환: 다른 키 → asc, 같은 키 asc → desc → 해제(null)
//   판정 ④ 영속: plSaveSort 가 localStorage `plSort` 에 쓰고 plLoadSort 가 복원 · 깨진 값은 null
//   판정 ⑤ 표 헤더: Domain 열은 `D` 로 축약, 정렬 대상 헤더는 data-sort 를 단다
//
//   실행: node plugins/fpm-core/services/hub/test_pl_sort_issue590.js
//   종료: 0=전건 통과 · 1=판정 실패 · 2=함수 추출 실패
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, 'server.py'), 'utf8');
let pass = 0, fail = 0;
const check = (name, cond) => { if (cond) { pass++; console.log('  ok   ' + name); } else { fail++; console.log('  FAIL ' + name); } };

function extract(name) {
  const m = SRC.match(new RegExp(`\\nfunction ${name}\\([\\s\\S]*?\\n}\\n`));
  return m ? m[0] : null;
}
const names = ['plSortList', 'plNextSort', 'plLoadSort', 'plSaveSort'];
const parts = names.map(extract);
// 영속 키·허용 키 상수도 함께 뗀다 — 없으면 함수 안 try 가 ReferenceError 를 삼켜 조용히 no-op 이 된다
const consts = ['PL_SORT_LS', 'PL_SORT_KEYS'].map(c => (SRC.match(new RegExp(`\nconst ${c} = [^\n]*`)) || [])[0]);
if (parts.some(p => !p) || consts.some(c => !c)) {
  console.log('  FAIL 함수·상수 추출 실패');
  process.exit(2);
}
parts.unshift(...consts);
const store = {};
const ctx = { localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } }, Intl, JSON, String, Number };
vm.createContext(ctx);
vm.runInContext(parts.join('\n') + '\nthis.api = {plSortList, plNextSort, plLoadSort, plSaveSort};', ctx);
const { plSortList, plNextSort, plLoadSort, plSaveSort } = ctx.api;

const LIST = [
  { id: '10', name: 'finfraHome', domain: 'w', path: '~/_git/__all/finfraHome', desc: 'finfra.kr', htm_off: false, issue_map: true },
  { id: '2', name: 'obsidian', domain: 'g', path: '~/_doc', desc: 'Obsidian', htm_off: true, issue_map: false },
  { id: '9a', name: 'wnTfidfPaper', domain: 'g', path: '~/Documents/x', desc: 'Weighted', htm_off: false, issue_map: false },
  { id: '0', name: 'nowage', domain: 'g', path: '~', desc: 'macOS 홈', htm_off: true, issue_map: false },
  { id: '9', name: '<private-project-2>', domain: 'g', path: '~/Documents/finfra', desc: 'fSnippet', htm_off: false, issue_map: true },
  { id: '11', name: 'fBanner', domain: 'm', path: '~/_git/__all/fBanner', desc: '이미지', htm_off: false, issue_map: true },
];
const ids = l => l.map(p => p.id).join(',');

// ①
check('① 번호 자연 정렬 asc', ids(plSortList(LIST, { key: 'id', dir: 'asc' })) === '0,2,9,9a,10,11');
// ②
check('② 번호 desc', ids(plSortList(LIST, { key: 'id', dir: 'desc' })) === '11,10,9a,9,2,0');
check('② 정렬 없음 = 원 순서', ids(plSortList(LIST, null)) === ids(LIST));
check('② 원본 배열 불변', ids(LIST) === '10,2,9a,0,9,11');
check('② domain asc + 동률 stable', ids(plSortList(LIST, { key: 'domain', dir: 'asc' })) === '2,9a,0,9,11,10');
check('② name 대소문자 무시', plSortList(LIST, { key: 'name', dir: 'asc' })[0].name === 'fBanner');
check('② hub asc = on 먼저', ids(plSortList(LIST, { key: 'hub', dir: 'asc' })) === '10,9a,9,11,2,0');
check('② map asc = 보유 먼저', ids(plSortList(LIST, { key: 'map', dir: 'asc' })) === '10,9,11,2,9a,0');
// ③
const s1 = plNextSort(null, 'name');
check('③ 첫 클릭 asc', s1 && s1.key === 'name' && s1.dir === 'asc');
const s2 = plNextSort(s1, 'name');
check('③ 두 번째 desc', s2 && s2.key === 'name' && s2.dir === 'desc');
check('③ 세 번째 해제', plNextSort(s2, 'name') === null);
const s3 = plNextSort(s2, 'id');
check('③ 다른 키 → asc', s3 && s3.key === 'id' && s3.dir === 'asc');
// ④
plSaveSort({ key: 'desc', dir: 'desc' });
check('④ localStorage plSort 저장', JSON.parse(store.plSort).key === 'desc');
const back = plLoadSort();
check('④ 복원', back && back.key === 'desc' && back.dir === 'desc');
plSaveSort(null);
check('④ 해제도 저장 → null 복원', plLoadSort() === null);
store.plSort = '{깨짐';
check('④ 깨진 값 → null', plLoadSort() === null);
store.plSort = JSON.stringify({ key: 'evil', dir: 'asc' });
check('④ 모르는 키 → null', plLoadSort() === null);
// ⑤
check('⑤ Domain 헤더 D 축약', /<th[^>]*data-sort="domain"[^>]*>D</.test(SRC) && !/<th>Domain<\/th>/.test(SRC));
check('⑤ 번호·이름·경로·설명 헤더 data-sort', ['id', 'name', 'path', 'desc'].every(k => SRC.includes(`data-sort="${k}"`) || SRC.includes(`<th\${sortAttr('${k}')}>`)));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
