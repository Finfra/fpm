#!/usr/bin/env python3
"""VSCode 워크스페이스 설정 머지 유틸.
기본 템플릿 + 도메인 오버레이 + 기존 설정 통합.
"""

import json
import sys
import shutil
from pathlib import Path
from datetime import datetime

def load_json_comments(path):
    """JSON with comments 로드."""
    with open(path) as f:
        content = f.read()
    # 간단한 // 주석 제거
    lines = []
    for line in content.split('\n'):
        if '//' in line:
            line = line[:line.index('//')]
        lines.append(line)
    return json.loads('\n'.join(lines))

def deep_merge(base, overlay):
    """dict 깊은 머지 (overlay가 base를 덮음)."""
    result = base.copy()
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result

def merge_vscode_settings(base_tmpl, overlay_tmpl, existing_path, domain='g'):
    """VSCode 설정 머지.

    Args:
        base_tmpl: 기본 템플릿 경로
        overlay_tmpl: 도메인 오버레이 경로 (선택)
        existing_path: 기존 .vscode/settings.json 경로
        domain: 도메인 (-g, -m, -w)

    Returns:
        (merged_settings, diff_desc)
    """
    # 1. 템플릿 로드
    base = load_json_comments(base_tmpl)
    merged = base.copy()

    if overlay_tmpl and overlay_tmpl.exists():
        overlay = load_json_comments(overlay_tmpl)
        merged = deep_merge(merged, overlay)

    # 2. 기존 설정 로드
    existing = {}
    if existing_path.exists():
        try:
            existing = load_json_comments(existing_path)
        except:
            pass

    # 3. 성능 키만 주입 (기존 설정 보존)
    result = existing.copy()
    for key in merged:
        result[key] = merged[key]

    # 4. 변경사항 계산
    before_keys = set(existing.keys())
    after_keys = set(result.keys())
    added = after_keys - before_keys
    changed = [k for k in before_keys & after_keys if existing.get(k) != result.get(k)]

    diff_desc = f"Added: {len(added)} keys, Changed: {len(changed)} keys"
    if added:
        diff_desc += f"\n  Added: {', '.join(sorted(added)[:5])}"
    if changed:
        diff_desc += f"\n  Changed: {', '.join(sorted(changed)[:5])}"

    return result, diff_desc

def main():
    if len(sys.argv) < 2:
        print("Usage: vscode-settings-merge.py <project_root> [--apply] [domain]")
        sys.exit(1)

    project_root = Path(sys.argv[1])
    apply_flag = '--apply' in sys.argv
    domain = next((a for a in sys.argv[2:] if a in ('g', 'm', 'w')), 'g')

    vscode_dir = project_root / '.vscode'
    vscode_dir.mkdir(exist_ok=True)
    settings_path = vscode_dir / 'settings.json'

    # 템플릿 경로 (스크립트 기준)
    script_dir = Path(__file__).parent
    base_tmpl = script_dir.parent / 'data/template/vscode-settings-perf.json'
    overlay_tmpl = script_dir.parent / f'data/template/vscode-settings-perf-{domain}.json'

    # 머지 수행
    merged, diff = merge_vscode_settings(base_tmpl, overlay_tmpl, settings_path, domain)

    # 결과 출력
    print(f"\n{'='*60}")
    print(f"Project: {project_root.name}")
    print(f"Domain: -{domain}")
    print(f"{'='*60}")
    print(f"\n{diff}\n")

    if apply_flag:
        # 백업
        if settings_path.exists():
            backup_name = f".vscode/settings.json.backup.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            backup_path = project_root / backup_name
            shutil.copy(settings_path, backup_path)
            print(f"✓ Backup: {backup_name}")

        # 저장
        with open(settings_path, 'w') as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        print(f"✓ Applied: {settings_path}")
    else:
        print("ℹ Dry-run mode. Use --apply to save.")

    print()

if __name__ == '__main__':
    main()
