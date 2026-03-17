# Send News Mail 워크플로 점검 결과

점검 일시: 2026-03-17 (로컬 기준)

---

## 1. 기본 브랜치 / 워크플로 위치

| 항목 | 결과 | 비고 |
|------|------|------|
| 현재 로컬 브랜치 | `main` | OK |
| 원격 기본 브랜치(HEAD) | `main` | OK |
| 워크플로 파일 위치 | `.github/workflows/send-news-mail.yml` | 기본 브랜치에 있으면 스케줄 실행 대상 |
| 로컬 ↔ 원격 동기화 | `Your branch is up to date with 'origin/main'` | 푸시 누락 없음 |

**결론:** 스케줄은 **기본 브랜치(main)** 에서만 실행되며, 워크플로 파일이 main에 있고 원격과 동기화되어 있으므로 **이 부분은 문제 없음**.

---

## 2. 워크플로 YAML / cron 문법

| 항목 | 결과 | 비고 |
|------|------|------|
| cron 4개 | `0 1 * * *`, `0 3 * * *`, `0 6 * * *`, `0 9 * * *` | UTC 01/03/06/09 = KST 10/12/15/18시 |
| cron 문법 | 5필드, 분 시 일 월 요일 | 유효 |
| workflow_dispatch | 있음 | 수동 실행 가능 |
| name | `Send News Mail` | Actions 탭에서 이 이름으로 표시 |

**결론:** YAML 및 스케줄 설정 **이상 없음**.

---

## 3. 저장소 활동(60일 미활동 여부)

| 항목 | 결과 | 비고 |
|------|------|------|
| 최근 커밋 (저장소) | 2026-03-16 23:34 KST | 최근 활동 있음 |
| 워크플로 파일 마지막 변경 | 2026-03-16 22:38 KST | 최근 수정됨 |

**결론:** 60일간 푸시 없음으로 인한 **자동 비활성화 가능성은 낮음**.  
(다만 과거에 이미 비활성화됐다면, 최근 푸시만으로는 자동 재활성화되지 않음.)

---

## 4. 로컬에서 확인 불가 · GitHub에서만 확인 가능한 항목

아래는 **GitHub 웹(Actions/설정)** 에서만 확인할 수 있습니다.

### 4-1. 워크플로 수동 비활성화 여부 (가장 유력)

1. **GitHub** → 저장소 **partnerchange_news** → **Actions** 탭
2. 왼쪽 목록에서 **"Send News Mail"** 클릭
3. 오른쪽이나 목록 옆에 **"Disabled"** / **비활성** 표시가 있는지 확인
4. **비활성**이면 **"Enable workflow"** 또는 **"Re-enable"** 로 다시 켜기

스케줄이 한 번이라도 비활성화된 적이 있으면, 푸시만으로는 자동으로 다시 실행되지 않습니다. **직접 켜줘야 합니다.**

### 4-2. 저장소 공개/비공개

- **Settings** → **General** → **Danger Zone** 위쪽에서 **Visibility** 확인
- 무료 계정에서 **비공개** 저장소는 동시 실행·시간 제한 등 제한이 있을 수 있음 (스케줄 자체는 보통 동작)

### 4-3. Actions 사용 설정

- **Settings** → **Actions** → **General**
- **Actions permissions** 에서 **Allow all actions and reusable workflows** 등으로 실행이 허용돼 있는지 확인

---

## 5. 권장 조치 (우선순위)

1. **Actions 탭에서 "Send News Mail" 비활성 여부 확인 후, 비활성이면 재활성화**
2. **한 번 수동 실행:** Actions → Send News Mail → **Run workflow** → Run workflow  
   - 스케줄 인식/실행 여부 확인용
3. (선택) **빈 커밋 푸시**로 워크플로 재등록 유도  
   ```bash
   git commit --allow-empty -m "chore: trigger Actions schedule"
   git push origin main
   ```

---

## 6. 요약

| 구분 | 점검 결과 |
|------|-----------|
| 기본 브랜치 / 워크플로 위치 | ✅ 문제 없음 |
| cron / YAML | ✅ 문제 없음 |
| 최근 저장소 활동 | ✅ 60일 미활동 아님 |
| **워크플로 비활성화 여부** | ⚠️ **GitHub Actions 탭에서 반드시 확인 필요** |
| 저장소 공개/비공개, Actions 권한 | ⚠️ GitHub 설정에서 확인 필요 |

