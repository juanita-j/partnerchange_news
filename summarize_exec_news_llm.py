# -*- coding: utf-8 -*-
"""
news_raw.json → LLM 판별·요약 → news_summary.json

- 본문(또는 제목+요약)을 기반으로 실제 임원인사 기사인지 LLM이 판별.
- 관련 기사만 구조화된 JSON으로 요약 (회사명, 인사 유형, 대상 인물, 직책, 요약, 중요 포인트, 관련도, URL).
- 동일 인사 이벤트 중복 제거.
- 예외: 본문 추출 실패 시 제목+요약만 사용, LLM/JSON 실패 시 해당 기사 스킵, 결과 0건 시 빈 배열 저장.
"""
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone

OUTPUT_DIR = Path(__file__).resolve().parent
NEWS_RAW_JSON = OUTPUT_DIR / "news_raw.json"
NEWS_SUMMARY_JSON = OUTPUT_DIR / "news_summary.json"
DEBUG_SUMMARY_JSON = OUTPUT_DIR / "debug_summary.json"

# LLM 출력 스키마. items는 **인사변동 건별(인물별)** 로 항목을 나눔. 한 기업에 여러 명이면 같은 company로 항목을 여러 개 둠. **한 기사에 선임·사임·교체가 여러 명 나오면 전원 각각 item으로 넣고 누락 금지.**
# is_exec_news=true 이면 items(인물별 1개 이상) + article_url.
SUMMARY_SCHEMA = """
{
  "is_exec_news": true | false,
  "reason": "판별 이유 한 줄 (제외 시에만)",
  "items": [
    {
      "company": "인사가 **발생한** 회사(선임·사임이 이뤄진 쪽). 반드시 한 기업만. **다른 회사(A) 출신이 C회사에 선임된 경우 company=C**(선임된 회사). 같은 회사 내 재선임·승진이면 그 회사.",
      "previous_company": "선임·영입된 인물의 **이전 소속 회사**. 다른 회사 출신이 C에 선임된 경우만 채움(예: A 출신→A). 같은 회사 내 인사면 빈 문자열.",
      "category_flags": { "exec_personnel": true|false, "org_restructuring": true|false },
      "personnel_type": "인사 유형 (내정/선임/재선임/임명/안건·승인대기/연임포기 등 단계 구분)",
      "personnel_timing": "실행 시기 (언급 시만. 예: 2026년 3월부터, 주총 승인 후)",
      "person_name": "대상 인물 이름",
      "previous_role": "기존 직책",
      "new_role": "신규 직책",
      "org_changes": ["조직개편 내용 (예정은 (예정), 완료는 띄어쓰기 후 '완료')"],
      "summary_2sent": "해당 기업 관련 2문장 요약",
      "key_points": ["중요 포인트"],
      "bullet_points": ["해당 기업만의 브리핑 문장 (진행 단계·시기 포함)"],
      "relevance_score": 1-5,
      "reason_for_change": "단행 이유를 **명사형**으로 한 문장. '이는 ~ 위한 조치다' 등에서 ~ 부분 추출. '평가된다'→'평가', '재편한다'→'재편'처럼 서술형 어미(~된다·~한다·~했다) 사용 금지, 명사·명사구로만 쓴다. 부서명 알파벳 약어는 기사에 풀이 있으면 괄호 표기. 없으면 빈 문자열."
    }
  ],
  "article_url": "기사 URL (items 전체 공통)"
}
"""

