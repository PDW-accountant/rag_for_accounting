# 토큰화 × 융합 × 리랭커 오프라인 실측 — 리랭커 기본 OFF 확정 (2026-07-05)

> **한 줄 요약(BLUF):** 토큰화·가중 RRF·캐스케이드 융합·리랭커 모델(bge·gte·ms-marco)을 조합해 현행 1507청크 코퍼스에서 실측했으나, **어느 셀도 dense 단독 baseline의 Hit@1(4/14)을 넘지 못했다.** 리랭커는 오히려 Hit@1을 깎고(bge 4→2), 가장 나은 gte조차 재정렬 없는 morph 융합과 동일(3/14)에 그친다. 따라서 **`USE_RERANKER` 운영 기본값은 OFF로 유지**한다. 
> 부수 확정: 형태소 토큰화는 재현율(retrieval_pass 7→9)을 실제로 올리는 레버이나 Hit@1 레버는 아니다.

## 배경

`#228`에서 리랭커를 운영 기본 ON으로 켜는 방안을 검토했으나, 앞선 실측(`rerank_replay_20260704_0159.md`, 1072청크)에서 bge 리랭커가 Hit@1을 4→2로 깎아 롤백됐다. 그때 진단은 두 갈래였다.

- **재현율 병목**: sparse 토큰화. 현행 PostgreSQL `to_tsvector('simple', …)`는 띄어쓰기로만 잘라 "외화환산손익"을 한 덩어리로 두므로, "외화환산" 질의와 매칭조차 못 한다(`#81`·`#226`).
- **리랭커 변별 실패**: bge의 gold/비gold 시그모이드 점수가 0.5~0.8 구간에 중첩돼 정답을 가려내지 못한다.

이 리포트는 두 병목을 **결합해** 재검한다: 토큰화를 형태소로 바꿔 재현율을 올린 뒤, 융합 방식과 리랭커 모델을 갈아끼우면 Hit@1이 개선되는가?

## 측정 조건

- 코퍼스: 1507청크(현행 canonical) · 벤치마크 14질의(K-GAAP)
- 방법: 질의별 dense + plainto sparse + morph BM25(오프라인, 코퍼스 인메모리 형태소 재토큰화) → RRF(k=60) 병합 → 셀별 재정렬 → 채점. 프로덕션 검색 경로·적재는 건드리지 않음.
- self-check: 오프라인 융합이 라이브 `search_chunks`와 **14/14 일치**.
- 판정: `judge_adoption`(Hit@1 순증 ≥+2 · 기존 hit 회귀 0 · MRR Δ>0 · rerank p50 ≤5s), 모집단 11건(gold 확정 대기 003·005·012 제외).
- 리랭커: bge(mps), gte-multilingual(MPS predict 비호환 → CPU 폴백), ms-marco(mps).
- 하니스: `scripts/rerank_tokenization_replay.py` (재현: `uv run --extra reranker python scripts/rerank_tokenization_replay.py`).

## 결과 매트릭스

전 질의에서 **plainto sparse는 0건**(현행 sparse가 자연어 질의에 매칭 실패) → baseline은 사실상 dense 단독이다.

| 셀 | Hit@1 | MRR | retrieval_pass | 회귀(기존 1위) | 비고 |
|---|---|---|---|---|---|
| **plainto (baseline)** | **4/14** | **0.399** | 7 | — | dense 단독 |
| morph | 3/14 | 0.381 | **9** | 001·009 | 토큰화 단독 |
| morph_wrrf (dense 가중 RRF) | 3/14 | 0.345 | 9 | 001 | 가중이 회귀 2→1로 줄임 |
| morph→dense (캐스케이드) | 3/14 | 0.336 | 8 | 001 | 크로스인코더 없이 dense 재정렬 |
| bge-reranker-v2-m3 | 2/14 | 0.267 | 9 | 001·009·014 | p50 7.04s(mps) |
| gte-multilingual-reranker-base | 3/14 | 0.381 | 9 | 001·009 | p50 126.8s(cpu 폴백) |
| ms-marco-MiniLM-L-6-v2 | 1/14 | 0.219 | 6 | 001·009·014 | 512토큰 절단, 대조군 |

## 셀별 판정 (전부 baseline 미달)

- **리랭커 모델 스윕**: gte가 bge보다 낫지만, gte 결과는 재정렬 없는 morph 융합과 **완전히 동일** — 즉 gte는 순서를 흐트러뜨리지 않되 끌어올리지도 못한다. bge는 유해, ms-marco는 최악. 게다가 gte는 MPS predict가 out-of-bounds로 깨져 CPU 폴백(p50 126.8s)이라 실사용 지연 불가.
- **dense 우선 가중 RRF**: dense를 2:1로 무겁게 주니 회귀가 2건→1건으로 줄어 가중이 dense 상위를 실제로 보호함을 확인. 그러나 001을 여전히 잃고 순증이 없어 Hit@1 3/14, MRR도 하락.
- **dense 캐스케이드**: morph 후보를 dense 유사도로 재정렬 — 역시 3/14, 001 잃음. 순수 morph 풀이라 재현율은 8로 소폭 낮음.

## 결정적 패턴

**모든 후보 셀에서 케이스 001이 회귀**하고 대부분 009도 회귀한다. dense 단독이 001·009의 정답을 이미 1위로 잡는데, morph 후보든 어떤 리랭커·융합이든 그것을 밀어낸다. 반면 재현율은 morph로 7→9로 오른다.

즉 **Hit@1 천장은 dense 단독(4/14)이고, 그 위에 얹는 모든 것이 Hit@1을 깎는다.** 병목은 리랭커 모델도, 융합 방식도, 토큰화도 아니다 — 이 벤치마크에서 Hit@1은 dense 임베딩이 이미 최적점에 가깝고, 재정렬 레이어가 그 최적을 흩뜨린다.

지연 주석: 이 하니스는 효율상 합집합을 한 번에 리랭킹한다. 프로덕션은 융합 top-10만 리랭킹하므로 실지연은 표의 절반 수준이다. 다만 지연과 무관하게 정확도(Hit@1)에서 이미 탈락한다.

## 시사점 · 후속

1. **`USE_RERANKER` 기본 OFF 유지** — 세 레버 어느 것도 채택 기준 미달. bge 유해·gte 무개선+지연 불가·ms-marco 무용. `RERANK_MODEL` 기본값만 한국어 지원 bge로 둔다(opt-in 시 ms-marco의 한국어 0/14보다 낫다).
2. **형태소 토큰화는 재현율 전용 레버** — retrieval_pass 7→9는 실측 이득이나 Hit@1을 깎으므로, 대칭 RRF가 아니라 dense 상위를 보존하는 융합과 함께 별도로 다뤄야 한다.
3. **001·009 gold 확정(`#183`)이 그림을 바꿀 수 있다** — 이 둘이 전 셀의 회귀 주범이다. dense가 exact-match로 잡은 문단과 리랭커가 올린 다른 관련 문단 중 무엇이 정답인지 회계사 확정이 필요하다.
4. **Hit@1 개선 여지는 리랭킹이 아니라 dense·청킹·rewrite** 쪽이다 — 재정렬 레이어는 현행 벤치마크에서 dense 최적을 넘지 못한다.

---
재현: `scripts/rerank_tokenization_replay.py`. 원시 결과 JSON은 gitignore 대상이며 본 리포트가 기록 정본이다.
