export type PromptSuggestion = { id: string; label: string; prompt: string; recent: boolean };

const starters = [
  { label: "쉽게 설명해줘", prompt: "블록체인을 초등학생도 이해할 수 있게 쉬운 예시로 설명해줘." },
  { label: "정중한 이메일 쓰기", prompt: "일정이 겹쳐 회의를 정중하게 거절하는 이메일을 세 문장으로 써줘." },
  { label: "여행 일정 짜기", prompt: "서울에서 1박 2일로 걷기 좋은 여행 일정을 아침부터 저녁까지 짜줘." },
  { label: "코드 예제 보기", prompt: "JavaScript에서 배열의 중복 값을 제거하는 방법을 예제 코드와 함께 알려줘." },
  { label: "자연스러운 영어로", prompt: "다음 문장을 자연스러운 영어로 바꿔줘: 내일 회의를 오후로 옮길 수 있을까요?" },
  { label: "주말 취미 추천", prompt: "주말에 혼자 즐길 수 있는 취미 5가지를 준비물과 함께 추천해줘." },
  { label: "세 줄 요약 요령", prompt: "긴 글을 세 줄로 요약하는 요령을 단계별로 알려줘." },
  { label: "공부 계획 세우기", prompt: "영어 회화를 한 달 동안 꾸준히 연습하는 계획을 주 단위로 짜줘." },
  { label: "아이디어 떠올리기", prompt: "작은 카페의 인스타그램 게시물 아이디어를 10개 제안해줘." },
  { label: "SQL 예시", prompt: "고객별 주문 합계를 구하는 SQL 쿼리 예시와 설명을 보여줘." },
  { label: "고르는 기준 알기", prompt: "노트북을 고를 때 꼭 확인해야 할 기준 5가지를 알려줘." },
  { label: "문장 다듬기", prompt: "다음 문장을 더 간결하고 자연스럽게 다듬어줘: 저는 어제 친구를 만나서 같이 영화를 보러 갔었습니다." },
] as const;

function shuffled<T>(items: readonly T[], seed: number): T[] {
  const result = [...items];
  let state = seed >>> 0;
  const next = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  for (let index = result.length - 1; index > 0; index--) {
    const swap = Math.floor(next() * (index + 1));
    [result[index], result[swap]] = [result[swap], result[index]];
  }
  return result;
}

export function recentPrompts(titles: readonly string[], limit: number): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const title of titles) {
    const text = title.replace(/\s+/g, " ").trim();
    if (text.length < 4 || /^\S+\.[a-z0-9]{2,5}$/i.test(text)) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(text);
    if (result.length >= limit) break;
  }
  return result;
}

export function pickSuggestions(titles: readonly string[], seed: number, count = 3): PromptSuggestion[] {
  const recent = recentPrompts(titles, Math.max(0, Math.min(2, count - 1)))
    .map((text, index): PromptSuggestion => ({ id: `recent-${index}`, label: text, prompt: text, recent: true }));
  const fresh = shuffled(starters, seed).slice(0, count - recent.length)
    .map((entry, index): PromptSuggestion => ({ id: `starter-${index}`, ...entry, recent: false }));
  return [...recent, ...fresh];
}
