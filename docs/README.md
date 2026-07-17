# 문서 목록


| 문서 | 담고 있는 내용 | 링크 |
|---|---|---|
| 프로젝트 README | 프로젝트 개요, 주요 기능, 설치·실행 요약, CLI/API/MCP/Codex 플러그인 사용법 | [../README.md](../README.md) |
| 아키텍처 | 서비스 목적, 전체 구조, 적재·검색·워크플로·API·MCP·Codex Skill 구성 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 함수 인터페이스 | FUNC-001~009의 역할, 진입점, 입출력 계약, 에러코드 | [func_interfaces.md](func_interfaces.md) |
| 로컬 개발 셋업 | uv 의존성 설치, 환경변수, ingest/query 실행, API·React 개발 서버, 테스트 방법 | [guides/local_dev_setup.md](guides/local_dev_setup.md) |
| Docker 셋업 | Docker Compose 구성, `database`·`embedding`·`app` 컨테이너, 설치와 점검 방법 | [guides/docker_setup_guide.md](guides/docker_setup_guide.md) |
| 검색 가이드 | Dense 검색, Sparse 검색, RRF 병합, 필터링, 검색 장애 처리와 개선 시 주의점 | [guides/retrieval_guide.md](guides/retrieval_guide.md) |
| 온톨로지 가이드 | 기준서 구조화, 온톨로지 노드, 청킹 단위, `chunk_id`, 메타데이터, 페이지 매핑 | [guides/ontology_guide.md](guides/ontology_guide.md) |
| 문서 파싱 가이드 | 파싱 산출물 정본, 페이지 마커, 취소선 조문 제외, 원문과 파싱 결과 검수 기준 | [guides/document_parsing_guide.md](guides/document_parsing_guide.md) |
| Codex 플러그인 가이드 | Codex 플러그인 등록, 스킬 트리거 확인, MCP 도구 호출 검증 | [guides/codex_plugin_guide.md](guides/codex_plugin_guide.md) |
| 평가 통과 규칙 | 검색 통과 기준, 답변 내용 평가 기준, 성능 지표 기록 원칙 | [benchmark/eval_pass_rules.md](benchmark/eval_pass_rules.md) |

