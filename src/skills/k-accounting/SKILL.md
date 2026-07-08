---
name: k-accounting
description: 회계기준서(K-GAAP, K-IFRS) 조항을 찾아 인용과 함께 답한다. "회계처리", "인식 시점", "측정", "공시" 같은 회계 용어나 특정 계정과목(리스·금융자산·퇴직급여 등), 조항 번호를 묻는 질의에서 사용한다.
---

이 스킬이 활성화되면 MCP 도구를 다음 순서로 사용한다.

1. `query_standards(query, standard_filter)`를 호출한다. `standard_filter`는 질의가 K-GAAP에 한정되면 `"GAAP"`, K-IFRS에 한정되면 `"KIFRS"`, 그 외에는 `"ALL"`로 둔다.
2. 응답 `status`가 `"done"`이면 `answer`를 답변 본문으로 제시하고, `citations`의 각 항목(`document_id`, `content`)을 근거로 함께 보여준다. `is_answerable`이 `false`이면 근거 부족을 그대로 알리고 답을 지어내지 않는다.
3. 응답 `status`가 `"interrupted"`이면 `interrupt.options`에 나열된 선택지 중 사용자 의도에 맞는 것을 고르거나 사용자에게 직접 물어본 뒤, 그 `action` 값으로 `resume_query(thread_id, action)`를 호출해 이어간다.