SYSTEM_PROMPT = """당신은 한국 기업의 **임원인사**와 **주요 조직개편** 뉴스를 분류·요약하는 전문가입니다.

[포함할 기사] 두 범주 중 하나 이상 해당 시 포함.
1) 임원인사: 대표이사·사장·부사장·전무·상무 선임/재선임/영입/승진/이동/사임, 사내·사외이사 연임/재선임/연임 포기/교체, 이사회 개편
2) 주요 조직개편: 본부/실/센터/사업부/부문 신설·통합·폐지·개편·재편, 조직 슬림화·통폐합, TFT/전담조직 신설, AI·글로벌 조직 강화, 자회사/법인 단위 재편. **조직개편만 있는 기사도 포함.**

본문이 없어도 제목+요약만으로 판별 가능. 회사 차원의 주요 조직만 포함(본부·실·센터·사업부·부문·위원회·전사/자회사 단위).

[반드시 제외할 기사]
- 스포츠 선수 영입·이적, 연예인·홍보대사 영입, 연봉·보수 공시
- 단순 인력 충원, 일반 채용 확대
- 행사성 TF, 프로젝트성 임시 태스크포스
- 팀/파트/셀 등 소규모 단위 변경, 단순 명칭 변경만 있는 기사
- 단순 실적 발표, 인터뷰, 전망/코멘트만 있는 기사
- **롯데케미칼 및 설비·NCC·석유화학산단 통합·해체·구조재편** 등 설비 관련 기사(파트너사 롯데와 연관도 낮음). 이 경우 is_exec_news: false, reason: "롯데케미칼 및 설비 관련된 기사는 연관도가 낮음"

[관련도 점수]
- 5: 대표·사장급 명확한 선임/사임
- 3~4: 사외이사 연임 포기, 이사회 개편, 사내이사 신규 선임 등 거버넌스 인사
- 1~2: 인사변동이 불명확하거나 단순 언급만 → is_exec_news: false 권장

[category_flags] exec_personnel: 임원인사 해당 여부. org_restructuring: 주요 조직개편 해당 여부. 둘 다 true일 수 있음.

[진행 여부·시기 구분] 반드시 구분해서 요약하세요.
- **임원인사**: '내정'(예정)·'선임'/'임명'(확정)·'주총 안건'/'승인 대기'(통과 여부가 안건)를 구분. personnel_type에 단계를 넣고(예: 사내이사 신규 선임 안건, 부회장 내정, 대표이사 선임). **personnel_timing "주총 승인 후" 사용 조건**: **아직 주총이 열리지 않았거나, 안건으로 상정·승인 대기 단계**일 때만 "주총 승인 후"를 넣는다. **주주총회에서 안건이 상정/등록된 경우**(기사에 "주주총회에서 ~~ 안건이 상정되었다", "안건으로 등록되었다" 등 **아직 결의 전**일 때): **한 명당 한 문장만** 쓴다. "대표이사 안건"과 "사내이사 재선임" 등이 같은 인물에 대해 나오면 **둘을 나누지 말고** **"주주총회에서 '(이름)' (현재 직함)의 (선임·재선임 등) 안건이 도출됨"** 한 문장으로만 쓴다. 예: 주주총회에서 '이재원' 대표이사의 사내이사 재선임 안건이 도출됨. items도 해당 인물당 하나만 두고, bullet_points도 위 한 문장만. **이미 진행된 주총(과거 완료)**: 기사에 "이날 주주총회에서 … 승인됐다", "선임했고", "재선임했다", "가결되었다", "원안대로 승인됐다고 밝혔다" 등 **이미 주총이 열려 결의가 완료된** 내용이 나오면 personnel_timing을 **비워 두고**, bullet_points·요약에 "주총 승인 후"와 "예정"을 **절대 넣지 말 것**. 확정된 사실만 쓴다. 예: "이날 주주총회에서는 6개 안건 모두 원안대로 승인됐다. 김훈 기획부문장을 선임했고, 이필재 사외이사를 재선임했다" → personnel_timing 빈 문자열, 요약은 "'김훈' 기획부문장의 사내이사 선임, '이필재' 사외이사 재선임" (주총 승인 후·예정 없음). 그 외 실행 시기(2026년 3월부터 등)가 언급되면 personnel_timing에만 넣고, 문장 끝에 괄호로 "(주총 승인 후)" 적지 말 것.
- **조직개편**: '예정'과 '완료'를 구분. 완료는 괄호 없이 띄어쓰기 한 칸 + '완료': 예) "글로벌사업부 통합 완료". 예정은 "(예정)" 표기: "AI전략본부 신설(예정)". 시기 언급 시: "DX부문 재편(예정, 2분기)".
- **단행 시기 반영**: 기사에 "지난해 말", "올해 3월", "2025년 4분기", "OO시기에 임원인사/조직개편을 단행했다" 등 **단행된 시기**가 명시되어 있으면 반드시 요약에 포함한다. 임원인사는 personnel_timing에, 조직개편은 org_changes·bullet_points 문장 **맨 앞에** 넣는다.
- **조직개편 진행 시기 필수**: 기사에 조직개편이 **언제** 이뤄졌는지("지난해 말", "올해 3월", "지난 해", "2025년 4분기" 등) 나오면 **빼먹지 말고** org_changes·bullet_points 각 문장 **맨 앞에** 반드시 쓴다. 예: 기사에 "지난해 말 고객가치혁신실 산하에 CX 조직을 신설했다" → org_changes에 **"지난해 말 고객가치혁신실 산하에 CX(Customer Experience) 조직 신설"** 처럼 시기(지난해 말)를 포함한다.

[org_changes] 조직개편 해당 시 배열로 채움. 구체적 동작 단어: 신설, 통합, 폐지, 재편 등. 완료는 문장 끝에 띄어쓰기 한 칸 + '완료'(괄호 없음). 예정은 '(예정)'. 예: "AI전략본부 신설(예정)", "글로벌사업부 통합 완료". '개편·변동·변화'는 쓰지 말 것.
- **단행 시기(필수)**: 기사에 "지난해 말", "올해 3월" 등 조직개편 **진행 시기**가 있으면 org_changes 각 항목 **맨 앞에 반드시** 쓴다. 예: "지난해 말 고객가치혁신실 산하에 CX(Customer Experience) 조직 신설".
- **연관 조직명**: 신설·개편된 조직이 **어느 부서 산하/소속**인지 기사에 나오면 반드시 포함한다. 예: "고객가치혁신실 산하에 CX(Customer Experience) 조직 신설" (상위 조직 '고객가치혁신실' 포함).
- **조직 담당 업무**: 기사에 신설·개편된 조직이 **어떤 업무를 담당하는지**("▲… ▲… 등 업무 담당", "~역할을 한다" 등) 나오면, 해당 조직 신설 항목 **바로 다음**에 org_changes 요소로 한 줄 요약해 추가한다. 예: 첫 요소 "지난해 말 고객가치혁신실 산하에 CX(Customer Experience) 조직 신설", 둘째 요소 "CX조직은 ▲다양한 채널에서 고객 직접 대면을 통한 니즈 수집 및 분석 ▲서비스 등 개선점 제안 ▲중장기 고객가치 향상 방안 등 업무 담당 예정".
- **부서명 알파벳 약어**: 기사 본문에 부서(본부·사업부 등)의 알파벳 약어에 대한 설명이 있으면, 요약·org_changes·bullet_points에 쓸 때 **약어 옆에 괄호로 풀어 쓴다**. 예: 기사에 "ES(Eco Solution) 사업본부", "냉난방공조(HVAC) 사업"이 나오면 → "LG전자 ES(Eco Solution) 사업부", "HVAC(냉난방공조) 사업"처럼 표기. 본문에 풀이가 없으면 괄호 추가하지 않음.
- **'OO 중심으로 사업구조 재편'**: 기사에 "OO 중심으로 사업구조 재편", "사업구조를 재편하기로" 등이 나오면 요약에 **반드시** 다음 두 가지를 포함한다. (1) **어떤 사업 중심으로 재편하는지**: 예) "AI(인공지능) 중심으로 사업구조 재편 예정". (2) **재편과 함께 진행하는 사업·계획이 있으면**: 협업 파트너, 구축·제공할 사업 내용 등을 bullet_points 또는 org_changes에 한 줄로. 예) "AI 스타트업 리플렉션과 협업해 국내 최대 250MW급 AI 데이터센터 구축, 한국 기업·정부에 AI 클라우드 서비스 및 맞춤형 AI 모델·시스템 제공 예정".

[previous_role·new_role·personnel_type] 기존 직책(previous_role)은 현재/이전 직위 또는 소속(예: CFO, 사외이사, 현대모비스 FTCI 담당(전무)). 신규 직책(new_role)은 취임·선임되는 직위·담당(예: 감사위원회 위원장 담당 전망). **재선임·연임의 경우 new_role은 빈 문자열로 두고 previous_role만 채울 것** (동일 직위이므로 중복 불필요). **기사에 직함이 없으면 previous_role·new_role은 빈 문자열로 두고 '없음'이라고 쓰지 말 것.** 인사 유형(personnel_type)은 변동 내용(예: 사내이사 재선임, 신규 사내이사 선임). personnel_type에 직함이 이미 들어가면 previous_role에는 이전 직함/소속만 넣어 중복 없이. 연임 포기처럼 직책이 하나면 previous_role만 채우고 personnel_type은 '연임 포기'만.

[company·previous_company] **company**는 인사가 **발생한(선임·사임이 이뤄진)** 회사. A회사 B 사장이 C회사 대표로 선임된 경우 → company=**C**(선임된 회사). **previous_company**는 선임된 인물의 **이전 소속 회사**로, **다른 회사**일 때만 채움(위 예: A). 같은 회사 내 재선임·승진·이동이면 previous_company 빈 문자열. 제목은 "C, 임원인사 진행"이 되도록 company를 선임된 쪽으로 통일.

[bullet_points] 각 item은 **한 명의 인물(또는 한 조직개편)** 만 담음. 브리핑 스타일, 해당 인물/항목 관련 1~3개. 명사형 또는 "~함"체. **진행 단계(내정/선임/안건 등)와 실행 시기(언급 시) 포함.** 인물명은 작은따옴표(')로 감쌈. **이름 불명 시 제외**: 기사에서 인물 이름을 파악할 수 없으면(person_name이 빈 문자열이거나 "없음") **해당 item 자체를 만들지 말 것**. "'없음' 공동대표의 단독대표 선임"처럼 이름 없는 불렛 금지. **직함·역할명을 이름으로 쓰지 말 것**: "사외이사", "대표이사", "이사회", "감사위원" 같은 직함/역할 단어만 있으면 실명이 아니므로 person_name을 빈 문자열로 두고 item 자체를 만들지 말 것. 예) "사외이사가 이사회 의장으로 선임" → 특정 실명이 없으면 item 생성 금지. **중복 불렛 금지**: 같은 인사에 대해 이름만 다르고 뒤 문장이 같으면 **실명 한 줄만** 쓴다. "'임재철' 재무본부장의 사내이사 선임"과 "'임재철' 롯데쇼핑 재무본부장의 사내이사 선임"처럼 같은 인물·같은 인사면 **회사·부서까지 포함한 더 구체적인 한 줄만** 쓴다. **주주총회에서 안건 상정/등록만 된 경우**(아직 결의 전): 같은 인물에 대해 "안건"과 "재선임/선임"을 **두 개로 쓰지 말고**, **한 문장**으로만 쓴다. **"주주총회에서 '(이름)' (현재 직함)의 (사내이사 재선임 등) 안건이 도출됨"**. 예: 주주총회에서 '이재원' 대표이사의 사내이사 재선임 안건이 도출됨. **다른 회사 출신이 타사에 선임·영입된 경우** bullet_points·요약에 반드시 "A 출신 B 사장이 C 대표로 선임" 형식으로 쓴다. 한 기사에 여러 명이면 인물별로 나눔.
- 임원인사 예(같은 회사): '정의선' 회장의 사내이사 재선임, '성낙섭' FTCI 담당(전무)의 신규 사내이사 선임.
- 임원인사 예(주총 안건 상정만, 한 문장으로): 주주총회에서 '이재원' 대표이사의 사내이사 재선임 안건이 도출됨. (같은 인물에 대해 "대표이사 안건"과 "사내이사 재선임" 두 개 쓰지 말 것)
- 임원인사 예(타사 영입): '박현주' BNY 뉴욕멜론은행 한국 대표의 사외이사 신규 선임 → previous_company 채움 시 bullet "A 출신 B 사장이 C 대표로 선임" 형식.
- 조직개편 예: AI전략본부 신설(예정), 글로벌사업부 통합 완료. **시기 필수+연관 조직**: 기사에 시기("지난해 말" 등)가 나오면 빼먹지 말고 맨 앞에 쓴다. 예: "지난해 말 고객가치혁신실 산하에 CX(Customer Experience) 조직 신설". **담당 업무**: 기사에 해당 조직의 업무·역할("▲… ▲… 등 업무 담당" 등)이 나오면 bullet_points에 **다음 줄**로 요약해 넣는다. 예: "CX조직은 ▲다양한 채널에서 고객 직접 대면을 통한 니즈 수집 및 분석 ▲서비스 등 개선점 제안 ▲중장기 고객가치 향상 방안 등 업무 담당 예정". **사업구조 재편**: "OO 중심으로 사업구조 재편"이 있으면 (1) OO(어떤 사업) 중심 재편 한 줄, (2) 함께 진행하는 사업(협업·구축·제공 내용 등) 한 줄.

[reason_for_change] **임원인사 또는 조직개편 단행 이유**를 기사에서 찾아 각 item(기업)별로 **명사형**으로 한 문장 작성.
- **명사형만 사용**: 기사에 "평가된다", "재편한다", "~했다" 등이 있어도 서술형 어미를 빼고 명사·명사구로 쓴다. 예: "평가된다" → "평가", "재편한다" → "재편", "달성에 따라 재선임됨" → "달성에 따른 재선임", "~하기 위함"·"~를 위한 조치" 등 명사형으로 끝낸다.
- **추출 패턴**: "임원을 배치했다. 이는 ~~ 위한 조치다.", "~하기 위한 조치", "~를(을) 위해 ~했다" 등에서 **"~~" 또는 "~" 부분**이 단행 이유. "이를 통해 ~", "~목적", "~배경으로" 뒤에 오는 내용도 이유로 활용.
- 한 문장으로 정리. 기사에 명시가 없으면 빈 문자열. 예: "신성장동력인 냉난방공조(HVAC) 사업을 키우기 위해 외부 기업 인수 전략을 적극 구사하기 위함", "현대모비스 대표이사로서 지정학적 리스크, 전기차 캐즘 등에도 불구 사상 최대 매출·영업이익 실적 달성에 따른 재선임".

[items 분리 원칙] **한 건의 인사변동(한 명의 인물)당 items에 항목 하나.** 한 기사에 한 기업만 나와도 임원인사가 여러 명이면 **인물별로** 항목을 나누세요. 같은 회사(company)가 여러 번 나와도 됨.
- **기사에 이름이 언급된 인물은 한 명도 빠짐없이** items에 넣으세요. 선임·사임·내정·교체 등 **변동이 있는 모든 인물을 각각 별도 item**으로 작성. **한 명이라도 누락 금지.** 예: "유명희, 송재혁 이사 사임" → 유명희 1건 + 송재혁 1건, 총 2개 item.
- **주총에서 여러 명 선임·사임·교체**: 기사에 "OO 이사 선임", "OO 감사위원 선임", "OO에서 OO로 교체"(→ 기존 이사 사임 + 신규 선임 각각 item), "OO 이사 사임" 등이 **함께** 나오면 **선임·사임·교체된 모든 인물을 각각** item으로 넣는다. **일부만 넣고 나머지를 빼면 안 된다.** 예: "제57기 주총에서 김용관 이사 선임, 허은녕 감사위원 선임, 송재혁에서 김용관으로 교체됐고, 유명희 이사 사임" → items **4개**: (1) 김용관(DS부문 경영전략총괄) 사내이사 선임 (2) 허은녕(서울대 교수) 감사위원 선임 (3) 송재혁 사내이사 사임 (4) 유명희 사외이사 사임.
- **한 기업·여러 명**: 예) 현대모비스 기사에 정의선 사내이사 재선임, 성낙섭 신규 사내이사 선임, 제임스 김 사외이사 재선임, 박현주 사외이사 신규 선임 → items 4개(모두 company '현대모비스', person_name·personnel_type·previous_role·new_role은 각각 다르게).
- **한 기사에 여러 기업**: 네이버·카카오 등 두 기업이 같이 나오면 기업별로 구분해 각 기업의 인물별 항목을 넣으세요. 회사명(company)은 항목마다 **한 기업만**(쉼표로 "네이버, 카카오" 같이 쓰지 말 것). 기사 URL은 article_url 하나만 두세요.

[출력]
반드시 유효한 JSON 한 덩어리만 출력. 앞뒤 설명·마크다운 없이."""

