"""scripts/rerank_tokenization_replay.py 순수부 테스트 — 재정렬·가중 융합 헬퍼.

DB·코퍼스·리랭커 모델이 필요한 실측 실행부(run_measure)는 스크립트 self-check와 실측 리포트로 검증하고,
여기서는 DB·모델 없이 도는 순수 함수만 고정한다.
토큰화·BM25·대칭 RRF·판정 등 재사용 조각은 각 원본 하니스 테스트가 이미 덮으므로 여기서 재검하지 않는다.
"""
import pytest

from scripts.rerank_tokenization_replay import rerank_order, weighted_rrf
from src.models.schemas import RetrievedChunk

pytestmark = pytest.mark.unit


def _chunk(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=chunk_id, document_id="doc", content=f"내용 {chunk_id}", score=0.0, metadata={})


class TestRerankOrder:
    """rerank_order() — 후보를 점수 내림차순으로 재정렬(크로스인코더·dense 캐스케이드 공용)."""

    def test_sorts_by_score_desc(self):
        # 융합 순서는 a,b,c지만 점수는 b>c>a → 재정렬 후 b,c,a. 낮게 융합된 정답을 위로 끌어올리는 경로.
        chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
        assert [c.chunk_id for c in rerank_order(chunks, {"a": 0.1, "b": 0.9, "c": 0.5})] == ["b", "c", "a"]

    def test_preserves_all_candidates(self):
        # 재정렬은 순서만 바꾸고 후보를 버리지 않는다(임계값 필터링은 rerank 노드의 별개 책임).
        assert len(rerank_order([_chunk("a"), _chunk("b")], {"a": 0.2, "b": 0.8})) == 2

    def test_missing_score_sinks_to_bottom(self):
        # dense 캐스케이드에서 후보 풀에 dense 점수가 없는 경우의 방어 — KeyError로 죽지 않고 맨 뒤로 보낸다.
        chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
        assert [c.chunk_id for c in rerank_order(chunks, {"a": 0.5, "c": 0.9})] == ["c", "a", "b"]


class TestWeightedRrf:
    """weighted_rrf() — 리스트별 가중 RRF. dense를 무겁게 줘 morph 노이즈가 dense 상위를 밀어내지 못하게 한다."""

    def test_dense_weight_dominates_sparse(self):
        # weights=[2,1]이면 dense rank1(D)·rank2(x)가 sparse rank1(S)보다 앞선다 — dense 상위 보존.
        dense = [_chunk("D"), _chunk("x")]
        sparse = [_chunk("S"), _chunk("y")]
        out = [c.chunk_id for c in weighted_rrf([dense, sparse], [2.0, 1.0], k=60, n=10)]
        assert out == ["D", "x", "S", "y"]

    def test_shared_doc_accumulates(self):
        # 양쪽 리스트 rank1에 함께 든 문서는 점수가 합산돼 최상위가 된다.
        a = [_chunk("shared"), _chunk("a2")]
        b = [_chunk("shared"), _chunk("b2")]
        assert weighted_rrf([a, b], [1.0, 1.0], k=60, n=10)[0].chunk_id == "shared"

    def test_respects_top_n(self):
        dense = [_chunk(f"d{i}") for i in range(5)]
        assert len(weighted_rrf([dense], [1.0], k=60, n=3)) == 3
