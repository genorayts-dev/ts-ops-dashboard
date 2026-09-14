# TS본부 운영 대시보드

주간·월간 실적 엑셀을 **업로드하면**, 사내망의 누구나 같은 최신 데이터를 보는 웹 대시보드.
정적 HTML이 아니라 **서버 + DB + 웹앱** 구조 — 한 사람이 파일을 올리면 모든 PC가 즉시 갱신된 값을 봅니다.

```
 담당자 ── .xlsx 업로드 ─▶  FastAPI  ──▶  PostgreSQL (유일 원본)
                              │  파싱·정규화·이전 버전 supersede
 사내 누구나 ── 브라우저 ─▶  React SPA  ◀── REST ── FastAPI
                              │
                       사내 SSO 프록시(nginx) 가 X-Remote-User 주입
```

- 입력은 **파일 업로드 전용** (기존 양식 엑셀을 계속 그대로 작성 → 드래그&드롭).
- 같은 기간을 다시 올리면 새 버전이 활성화되고 이전 버전은 이력으로 보관(1‑클릭 롤백).
- 편집형 협업 대신 **"업로드 = 갱신" + 항목별 코멘트(annotation)** 레이어.

---

## 1. 빠른 시작 (개발)

```bash
# DB + API
docker compose up -d db backend

# 지도용 국가 좌표 시드
pip install sqlalchemy psycopg[binary]
python scripts/load_geo_seed.py

# 엑셀 한 건 넣어보기
curl -F "file=@/path/TS본부_주간업무(2026년 9월 1주).xlsx" http://localhost:8000/api/ingest

# 확인
curl "http://localhost:8000/api/dashboard/overview?ptype=weekly"
open http://localhost:8000/docs
```

프런트는 `frontend/`(별도 README) — Vite dev 서버 `npm run dev` → `http://localhost:5173`.

## 2. 구성요소

| 레이어 | 선택 | 비고 |
|---|---|---|
| DB | PostgreSQL 16 | `db/schema.sql` 가 전체 스키마. 컨테이너 최초 기동 시 자동 실행 |
| API | FastAPI (Python 3.12) | `backend/app/` — 당신이 확장. 엔드포인트 목록은 §4 |
| 파서 | openpyxl + 규칙 파일 | `backend/app/ingest/` + `mapping.yaml` (양식 바뀌면 **코드 아닌 yaml** 수정) |
| 프런트 | React + Vite + **ECharts** | 차트·세계지도 한 라이브러리. 국내 상세지도만 Leaflet |
| 배포 | docker compose | `web`(nginx) 가 정적 SPA 서빙 + `/api` 프록시 + SSO 헤더 |

## 3. 인증 (사내망)

별도 로그인 화면 없음. 앞단 **사내 SSO / AD 프록시**가 인증 후 사용자 사번을
`X-Remote-User` 헤더로 주입 → API가 업로드·코멘트에 `uploaded_by`/`author`로 기록.
`deploy/nginx.conf`에 연동 지점 주석. (외부에서 들어온 동일 헤더는 프록시가 반드시 제거)

## 4. API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/ingest` | xlsx 업로드 → 양식 자동판별(weekly_new/weekly_old/monthly) → 적재. 응답에 삽입 건수 + warnings |
| GET | `/api/batches` | 업로드 이력 |
| POST | `/api/batches/{id}/rollback` | 해당 버전 폐기, 직전 버전 재활성화 |
| GET | `/api/dashboard/periods?ptype=weekly\|monthly` | 기간 목록(최신 버전 존재하는 것만) |
| GET | `/api/dashboard/overview?period_id=&ptype=` | 팀별 접수·완료·Inbound·매출 카드 + 합계 |
| GET | `/api/dashboard/trend?metric=revenue_krw\|service_cnt\|inbound_cnt&year=` | 월별 추이(월간 표지 기반) |
| GET | `/api/dashboard/defects?period_id=&team=` | S/W·H/W·지원 세부 불량 분류 |
| GET | `/api/dashboard/equipment?period_id=` | 장비 모델별 방문/출하 |
| GET | `/api/dashboard/receivables?period_id=` | 채권 라인 + aging 버킷(원화) |
| GET | `/api/dashboard/kpi?period_id=` | 월간 KPI 추진 실적 |
| GET | `/api/dashboard/issues?period_id=&ptype=` | 서비스 이슈(주요/다발성) |
| GET | `/api/dashboard/cases?period_id=&country=&result=&q=` | 서비스 케이스(Raw Data) 검색 |
| GET | `/api/map/config` | 국내 상세지도 타일 설정(키 없으면 프런트가 국내 탭 숨김) |
| GET | `/api/map/countries?metric=cases\|open_issues\|revenue\|receivable` | **세계 국가 단위 집계** (외부 지도 API 불필요) |
| GET | `/api/map/kr-sites?period_id=` | 국내 방문 AS 위치(핀) |
| GET/POST | `/api/annotations` | 항목별 코멘트 |