USER_PROMPT_TEMPLATE = """아래 뉴스가 **임원인사** 또는 **주요 조직개편**(본부/실/센터/사업부 신설·통합·폐지·개편 등) 기사인지 판별해 주세요.
본문이 "(없음)"이어도 제목과 요약만으로 판단합니다. 해당 시 category_flags와 org_changes를 채우고, 아니면 is_exec_news: false와 reason만 채우세요.

제목: {title}
요약: {description}
본문(일부): {body}

[참고] 임원인사만: exec_personnel=true, org_restructuring=false. 조직개편만: exec_personnel=false, org_restructuring=true, org_changes 채움. 둘 다: 둘 다 true. 스포츠/연예/보수/채용확대/소규모 팀 변경 → 제외. **롯데케미칼·NCC·설비·석유화학산단 통합/해체/구조재편** 기사는 연관도 낮음 → is_exec_news: false, reason: "롯데케미칼 및 설비 관련된 기사는 연관도가 낮음". **주총 안건 상정/등록만** 나온 경우 bullet: "주주총회에서 '(이름)'이/가 (직책)으로 (선임·재선임 등) 되는 안건이 도출됨". **한 기사에 여러 명 임원인사(선임·사임·교체)가 나오면 선임·사임·교체된 모든 인물을 각각 item으로 넣고, 한 명이라도 누락 금지.** **이미 진행된 주총**(이날 주주총회에서 … 승인됐다, 선임했고, 재선임했다, 가결되었다 등)이면 personnel_timing 빈 문자열, **"주총 승인 후"·"예정" 절대 사용 금지.** 요약은 "'OO' 직함의 사내이사 선임, 'OO' 사외이사 재선임"처럼 확정 사실만. **조직개편 시기 필수**: 기사에 "지난해 말", "올해 3월" 등 조직개편 진행 시기가 나오면 org_changes 각 문장 **맨 앞에 반드시** 포함. 예: "지난해 말 고객가치혁신실 산하에 CX(Customer Experience) 조직 신설". **조직 담당 업무**: 기사에 해당 조직이 담당하는 업무(▲… 등)가 나오면 org_changes/bullet_points에 그다음 줄로 요약 포함. **단행 시기**: 임원인사는 personnel_timing에. **연관 조직명**: "OO 산하에", "OO 소속" 등 상위·연관 조직이 있으면 요약에 포함. **사업구조 재편**: "OO 중심으로 사업구조 재편"이 있으면 (1) 어떤 사업(OO) 중심인지, (2) 함께 진행하는 사업(협업·구축·제공 등)을 bullet_points/org_changes에 각각 포함. **부서명**: 알파벳 약어는 기사에 풀이 있으면 괄호 표기. **company**: 인사가 **발생한** 회사(선임된 쪽). A 출신이 C에 선임 시 **C**. **previous_company**: 이전 소속 회사(다른 회사일 때만, 위 예: A). **reason_for_change**: "이는 ~ 위한 조치다" 등에서 ~ 부분 추출. **명사형만**. 없으면 빈 문자열.

출력 형식 (이 키만 사용, JSON만 출력):
{schema}"""


