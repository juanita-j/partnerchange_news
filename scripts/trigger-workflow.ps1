# GitHub Actions "Send News Mail" 워크플로를 workflow_dispatch로 실행
# 사용: $env:GITHUB_TOKEN="ghp_xxx"; .\trigger-workflow.ps1
# 또는 cron-job.org / 작업 스케줄러에서 이 스크립트를 주기적으로 실행

$repo = "juanita-j/partnerchange_news"
$workflow = "send-news-mail.yml"
$token = $env:GITHUB_TOKEN
if (-not $token) {
  Write-Error "GITHUB_TOKEN 환경 변수를 설정하세요. (GitHub Settings -> Developer settings -> Personal access tokens, repo + workflow 권한)"
  exit 1
}
$uri = "https://api.github.com/repos/$repo/actions/workflows/$workflow/dispatches"
$headers = @{
  "Accept"        = "application/vnd.github.v3+json"
  "Authorization" = "token $token"
}
$body = '{"ref":"main"}'
try {
  Invoke-RestMethod -Uri $uri -Method POST -Headers $headers -Body $body -ContentType "application/json"
  Write-Host "Send News Mail workflow triggered successfully."
} catch {
  Write-Error $_.Exception.Message
  exit 1
}
