"""
Codex 플러그인 매니페스트(plugin.json)·스킬(SKILL.md)·MCP 설정(.mcp.json) 구조 검증.

이 세 파일은 codex CLI가 직접 읽는 설정 파일이라 py_compile 같은 파이썬 문법 검사로는 오류를 잡을 수 없다.
예를 들어 plugin.json의 skills 필드가 실제 존재하지 않는 경로를 가리키면, codex는 이를 조용히 무시하고 스킬을 아예 로드하지 않는다.
에러 메시지 없이 기능만 빠지므로 배포 후에야 발견되기 쉽다.
이 테스트는 그런 실수를 codex 실행 전에 잡는다.
"""
import inspect
import json
import re
from pathlib import Path
from typing import get_args

import pytest

SRC_ROOT = Path(__file__).parent.parent.parent / "src"
PLUGIN_JSON = SRC_ROOT / ".codex-plugin" / "plugin.json"
MCP_JSON = SRC_ROOT / ".mcp.json"
SKILL_MD = SRC_ROOT / "skills" / "k-accounting" / "SKILL.md"


@pytest.mark.unit
class TestCodexPluginManifest:
    """plugin.json 필수 필드와 참조 경로의 유효성을 검증한다."""

    def test_plugin_json_has_required_fields(self):
        """필수 필드가 존재하는지"""
        data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        for field in ("name", "version", "description", "skills", "mcpServers"):
            assert data.get(field), f"plugin.json에 '{field}' 필드가 없거나 비어 있다"

    def test_plugin_json_skills_path_resolves_to_existing_dir(self):
        """스킬 경로가 실제 디렉터리를 가리키는지"""
        # plugin.json 안의 상대경로는 plugin.json이 있는 .codex-plugin/이 아니라 플러그인 루트(SRC_ROOT)를 기준으로 풀린다.
        # Codex 공식 문서상 skills/·.mcp.json은 .codex-plugin/의 형제 디렉터리로 플러그인 루트에 위치하기 때문이다.
        data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        skills_path = (SRC_ROOT / data["skills"]).resolve()
        assert skills_path.is_dir(), (
            f"plugin.json의 skills 경로({data['skills']})가 실제 디렉터리를 가리키지 않는다"
        )

    def test_plugin_json_mcp_servers_path_resolves_to_existing_file(self):
        """mcp server 경로가 실제 파일을 가리키는지"""
        data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        mcp_path = (SRC_ROOT / data["mcpServers"]).resolve()
        assert mcp_path.is_file(), (
            f"plugin.json의 mcpServers 경로({data['mcpServers']})가 실제 파일을 가리키지 않는다"
        )


@pytest.mark.unit
class TestCodexMcpConfig:
    """.mcp.json이 기존 FastMCP 서버(src/mcp_server/server.py)를 올바르게 참조하는지 검증한다."""

    def test_mcp_json_references_existing_server_module(self):
        """mcp server 모듈을 올바르게 참조하는지"""
        data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        # Codex는 mcpServers 키만 인식하고 mcp_servers 같은 다른 표기는 조용히 무시한다.
        # 구 키까지 함께 허용하면 구 키로 되돌리는 회귀를 이 테스트가 통과시키므로, mcpServers 단일로 검사한다.
        servers = data.get("mcpServers")
        assert servers, ".mcp.json에 mcpServers 키가 없거나 비어 있다"

        launch_commands = [
            " ".join([cfg.get("command", "")] + cfg.get("args", []))
            for cfg in servers.values()
        ]
        assert any("src.mcp_server.server" in cmd for cmd in launch_commands), (
            ".mcp.json의 실행 커맨드가 src.mcp_server.server를 가리키지 않는다"
        )


@pytest.mark.unit
class TestKaccountingSkill:
    """SKILL.md의 frontmatter(파일 맨 앞 '---'로 감싼 메타데이터 블록)에 트리거 판단용 필드가 있는지 검증한다."""

    def test_skill_md_starts_with_frontmatter_block(self):
        """SKILL.md는 '---'로 시작하는 frontmatter 블록이 있어야 한다"""
        text = SKILL_MD.read_text(encoding="utf-8")
        assert text.startswith("---"), "SKILL.md는 '---'로 시작하는 frontmatter 블록이 있어야 한다"

    def test_skill_md_frontmatter_has_name_and_description(self):
        """SKILL.md frontmatter에 name과 description이 있는지 검증한다"""
        text = SKILL_MD.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        # 닫는 ---가 없으면 파일 전체가 frontmatter로 잡혀 아래 검사가 헛돌고,
        # 정작 codex/Claude는 메타데이터 파싱에 실패해 스킬을 조용히 무시한다.
        assert len(parts) == 3, (
            "SKILL.md frontmatter가 닫는 '---' 없이 끝났다 — 메타데이터 블록이 성립하지 않는다"
        )
        frontmatter = parts[1]
        # \s는 개행까지 삼켜 'name:'(빈 값) 뒤 다음 줄의 키를 값으로 오인하므로, 같은 줄 공백만 허용한다.
        assert re.search(r"^name:[ \t]*\S+", frontmatter, re.MULTILINE), (
            "SKILL.md frontmatter에 name이 없다"
        )
        assert re.search(r"^description:[ \t]*\S+", frontmatter, re.MULTILINE), (
            "SKILL.md frontmatter에 description이 없다"
        )

    def test_skill_md_standard_filter_values_match_server_literal(self):
        """스킬이 지시하는 standard_filter 값이 서버 enum과 일치하는지 검증한다"""
        # 스킬 본문의 `"GAAP"` 같은 값은 서버 시그니처의 Literal에서 손으로 옮겨 적은 사본이다.
        # 서버 enum이 바뀌면(값 개명·추가) 스킬은 옛 값을 계속 지시하는데,
        # 그 어긋남은 실행 시점의 pydantic 검증 에러로만 드러나고 단위 스위트는 통과하므로 여기서 잡는다.
        from src.mcp_server import server

        annotation = inspect.signature(server.query_standards).parameters[
            "standard_filter"
        ].annotation
        server_values = set(get_args(annotation))

        skill_values = set(
            re.findall(r'`"([A-Z]+)"`', SKILL_MD.read_text(encoding="utf-8"))
        )
        assert skill_values == server_values, (
            f"SKILL.md의 standard_filter 값 {sorted(skill_values)}이 "
            f"서버 Literal {sorted(server_values)}과 다르다 — 한쪽만 바뀐 상태다"
        )