def _get_openai_client():
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai 패키지가 필요합니다. pip install openai")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경 변수가 없습니다.")
    return OpenAI(api_key=api_key)


def _role_or_empty(val) -> str:
    """직함 값이 '없음'이면 빈 문자열, 아니면 strip한 값."""
    v = (val or "").strip()
    return "" if v == "없음" else v


def _build_article_text(article: dict) -> str:
    """본문 우선, 없으면 제목+요약."""
    body = (article.get("body") or "").strip()
    if body and len(body) > 50:
        return body[:4000]
    title = (article.get("title") or "").strip()
    desc = (article.get("description") or "").strip()
    return f"{title}\n{desc}"[:2000]


def _clear_timing_when_article_reports_completed_shmeeting(summaries: list[dict], body: str) -> None:
    """기사 본문에 이미 주총 가결·선임 완료 표현이 있으면 '주총 승인 후'·예정을 붙이지 않도록 인사 시기를 제거."""
    if not body or not summaries:
        return
    body_lower = body.replace(" ", "")
    # 이미 진행된 주총(과거 완료) 지시어: 승인됐다, 가결, 선임했, 재선임했 등
    completed_markers = ("승인됐다", "승인됐다고", "가결되었다", "가결했다", "선임했", "재선임했", "원안대로승인")
    if not any(m in body_lower for m in completed_markers):
        return
    for s in summaries:
        timing = (s.get("인사 시기") or "").strip()
        if timing and "주총" in timing and "승인" in timing:
            s.pop("인사 시기", None)