**오늘 10시에 실행이 안 됐다면, 가장 먼저 Actions 탭에서 "Send News Mail"이 비활성 상태인지 보고, 비활성이면 재활성화하는 것을 권장합니다.**

---

## (추가) 스케줄만 안 되고 수동 실행은 될 때 · 11시 넘어도 자동 발송 안 될 때

- **원인**: GitHub가 저장소를 60일 미활동으로 판단하면 **스케줄 트리거만 자동 비활성화**하는 경우가 있음. UI에는 "Disabled"가 안 보일 수 있음.
- **시도할 것**  
  1. **Actions** → **Send News Mail** → 오른쪽 상단/설정에서 **"Enable workflow"** 또는 스케줄 관련 **재활성화**가 있으면 실행.  
  2. **Settings** → **Actions** → **General** → **"Allow scheduled workflows"** 등 스케줄 허용 옵션 확인.  
  3. 워크플로 파일을 **한 줄 수정 후 푸시**해 스케줄을 다시 등록시키기 (예: 주석 한 줄 추가 후 `git push origin main`).
- **그래도 스케줄이 안 돌면**: GitHub 스케줄러에 의존하지 않고, **외부 cron으로 같은 워크플로를 실행**하는 방식으로 보완 (아래 "외부 cron으로 workflow_dispatch 실행" 참고).

---

## 외부 cron으로 workflow_dispatch 실행 (스케줄 대체)

GitHub 스케줄이 계속 안 될 때, **cron-job.org**·**Windows 작업 스케줄러** 등에서 정해진 시간에 아래 API를 호출하면 수동 실행과 동일한 워크플로가 실행됩니다.

1. **GitHub Personal Access Token (PAT)** 발급  
   - GitHub → **Settings** → **Developer settings** → **Personal access tokens**  
   - 권한: `repo`, `workflow`  
   - 토큰 값을 복사해 안전한 곳에 보관.

2. **API 호출 (PowerShell)**  
   - `YOUR_GITHUB_TOKEN` 자리에 PAT 넣기.  
   - `juanita-j/partnerchange_news` 대신 본인 저장소가 다르면 `OWNER/REPO` 수정.

```powershell
$token = "YOUR_GITHUB_TOKEN"
$headers = @{
  "Accept" = "application/vnd.github.v3+json"
  "Authorization" = "token $token"
}
$body = '{"ref":"main"}'
Invoke-RestMethod -Uri "https://api.github.com/repos/juanita-j/partnerchange_news/actions/workflows/send-news-mail.yml/dispatches" -Method POST -Headers $headers -Body $body -ContentType "application/json"
```

3. **cron-job.org 설정 예시**  
   - 매일 9:05, 10:05, …, 19:05 KST에 1시간마다 실행하려면, UTC 기준 0:05, 1:05, …, 10:05에 위 URL로 POST 요청 (Authorization 헤더에 PAT 포함).  
   - 또는 **한국 시간 9시, 10시, …, 19시**에 맞춰 11개 스케줄 등록.

4. **Windows 작업 스케줄러**  
   - 1시간마다 실행할 작업 하나 만들고, **프로그램**을 `powershell.exe`, **인수**에 위 `Invoke-RestMethod` 한 줄 스크립트 또는 `.ps1` 경로 지정.

이렇게 하면 GitHub 내부 스케줄 없이도, 지정한 시간에 메일 발송 워크플로가 실행됩니다.

---

## (기존) 스케줄만 안 되고 수동 실행은 될 때 (정각 부하)

- **원인**: GitHub에서 **매시 정각(분=0)** 에 전 세계 cron이 몰려 부하가 커서, 정각 스케줄이 지연·누락되는 경우가 있음. 공식/커뮤니티에서도 “정각 피해서 몇 분 뒤로 잡으라”고 권장함.
- **조치**: cron을 **정각에서 5~10분 뒤**로 변경함.  
  - 변경 예: `0 1 * * *` → `8 1 * * *` (UTC 01:08 = KST 10:08).  
  - 적용 후 **main에 푸시**하면 다음 스케줄부터 새 시간에 실행됨.