## 5. 지도 — 필요한 것

### 탭 ① 세계 국가 지도 → **API 키 불필요**
데이터가 국가 단위(수금·채권·Raw Data의 `국가`)라서, 프런트에 **world GeoJSON(TopoJSON)을 번들**해
ECharts choropleth/버블맵으로 그립니다. 사내망에서 외부 호출 0건 — 키 만료·과금·차단 없음.
`/api/map/countries` 응답의 `iso3`로 GeoJSON과 조인. (`frontend/README.md`에 코드)

### 탭 ② 국내 시·군 상세 지도 → **새 지도 계정/토큰 발급 필요**
K테크 방문 AS를 실제 병원 소재지(수원·전주·경산…) 핀으로 찍으려면 지도 타일 제공자가 필요합니다.
**기존에 쓰던 개인 계정/키는 쓰지 않습니다.** 아래 중 하나로 새로 발급해서 전달해 주세요:

> **옵션 A — MapTiler Cloud (권장, 무료 100k 로드/월)**
> 1. 회사 이메일로 새 계정 생성
> 2. Maps → API Keys → **새 키 1개 발급**
> 3. 그 키에 **Allowed origins** 를 사내 대시보드 호스트로 제한 (예: `http://dashboard.내부도메인`, `http://localhost:8080`)
> 4. 타일 URL 전달: `https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}.png?key=<새키>`
>
> **옵션 B — Mapbox** : 새 계정 → **public access token** 1개 발급 → URL restriction 을 사내 도메인으로 → 스타일 URL 전달
>
> **옵션 C — 완전 폐쇄망** : 외부 접속이 막혀 있으면 **OpenMapTiles + 한국 추출본**을 사내 타일 서버(tileserver-gl)로 self-host. 이 경우 키 자체가 불필요, 타일 URL만 사내 주소로.

받은 값은 `docker-compose.yml` 의 `TSD_KR_MAP_TILE_URL` / `TSD_KR_MAP_ATTRIBUTION` 에 넣으면
`/api/map/config` 를 통해 프런트가 자동으로 국내 탭을 켭니다. **값이 비어 있으면 국내 탭은 숨겨지고
세계 지도만 동작**하므로, 옵션 ②는 나중에 붙여도 됩니다.

지오코딩(국가·도시명→좌표)은 `geo_place` 테이블에 미리 채워두므로 실시간 지오코딩 API도 불필요합니다.
국내 시·군 좌표는 `data/geo_place_seed.csv` 에 `kind=kr_city` 행으로 추가(현재 국가만 포함).

## 6. 곧 올 "AS 리포트" 대비

파서가 `mapping.yaml` 규칙 기반이라, AS 리포트 양식이 오면:
1. `mapping.yaml` 에 `formats.as_report:` 블록 추가(시트/헤더 매핑)
2. `ingest/as_report.py` 파서 1개 추가, `ingest/__init__.py:parse()` 에 분기 1줄
3. 대부분 `svc_case` / `receivable` / `equipment_stat` 에 그대로 적재 → 스키마 변경 최소

리포트 받으면 위 3개를 채워서 전달하겠습니다.

## 7. 알려진 TODO (실파일 대조 후 확정)

- `weekly_new` 파서: D/M테크 채권표는 병합셀이 많아 열 위치 스캔 방식 — 실제 3~4개 파일로 검증 필요
- `weekly_old` 파서: 팀시트 상단 '주요내용' 서술 블록 때문에 표 오프셋이 신양식과 다름. 요약표·지역표는 동작, 장비표는 K만
- `monthly` 파서: 표지 월별 추이 매트릭스가 매우 넓은 병합 구조 — 현재 '1월'~'N월' 라벨 스캔 방식, 3벌(서비스/Inbound/매출) 순서 가정
- KPI(`kpi_item`) 상세 시트 파싱은 미구현 — 표지 요약만
- `completion_rate` 등 일부 파생값은 프런트 계산 또는 후처리 잡으로