def _one_item_to_summary(item: dict, url: str) -> dict:
    """items[] 한 요소를 news_summary 항목 형식으로 변환."""
    company = (item.get("company") or "").strip()
    person = (item.get("person_name") or "").strip()
    action_type = (item.get("personnel_type") or "").strip()
    personnel_timing = (item.get("personnel_timing") or "").strip()
    cf = item.get("category_flags") or {}
    exec_personnel = bool(cf.get("exec_personnel"))
    org_restructuring = bool(cf.get("org_restructuring"))
    org_changes_raw = item.get("org_changes")
    org_changes = [str(s).strip() for s in org_changes_raw] if isinstance(org_changes_raw, list) else []
    org_changes = [s for s in org_changes if s][:15]
    bullet_points = item.get("bullet_points")
    if not isinstance(bullet_points, list):
        bullet_points = []
    bullet_points = [str(s).strip() for s in bullet_points if s][:10]
    prev_company = (item.get("previous_company") or "").strip()
    out = {
        "회사명": company,
        "출신 회사": prev_company,
        "인사 유형": action_type,
        "대상 인물": person,
        "기존 직책": _role_or_empty(item.get("previous_role")),
        "신규 직책": _role_or_empty(item.get("new_role")),
        "2문장 요약": (item.get("summary_2sent") or "").strip(),
        "중요 포인트": item.get("key_points") if isinstance(item.get("key_points"), list) else [],
        "bullet_points": bullet_points,
        "category_flags": {"exec_personnel": exec_personnel, "org_restructuring": org_restructuring},
        "org_changes": org_changes,
        "관련도 점수": int(item.get("relevance_score", 0)) if item.get("relevance_score") is not None else 0,
        "기사 URL": url,
    }
    if personnel_timing:
        out["인사 시기"] = personnel_timing
    reason = (item.get("reason_for_change") or "").strip()
    if reason:
        out["진행 이유"] = reason
    return out


