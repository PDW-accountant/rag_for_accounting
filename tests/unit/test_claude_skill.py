"""
Claude Code용 스킬이 Codex용 스킬과 같은 내용인지 검증한다.

같은 스킬을 에이전트가 서로 다른 고정 위치에서 읽기 때문에 사본이 두 개다.
한쪽 SKILL.md만 고치면(예: 트리거율을 높이려고 description에 용어를 보강) 두 에이전트가 같은 질의에 다르게 동작하는데, 이 어긋남은 에러 없이 조용히 벌어져 눈에 띄지 않는다.
이 테스트가 두 사본이 어긋나는 순간을 잡는다.
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
CODEX_SKILL = REPO_ROOT / "src" / "skills" / "k-accounting" / "SKILL.md"
CLAUDE_SKILL = REPO_ROOT / ".claude" / "skills" / "k-accounting" / "SKILL.md"


@pytest.mark.unit
class TestClaudeSkillSync:
    """Claude Code용 스킬 사본의 존재와 Codex 원본과의 동기화를 검증한다."""

    def test_claude_skill_exists(self):
        """Claude Code가 스킬을 찾는 위치에 파일이 있어야 한다"""
        assert CLAUDE_SKILL.is_file(), (
            "Claude Code용 스킬(.claude/skills/k-accounting/SKILL.md)이 없다"
        )

    def test_claude_skill_matches_codex_skill(self):
        """두 사본의 내용이 같아야 한다"""
        assert CLAUDE_SKILL.read_text() == CODEX_SKILL.read_text(), (
            "src/skills와 .claude/skills의 SKILL.md 내용이 다르다 — "
            "한쪽만 수정된 상태다. 두 파일을 같게 맞춘 뒤 커밋할 것"
        )
