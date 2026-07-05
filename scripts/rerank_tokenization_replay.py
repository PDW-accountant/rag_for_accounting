"""토큰화 × 융합 × 리랭커 오프라인 실측 — Hit@1을 올릴 조합을 찾는다.

[배경] #228 리랭커 기본 ON은 실측에서 Hit@1을 4→2로 깎았다. 진단은 두 갈래였다.
  (1) 재현율 병목 = sparse 토큰화. 현행 'simple'은 "외화환산손익"을 한 덩어리로 둬 "외화환산" 질의와 매칭 실패.
  (2) bge 리랭커의 gold/비gold 점수 미변별. 앞선 측정에서 morph 토큰화는 재현율을 올렸으나(pass 7→9),
  대칭 RRF가 morph 노이즈로 dense의 Hit@1 상위를 밀어냈고, bge는 재현율과 무관하게 Hit@1을 회귀시켰다.

[목적] 그래서 세 레버를 함께 잰다.
  (A) 리랭커 모델 스윕 — bge 말고 다른 모델(gte-multilingual 등)이 gold/비gold를 더 잘 가르는가?
  (B) dense-우선 가중 RRF — dense 상위를 morph가 못 밀어내게 가중하면 재현율은 취하고 Hit@1은 지키는가?
  (C) dense 캐스케이드 — 크로스인코더 대신 morph 후보를 dense 유사도로 재정렬하면(sparse→dense) 어떤가?
  판정은 rerank_replay·bm25_replay와 같은 게이트(judge_adoption), baseline은 현행 하이브리드(plainto+dense RRF).

[측정 셀]
  plainto      : dense + plainto(현행) RRF, 재정렬 없음                = baseline
  morph        : dense + morph RRF, 재정렬 없음                        (토큰화 단독)
  morph_wrrf   : dense + morph, dense-우선 가중 RRF, 재정렬 없음          (레버 B)
  morph→dense  : morph 후보를 dense 유사도로 재정렬(캐스케이드)           (레버 C)
  {model}      : dense + morph RRF를 {model} 크로스인코더로 재정렬        (레버 A, 모델별)

[제약] 실측 실행은 호스트에서 — DB 기동·chunks 적재·리랭커 모델 로드가 필요하다. sentence-transformers는 --extra reranker.
  gte 등 MPS 비호환 모델은 CPU로 폴백 로드해 Hit@1 신호만이라도 잰다(지연은 CPU라 게이트 판정엔 무의미).

사용 (호스트 실행):
  uv run --extra reranker python scripts/rerank_tokenization_replay.py
  uv run --extra reranker python scripts/rerank_tokenization_replay.py --models bge-reranker-v2-m3,gte-multilingual-reranker-base
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.models.schemas import RetrievedChunk  # noqa: E402
from src.utils.config import KST, RRF_K  # noqa: E402
from scripts.rerank_replay import (  # noqa: E402
    REPLAY_MODELS,
    TOP_N,
    _case_filter,
    _mrr,
    _sigmoid,
    fuse_top_n,
    judge_adoption,
)
from scripts.bm25_replay import Bm25Index, _bm25_sparse, load_corpus, tokenize_morph  # noqa: E402

# dense-우선 가중 RRF의 dense 가중치(sparse=1.0). dense가 Hit@1 최강이라, 상위를 morph가 밀어내지 않게 무겁게 준다.
DENSE_WEIGHT = 2.0


def rerank_order(chunks: list[RetrievedChunk], scores: dict[str, float]) -> list[RetrievedChunk]:
    """후보를 점수(chunk_id→score) 내림차순으로 재정렬한다 — 크로스인코더 재정렬과 dense 캐스케이드가 공용한다.

    필터링 없이 순서만 바꾼다. 점수가 없는 후보는 맨 뒤로 보낸다(dense 캐스케이드에서 후보 풀에 dense 점수가
    빠진 경우의 방어 — KeyError로 측정 전체가 죽지 않게).
    """
    return sorted(chunks, key=lambda c: scores.get(c.chunk_id, float("-inf")), reverse=True)


def weighted_rrf(
    result_lists: list[list[RetrievedChunk]], weights: list[float], k: int, n: int
) -> list[RetrievedChunk]:
    """가중 RRF — score(doc) = Σ wᵢ / (k + rankᵢ). 대칭 reciprocal_rank_fusion과 달리 리스트별 가중치를 준다.

    dense를 무겁게 주면(예: [2,1]) dense 상위가 sparse 노이즈에 밀리지 않는다 — morph의 재현율만 취하고
    dense가 1위로 잡던 정답(Hit@1)은 지키려는 의도. 반환은 점수 내림차순 상위 n개.
    """
    scores: dict[str, float] = {}
    keep: dict[str, RetrievedChunk] = {}
    for results, w in zip(result_lists, weights):
        for rank, chunk in enumerate(results, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + w / (k + rank)
            keep.setdefault(chunk.chunk_id, chunk)
    return [keep[cid] for cid in sorted(scores, key=lambda c: scores[c], reverse=True)][:n]


def _score_with_reranker(cross_encoder_cls, spec: dict, measured: list) -> tuple:
    """
    모델을 로드해 케이스별 합집합 후보에 점수를 매긴다. 자동 디바이스에서 로드 또는 predict가 깨지면 CPU로 재시도한다.

    gte-multilingual 류는 trust_remote_code 커스텀 구현이 MPS와 비호환이라,
    로드는 되고도 predict에서 AcceleratorError(out-of-bounds)로 죽는다. 
    지연은 CPU라 게이트엔 무의미해도 "점수를 더 잘 가르는가"는 CPU로도 재므로, 로드·추론 어느 단계에서 깨지든 CPU로 한 번 더 시도한다.
    반환: (device_str, cold_start_s, {case_id: {chunk_id: score}}, p50). 자동·CPU 모두 실패하면 예외를 올린다.
    """
    last_err = None
    for device in (None, "cpu"):  # None=자동(MPS), 실패 시 CPU 재시도
        try:
            t0 = time.perf_counter()
            kwargs = {"max_length": spec["max_length"], "trust_remote_code": spec["trust_remote_code"]}
            if device:
                kwargs["device"] = device
            model = cross_encoder_cls(spec["name"], **kwargs)
            cold_start_s = time.perf_counter() - t0

            latencies, per_case = [], {}
            for rc in measured:
                t1 = time.perf_counter()
                raw = model.predict([(rc["query"], c.content) for c in rc["union"]])
                latencies.append(time.perf_counter() - t1)
                per_case[rc["id"]] = {c.chunk_id: _sigmoid(float(s)) for c, s in zip(rc["union"], raw)}
            return str(getattr(model, "device", device or "?")), cold_start_s, per_case, statistics.median(latencies)
        except Exception as e:  # noqa: BLE001 — 이 디바이스 실패는 다음(CPU)에서 재시도, 둘 다 실패면 아래서 raise
            last_err = f"{type(e).__name__}: {e}"
    raise RuntimeError(last_err)


def run_measure(out_dir: str, top_n: int, k: int, dense_weight: float, model_keys: list[str]) -> int:
    """벤치마크 전 질의를 셀별로 재질의·채점하고 baseline(plainto+dense RRF) 대비 채택 여부를 판정한다.

    흐름: 코퍼스 로드 → 형태소 BM25 인덱스 → 질의별 검색(dense·plainto·morph + dense 전량 점수 + self-check)
          → 모델 스윕(로드·합집합 추론) → 셀 채점 → baseline 대비 판정 → 산출물 저장.
    """
    if os.getenv("POSTGRES_HOST") == "database":  # 호스트 실행 보정(다른 하니스와 동일)
        os.environ["POSTGRES_HOST"] = "localhost"

    from src.db.connection import close_pool, init_pool
    from src.retrieval.searcher import dense_search, embed_query, search_chunks, sparse_search
    from tests.utils.benchmark_loader import load_benchmark
    from tests.utils.benchmark_metrics import (
        get_chunk_count,
        gold_para_set,
        parse_gold_clauses,
        rank_hit,
        resolve_core_paras,
        retrieval_pass,
    )

    cases = load_benchmark()
    init_pool()
    try:
        n_chunks = get_chunk_count()
        print(f"코퍼스: {n_chunks}청크 · RRF_K={k} · top_n={top_n} · dense_weight={dense_weight} · 모델 {model_keys}")

        # 형태소 BM25 인덱스 1회 구축(질의당 아님). 전 청크 형태소 분석이라 수 초 걸린다.
        corpus = load_corpus()
        t0 = time.perf_counter()
        morph_index = Bm25Index([c.content for c in corpus], tokenize_morph)
        print(f"형태소 BM25 인덱스 구축: {time.perf_counter() - t0:.1f}s ({len(corpus)}청크)")

        measured = []
        mismatches = []
        for case in cases:
            mf = _case_filter(case.standard)
            vec = embed_query(case.query)

            # dense 전량 랭킹을 1회 뽑아, top_n(=dense 후보)과 캐스케이드용 dense 점수 맵을 함께 얻는다.
            dense_full = dense_search(vec, max(n_chunks, top_n), mf)
            dense = dense_full[:top_n]
            dense_score_all = {c.chunk_id: c.score for c in dense_full}

            plainto = sparse_search(case.query, top_n, mf)
            morph = _bm25_sparse(morph_index, corpus, case.query, top_n, mf)

            # self-check: (plainto, off) 오프라인 융합이 라이브 search_chunks와 같아야 측정을 신뢰할 수 있다.
            # search_chunks는 RRF_K로 융합하므로 비교도 RRF_K에서 한다(측정 k와 무관하게 고정).
            if [c.chunk_id for c in fuse_top_n(dense, plainto, k=RRF_K, n=top_n)] != \
               [c.chunk_id for c in search_chunks(case.query, top_n, mf)]:
                mismatches.append(case.id)

            union, seen = [], set()
            for c in dense + plainto + morph:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    union.append(c)

            gold = gold_para_set(parse_gold_clauses(case.references))
            measured.append({
                "id": case.id, "query": case.query, "gold": gold,
                "core": resolve_core_paras(case, gold),
                "dense": dense, "plainto": plainto, "morph": morph, "union": union,
                # 캐스케이드·판정에 쓸 dense 점수 — 합집합 후보만 남겨 메모리를 아낀다(전량 맵은 케이스마다 큼).
                "dense_score": {c.chunk_id: dense_score_all.get(c.chunk_id, 0.0) for c in union},
            })
            print(f"  {case.id}: dense {len(dense)} · plainto {len(plainto)} · morph {len(morph)} "
                  f"· self-check {'✓' if case.id not in mismatches else '✗'}")
    finally:
        close_pool()

    # ── 리랭커 모델 스윕: 각 모델을 로드(가능하면)해 케이스별 합집합에 점수를 매긴다(DB 불필요 단계). ──
    from sentence_transformers import CrossEncoder

    model_scores: dict[str, dict[str, dict[str, float]]] = {}  # key → case_id → {chunk_id: score}
    model_latency: dict[str, float] = {}
    model_meta: dict[str, dict] = {}
    for key in model_keys:
        try:
            device, cold_start_s, per_case, p50 = _score_with_reranker(CrossEncoder, REPLAY_MODELS[key], measured)
        except Exception as e:  # noqa: BLE001 — 한 모델 실패가 나머지 모델·비모델 셀·출력을 죽이지 않게 격리
            model_meta[key] = {"load_error": str(e)}
            print(f"[{key}] 측정 실패 — 건너뜀: {e}")
            continue
        model_scores[key] = per_case
        model_latency[key] = p50
        model_meta[key] = {"device": device, "cold_start_s": round(cold_start_s, 2), "latency_p50_s": round(p50, 4)}
        print(f"[{key}] device={device} · cold {cold_start_s:.1f}s · p50 {p50 * 1000:.0f}ms")

    # ── 셀 채점: 셀별 재정렬 규칙으로 top_n 콘텐츠를 만들어 정답 최초 등장 순위·재현율을 기록. ──
    def score_cell(order_fn) -> dict:
        by_case, pass_cnt = {}, 0
        for rc in measured:
            contents = [c.content for c in order_fn(rc)]
            fh, _ = rank_hit(contents, rc["gold"], "exact")
            by_case[rc["id"]] = fh
            pass_cnt += retrieval_pass(contents, rc["core"])
        return {"first_hits": by_case, "retrieval_pass": pass_cnt}

    cells: dict[str, dict] = {
        "plainto": score_cell(lambda rc: fuse_top_n(rc["dense"], rc["plainto"], k=k, n=top_n)),
        "morph": score_cell(lambda rc: fuse_top_n(rc["dense"], rc["morph"], k=k, n=top_n)),
        "morph_wrrf": score_cell(
            lambda rc: weighted_rrf([rc["dense"], rc["morph"]], [dense_weight, 1.0], k=k, n=top_n)),
        "morph→dense": score_cell(lambda rc: rerank_order(rc["morph"], rc["dense_score"])[:top_n]),
    }
    for key in model_scores:
        cells[key] = score_cell(
            lambda rc, key=key: rerank_order(fuse_top_n(rc["dense"], rc["morph"], k=k, n=top_n),
                                             model_scores[key][rc["id"]]))

    # ── 판정: 각 셀을 baseline(plainto) 대비 사전 확정 게이트로. 모델 셀만 지연 p50을 판정에 넣는다. ──
    base_fh = cells["plainto"]["first_hits"]
    n = len(base_fh)
    non_model = ["morph", "morph_wrrf", "morph→dense"]
    order = non_model + list(model_scores)
    verdicts: dict[str, dict] = {}
    print(f"\n{'셀':<30} {'Hit@1':>6} {'MRR':>6} {'pass':>5}  판정")
    base_hit1 = sum(1 for v in base_fh.values() if v == 1)
    print(f"{'plainto (baseline)':<30} {base_hit1:>4}/{n} {_mrr(base_fh, sorted(base_fh)):>6.3f} "
          f"{cells['plainto']['retrieval_pass']:>5}")
    for label in order:
        fh = cells[label]["first_hits"]
        hit1 = sum(1 for v in fh.values() if v == 1)
        p50 = model_latency.get(label, 0.0)  # 모델 셀만 지연 판정, 나머지는 0
        verdict = judge_adoption(base_fh, fh, p50)
        verdicts[label] = verdict
        mark = "채택기준 충족" if verdict["adopt"] else f"미충족: {'; '.join(verdict['reasons'])}"
        print(f"{label:<30} {hit1:>4}/{n} {_mrr(fh, sorted(fh)):>6.3f} {cells[label]['retrieval_pass']:>5}  {mark}")
    print(f"\nself-check 불일치 {len(mismatches)}건 {mismatches or ''}")
    for key, meta in model_meta.items():
        print(f"  [{key}] {meta}")

    ts = datetime.now(KST)
    out_path = Path(out_dir) / f"rerank_tokenization_replay_result_{ts.strftime('%Y%m%d_%H%M')}.json"
    out_path.write_text(json.dumps({
        "generated_at": ts.isoformat(),
        "k": k, "top_n": top_n, "dense_weight": dense_weight,
        "selfcheck_mismatches": mismatches,
        "cells": cells,
        "verdicts": verdicts,
        "models": model_meta,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 저장: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="토큰화 × 융합 × 리랭커 결합 오프라인 실측")
    parser.add_argument("--out-dir", default="docs/measurements")
    parser.add_argument("--top-n", type=int, default=TOP_N)
    parser.add_argument("--k", type=int, default=RRF_K)
    parser.add_argument("--dense-weight", type=float, default=DENSE_WEIGHT)
    parser.add_argument("--models", default=None,
                        help=f"쉼표 구분 리랭커 키(기본=전부). 가능: {','.join(REPLAY_MODELS)}")
    args = parser.parse_args()

    keys = list(REPLAY_MODELS) if not args.models else [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in keys if m not in REPLAY_MODELS]
    if unknown:
        print(f"알 수 없는 모델 키: {unknown}. 가능: {list(REPLAY_MODELS)}", file=sys.stderr)
        return 2
    return run_measure(args.out_dir, args.top_n, args.k, args.dense_weight, keys)


if __name__ == "__main__":
    raise SystemExit(main())