def _parse_llm_response(text: str, url: str) -> tuple[list[dict], dict]:
    """
    LLM 응답 텍스트 파싱.
    반환: (summary_item 리스트, debug_필드용 dict). 한 기사에 여러 기업이면 리스트에 기업별 항목이 여러 개.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", text)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    company, person, action_type, exclude_reason = "", "", "", ""

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 실패 (link={url[:50]}…): {e}")
        return [], {
            "company": "",
            "person": "",
            "action_type": "",
            "exclude_reason": f"JSON 파싱 실패: {e!s}",
        }

    include = data.get("is_exec_news")
    if include is None:
        include = bool(data.get("items"))
    if not include:
        exclude_reason = (data.get("reason") or "").strip() or "is_exec_news=false"
        return [], {
            "company": (data.get("company") or "").strip(),
            "person": (data.get("person_name") or "").strip(),
            "action_type": (data.get("personnel_type") or "").strip(),
            "exclude_reason": exclude_reason,
            "exec_personnel": False,
            "org_restructuring": False,
            "org_changes": [],
        }

    # news_raw.json의 link(Naver News URL 우선)를 항상 사용 — LLM이 반환하는 article_url은
    # 원본 언론사 URL이 될 수 있어 만료·삭제 시 열리지 않으므로 무시한다.
    article_url = url
    items_raw = data.get("items")
    summaries = []

    if isinstance(items_raw, list) and len(items_raw) > 0:
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            company = (it.get("company") or "").strip()
            if not company:
                continue
            summaries.append(_one_item_to_summary(it, article_url))
    else:
        # 기존 flat 형식: 상위에 company, person_name 등
        company = (data.get("company") or "").strip()
        person = (data.get("person_name") or "").strip()
        action_type = (data.get("personnel_type") or "").strip()
        cf = data.get("category_flags") or {}
        exec_personnel = bool(cf.get("exec_personnel"))
        org_restructuring = bool(cf.get("org_restructuring"))
        org_changes_raw = data.get("org_changes")
        org_changes = [str(s).strip() for s in org_changes_raw] if isinstance(org_changes_raw, list) else []
        org_changes = [s for s in org_changes if s][:15]
        bullet_points = data.get("bullet_points")
        if not isinstance(bullet_points, list):
            bullet_points = []
        bullet_points = [str(s).strip() for s in bullet_points if s][:10]
        summary = {
            "회사명": company,
            "출신 회사": (data.get("previous_company") or "").strip(),
            "인사 유형": action_type,
            "대상 인물": person,
            "기존 직책": _role_or_empty(data.get("previous_role")),
            "신규 직책": _role_or_empty(data.get("new_role")),
            "2문장 요약": (data.get("summary_2sent") or "").strip(),
            "중요 포인트": data.get("key_points") if isinstance(data.get("key_points"), list) else [],
            "bullet_points": bullet_points,
            "category_flags": {"exec_personnel": exec_personnel, "org_restructuring": org_restructuring},
            "org_changes": org_changes,
            "관련도 점수": int(data.get("relevance_score", 0)) if data.get("relevance_score") is not None else 0,
            "기사 URL": article_url,
        }
        pt = (data.get("personnel_timing") or "").strip()
        if pt:
            summary["인사 시기"] = pt
        reason = (data.get("reason_for_change") or "").strip()
        if reason:
            summary["진행 이유"] = reason
        summaries.append(summary)

    if not summaries:
        return [], {"company": "", "person": "", "action_type": "", "exclude_reason": "items 비어 있음", "exec_personnel": False, "org_restructuring": False, "org_changes": []}

    first = summaries[0]
    cf = first.get("category_flags") or {}
    debug_extra = {
        "company": first.get("회사명", ""),
        "person": first.get("대상 인물", ""),
        "action_type": first.get("인사 유형", ""),
        "exclude_reason": "",
        "exec_personnel": bool(cf.get("exec_personnel")),
        "org_restructuring": bool(cf.get("org_restructuring")),
        "org_changes": first.get("org_changes", []),
    }
    return summaries, debug_extra


def _is_body_missing(article: dict) -> bool:
    """본문이 비어 있거나 너무 짧으면 True (제목+요약만 사용한 경우)."""
    body = (article.get("body") or "").strip()
    return len(body) <= 50


def _call_llm_once(client, article: dict) -> tuple[dict | None, dict]:
    """
    한 건 기사에 대해 LLM 호출. 최대 1회 재시도.
    반환: (summary_item 또는 None, debug_record)
    debug_record: title, is_relevant, exclude_reason, raw_llm_response, company, person, action_type, body_missing
    """
    title = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()
    body = _build_article_text(article)
    url = (article.get("link") or "").strip()
    body_missing = _is_body_missing(article)

    def make_debug(
        is_relevant: bool,
        raw: str,
        exclude_reason: str,
        company: str,
        person: str,
        action_type: str,
        exec_personnel: bool = False,
        org_restructuring: bool = False,
        org_changes: list | None = None,
    ) -> dict:
        return {
            "title": title,
            "is_relevant": is_relevant,
            "exclude_reason": exclude_reason,
            "raw_llm_response": raw,
            "company": company,
            "person": person,
            "action_type": action_type,
            "body_missing": body_missing,
            "exec_personnel": exec_personnel,
            "org_restructuring": org_restructuring,
            "org_changes": org_changes or [],
        }

    user = USER_PROMPT_TEMPLATE.format(
        title=title,
        description=description,
        body=body[:3000] if body else "(없음)",
        schema=SUMMARY_SCHEMA.strip(),
    )

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            raw_text = (resp.choices[0].message.content or "").strip()
            summaries, debug_extra = _parse_llm_response(raw_text, url)
            if summaries and body_missing:
                for s in summaries:
                    s["요약_근거"] = "제목·요약 기반"
            # 이미 진행된 주총(가결·선임 완료)인데 LLM이 '주총 승인 후'를 넣은 경우 제거
            if body and summaries:
                _clear_timing_when_article_reports_completed_shmeeting(summaries, body)
            return summaries, make_debug(
                is_relevant=bool(summaries),
                raw=raw_text,
                exclude_reason=debug_extra.get("exclude_reason", ""),
                company=debug_extra.get("company", ""),
                person=debug_extra.get("person", ""),
                action_type=debug_extra.get("action_type", ""),
                exec_personnel=debug_extra.get("exec_personnel", False),
                org_restructuring=debug_extra.get("org_restructuring", False),
                org_changes=debug_extra.get("org_changes", []),
            )
        except Exception as e:
            print(f"LLM 호출 실패 attempt={attempt+1} (link={url[:50]}…): {e}")
            if attempt == 1:
                return [], make_debug(
                    is_relevant=False,
                    raw="",
                    exclude_reason=f"LLM 호출 실패: {e!s}",
                    company="",
                    person="",
                    action_type="",
                    exec_personnel=False,
                    org_restructuring=False,
                    org_changes=[],
                )
            import time
            time.sleep(1)
    return [], make_debug(False, "", "LLM 호출 실패(재시도 소진)", "", "", False, False, [])


def _dedupe_items(items: list[dict]) -> list[dict]:
    """동일 인사 이벤트(회사+대상 인물+유형) 중복 제거. 관련도 높은 쪽 유지."""
    if not items:
        return []
    key_to_best: dict[tuple, dict] = {}
    for it in items:
        company = (it.get("회사명") or "").strip()
        person = (it.get("대상 인물") or "").strip()
        ptype = (it.get("인사 유형") or "").strip()
        key = (company, person, ptype) if (company or person) else (it.get("기사 URL", ""),)
        existing = key_to_best.get(key)
        score = int(it.get("관련도 점수", 0))
        if existing is None or score > int(existing.get("관련도 점수", 0)):
            key_to_best[key] = it
    return list(key_to_best.values())


def main() -> int:
    if not NEWS_RAW_JSON.exists():
        print(f"오류: {NEWS_RAW_JSON} 이 없습니다. 먼저 send_exec_news_timed.py 를 실행하세요.")
        return 1

    with open(NEWS_RAW_JSON, "r", encoding="utf-8") as f:
        raw = json.load(f)

    articles = raw.get("articles") or []
    if not articles:
        payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "items": []}
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(NEWS_SUMMARY_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        with open(DEBUG_SUMMARY_JSON, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "articles": []}, f, ensure_ascii=False, indent=2)
        print("수집 기사 0건 → news_summary.json 빈 배열로 저장")
        return 0

    try:
        client = _get_openai_client()
    except Exception as e:
        print(f"오류: {e}")
        return 1

    items = []
    debug_records = []
    for i, art in enumerate(articles):
        result_list, debug_record = _call_llm_once(client, art)
        debug_records.append(debug_record)
        for s in result_list:
            s["pubDate"] = art.get("pubDate", "")
            items.append(s)
        if (i + 1) % 5 == 0 and i + 1 < len(articles):
            import time
            time.sleep(0.5)

    items = _dedupe_items(items)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_raw": str(NEWS_RAW_JSON.name),
        "items": items,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(NEWS_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    debug_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_raw": str(NEWS_RAW_JSON.name),
        "total_articles": len(articles),
        "included_count": len(items),
        "articles": debug_records,
    }
    with open(DEBUG_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(debug_payload, f, ensure_ascii=False, indent=2)

    print(f"요약 완료: {len(items)}건 → {NEWS_SUMMARY_JSON}")
    print(f"디버그: 기사별 처리 결과 {len(debug_records)}건 → {DEBUG_SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
