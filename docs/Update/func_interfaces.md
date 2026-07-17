# FUNC 인터페이스 명세 (FUNC-001~009)

> **한 줄 요약(BLUF):** v1.0 각 기능(FUNC-001~009)의 입출력 계약과 에러코드. 타입은 `src/models/schemas.py`·`src/models/state.py`가 정본이다.

> **약어** — HNSW(근사최근접 벡터 인덱스) · tsvector(PostgreSQL 전문검색 토큰) · upsert(있으면 갱신·없으면 삽입). 공통 용어(조항·RRF·HIL·CRAG)는 [용어 사전](../README.md#용어-단일화-사전), 비개발 독자는 [아키텍처 개요](architecture_overview.md)부터.

*작성일 2026-06-13 · 코드 실태 기준.*

## 데이터 스키마

FUNC들이 주고받는 데이터 타입은 `src/models/schemas.py`(공용 스키마)와 `src/models/state.py`(`GraphState`)가 정본이다.
필드를 이 문서에 다시 나열하면 코드가 바뀔 때마다 여기도 같이 고쳐야 해서 금방 어긋난다 — 정확한 필드는 소스를 직접 본다.

---

## FUNC-001 — 문서 파싱 (`src/ingest/parse/`)
PDF 한 개를 받아 Docling으로 텍스트·표를 뽑고, 페이지 안의 읽는 순서를 사람이 읽는 순서(위→아래, 왼→오른)로 재정렬한 뒤
마크다운 문서(`ParsedDocument`)로 돌려준다. `DoclingParser().parse(path)`로 진입한다.

## FUNC-002 — 청킹/온톨로지 (`src/ingest/ontology/`)
마크다운 문서를 장·절·소절(Standard/Section/Subsection) 구조로 나누고, 조항 간 참조(REFERENCES 등) 관계를
정규식과 LLM으로 함께 채운 뒤, 그 구조를 검색 가능한 청크로 잘라낸다.
`build_graph(md_path, standard_id, standard_type)`로 구조를 만들고 `chunk_graph(graph, source_path)`로 청크를 뽑는다.
구조를 못 알아내면 OT-103을 낸다.

## FUNC-003 — 인덱싱 (`src/db/vector_store.py`, `src/clients/embedding.py`)
- **입력**: `list[RetrievedChunk]`, collection(기본 `chunks`)
- **출력**: `IndexingResult`
- **진입**: `index_documents(chunks, collection)`. 임베딩 KURE-v1(1024d) → pgvector HNSW upsert(멱등 chunk_id)
- **에러**: IX-201(토큰 한도 초과 → 부분 커밋), SE-102(DB)
>>>>>>> 3f7b0fb (refactor: src 구조 재배치 — ingest 파이프라인 분리·클라이언트 통합·mcp 개명)

## FUNC-004 — 질의 재구성 (`src/agent/nodes/rewrite.py`)
사용자 질의가 회계 질문인지 먼저 판별하고, 아니면 조기 종료한다.
회계 질문이면 질의 성격에 따라 hyde(가상 답변 생성)·decompose(하위 질문 분해)·stepback(일반 원칙으로 추상화) 중
하나를 골라 검색용 쿼리를 만든다. LLM 호출이 실패하면 CM-002를 내고 원문 쿼리로 폴백한다.
`rewrite_query(state)`로 진입한다.

## FUNC-005 — 하이브리드 검색 (`src/retrieval/searcher.py`)
pgvector 코사인 유사도 기반 dense 검색과 PostgreSQL 전문검색 기반 sparse 검색을 각각 돌린 뒤,
RRF(순위 기반 병합, k=60)로 합친다. 한쪽이 실패해도 다른 쪽 결과로 계속 진행하고, 결과가 없으면
top_k를 늘려 한 번 더 찾아본다. 그래도 없으면 SE-103을 낸다. `search_chunks(...)`로 진입한다.

## FUNC-006 — 리랭킹 (`src/retrieval/reranker.py`)
검색된 청크를 Cross-Encoder 모델로 질의와의 관련도를 다시 매겨 정렬한다.
`USE_RERANKER`가 꺼져 있으면(기본값) 이 단계를 건너뛴다.
모델 호출이나 점수 계산이 실패하면 RR-201, 임계값을 넘는 청크가 하나도 없으면 RR-202를 낸다.
`rerank_chunks(...)`로 진입한다.

## FUNC-007 — 적합성 평가 / CRAG (`src/agent/nodes/evaluate.py`)
검색된 컨텍스트가 질의에 답하기 충분한지 LLM으로 판단한다. 부족하면 needs_external·needs_reretrieval
신호를 세워 워크플로우가 재검색(rewrite로 되돌아가는 CRAG 루프)을 돌게 한다.
평가 응답을 못 읽으면 EV-301, 결과가 내부적으로 모순되면 EV-302, 근거 없는 주장이 감지되면 EV-303을 낸다.
`evaluate_context(state)`로 진입한다.

## FUNC-008 — 답변·인용 생성 (`src/agent/nodes/generate.py`)
컨텍스트를 근거로 최종 답변을 생성하고, 답변 안의 `[n]` 표시를 실제 인용 청크로 연결한다.
인용 없이 답변 가능이라고 하면 GN-401, 컨텍스트가 토큰 한도를 넘으면 GN-402를 낸다.
`generate_response(state)`로 진입한다.

## FUNC-009 — 워크플로우 제어 (`src/agent/workflow.py`)
rewrite→search→rerank→evaluate→generate 노드를 LangGraph StateGraph로 엮고, 평가 미달 시 rewrite로
돌아가는 CRAG 루프(최대 `MAX_REWRITE_COUNT=3`회)와 사람 확인이 필요한 HIL 중단·재개(최대 `MAX_HIL_COUNT=5`회)를
라우팅한다. 노드에서 예외가 나면 `handle_node_errors` 데코레이터가 error_logs에 기록하고 계속 진행하며,
반복 한도 초과(GraphRecursionError)나 시간 초과(TimeoutError)에는 예외를 다시 던지지 않고 정해진 폴백 응답을
돌려준다. `run_workflow(query, standard_filter)`·`resume_workflow(thread_id, decision)`로 진입한다.

---

## 에러코드 카탈로그 (`src/utils/exception.py`)

| 코드 | 노드 | 발생 시점 |
|---|---|---|
| CM-001 | * | 설정·환경변수가 없을 때 |
| CM-002 | * | LLM 호출이 실패했을 때(연결·인증·응답 파싱) |
| CM-003 | * | 문서 파싱 실패용 예외 — 클래스는 있지만 아직 이 예외를 실제로 던지는 코드가 없다(향후 `DoclingParser.parse`에 연결 예정) |
| OT-103 | ontology | 문서 구조를 못 알아냈을 때 |
| SE-101 | search | pgvector 검색 응답이 시간을 초과했을 때 |
| SE-102 | search 또는 index | DB 연결이 끊기거나 쿼리 실행이 실패했을 때 |
| SE-103 | search | 검색 결과가 없거나 임계값을 만족하는 결과가 하나도 없을 때 |
| RR-201 | rerank | 리랭킹 모델 호출이나 점수 계산이 실패했을 때 |
| RR-202 | rerank | 리랭킹 후 임계값을 넘는 청크가 하나도 없을 때 |
| IX-201 | index | 임베딩 토큰 한도를 넘겨 해당 청크를 건너뛸 때 |
| EV-301 | evaluate | 평가 응답을 정해진 형식으로 못 읽었을 때 |
| EV-302 | evaluate | 평가 결과가 내부적으로 모순될 때 |
| EV-303 | evaluate | 근거 없는 주장(환각)이 감지됐을 때 |
| GN-401 | generate | 답변 가능이라면서 인용 근거가 없을 때 |
| GN-402 | generate | 컨텍스트가 모델의 토큰 한도를 넘었을 때 |
| TIMEOUT | workflow | 노드 하나가 step_timeout을 넘었을 때(그래프 레벨이라 어느 노드인지 특정 불가 — `exception.py`가 아니라 `workflow.py`의 폴백이 직접 기록) |
| RECURSION_LIMIT | workflow | 재시도가 그래프의 recursion_limit을 다 써서 소진됐을 때(그래프 레벨이라 어느 노드인지 특정 불가 — `exception.py`가 아니라 `workflow.py`의 폴백이 직접 기록) |

> `ErrorLog`(timestamp KST, node, error_type, message)로 `GraphState.error_logs`에 누적.
