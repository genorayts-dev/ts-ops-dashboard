-- =============================================================================
-- TS본부 운영 대시보드 — PostgreSQL 스키마
-- 원칙:
--   * 서버 DB가 유일한 원본(single source of truth). 입력은 엑셀 업로드로만.
--   * 업로드 1건 = upload_batch 1행. 같은 (기간, 리포트종류)를 다시 올리면
--     새 batch가 supersede 하고, 최신 batch만 대시보드 기본 조회에 노출.
--   * 모든 사실 테이블은 batch_id 로 롤백/이력 추적 가능.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------------
-- 마스터
-- ---------------------------------------------------------------------------
CREATE TABLE team (
    code        TEXT PRIMARY KEY,              -- 'D' | 'M' | 'K'
    name        TEXT NOT NULL                  -- 'D테크솔루션팀' ...
);
INSERT INTO team(code, name) VALUES
    ('D','D테크솔루션팀'), ('M','M테크솔루션팀'), ('K','K테크솔루션팀');

CREATE TABLE fx_plan (
    year        INT  NOT NULL,
    currency    TEXT NOT NULL,                 -- 'USD','EUR','JPY','CNY','KRW'
    rate_krw    NUMERIC NOT NULL,              -- 1 통화당 원화 (JPY는 1엔 기준)
    PRIMARY KEY (year, currency)
);
INSERT INTO fx_plan(year,currency,rate_krw) VALUES
    (2026,'USD',1380),(2026,'EUR',1640),(2026,'JPY',9.4),(2026,'CNY',195),(2026,'KRW',1),
    (2025,'USD',1300),(2025,'EUR',1400),(2025,'JPY',9),(2025,'CNY',180),(2025,'KRW',1);

-- 국가/도시 → 좌표 & 지역그룹 (지도용, 최초 1회 채우고 유지)
CREATE TABLE geo_place (
    id          BIGSERIAL PRIMARY KEY,
    name_ko     TEXT NOT NULL,                 -- '튀르키예', '터키', '수원' ...
    canonical   TEXT NOT NULL,                 -- 표준명 (동의어 통합): '튀르키예'
    kind        TEXT NOT NULL,                 -- 'country' | 'kr_city'
    iso3        TEXT,                          -- country 일 때 'TUR'
    region_group TEXT,                         -- '아시아','CIS','중동','아프리카','유럽','남미','오세아니아','중국'
    lat         NUMERIC,
    lng         NUMERIC,
    UNIQUE (name_ko, kind)
);
CREATE INDEX ix_geo_canonical ON geo_place(canonical);

-- ---------------------------------------------------------------------------
-- 기간 & 업로드 배치
-- ---------------------------------------------------------------------------
CREATE TABLE report_period (
    id          BIGSERIAL PRIMARY KEY,
    ptype       TEXT NOT NULL,                 -- 'weekly' | 'monthly' | 'as_ledger'
    year        INT  NOT NULL,
    month       INT,                           -- 공통
    week_no     INT,                           -- weekly 만 (그 외 NULL)
    date_start  DATE,
    date_end    DATE,
    label       TEXT NOT NULL,                 -- '2026년 9월 1주', '2026년 08월'
    -- NULLS NOT DISTINCT: monthly/as_ledger 의 NULL week_no 도 중복 없이 upsert (PG15+)
    UNIQUE NULLS NOT DISTINCT (ptype, year, month, week_no)
);

CREATE TABLE upload_batch (
    id            BIGSERIAL PRIMARY KEY,
    period_id     BIGINT NOT NULL REFERENCES report_period(id),
    source_name   TEXT NOT NULL,               -- 원본 파일명
    source_sha256 TEXT NOT NULL,
    source_blob   BYTEA,                       -- 원본 보관(선택, 크면 오브젝트스토리지로)
    format_detected TEXT NOT NULL,             -- 'weekly_new' | 'weekly_old' | 'monthly' | 'as_report'
    -- 같은 기간 안에서 서로 덮어써야 하는 단위. weekly/monthly = format_detected,
    -- AS 대장은 'as:<org>:<product_line>' (팀·장비군별 파일이 독립적으로 갱신되므로).
    scope_key   TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'superseded' | 'failed'
    warnings      JSONB NOT NULL DEFAULT '[]',
    uploaded_by   TEXT NOT NULL,               -- 리버스프록시가 주입한 사번/ID
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_batch_period ON upload_batch(period_id, status);

-- 같은 기간+종류의 이전 active batch를 superseded 로 내리는 트리거
CREATE OR REPLACE FUNCTION supersede_prev_batch() RETURNS TRIGGER AS $$
BEGIN
    UPDATE upload_batch b
       SET status = 'superseded'
     WHERE b.period_id = NEW.period_id
       AND b.id <> NEW.id
       AND b.status = 'active'
       AND b.scope_key = NEW.scope_key;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_supersede
AFTER INSERT ON upload_batch
FOR EACH ROW WHEN (NEW.status = 'active')
EXECUTE FUNCTION supersede_prev_batch();

-- ---------------------------------------------------------------------------
-- 사실(fact) 테이블 — 전부 batch_id 로 스코프
-- ---------------------------------------------------------------------------

-- 주간/월간 공통 팀 실적 요약
CREATE TABLE svc_summary (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id     BIGINT NOT NULL REFERENCES report_period(id),
    team_code     TEXT NOT NULL REFERENCES team(code),
    received      INT,                         -- AS 접수
    completed     INT,                         -- AS 완료
    completion_rate NUMERIC,                   -- 0~1
    inbound       INT,
    revenue_krw           BIGINT,              -- 당기 AS매출 (원화 환산 합계)
    revenue_krw_ytd       BIGINT,              -- 26년 누계
    rev_usd NUMERIC, rev_eur NUMERIC, rev_jpy NUMERIC, rev_cny NUMERIC, rev_krw_cash NUMERIC,
    UNIQUE (batch_id, team_code)
);
CREATE INDEX ix_summary_period ON svc_summary(period_id, team_code);

-- 지역별 실적
CREATE TABLE svc_region (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    team_code   TEXT NOT NULL REFERENCES team(code),
    region      TEXT NOT NULL,                 -- '아시아','CIS','중동','아프리카','중국','오세아니아'...
    total       INT, completed INT, incomplete INT, rate NUMERIC
);
CREATE INDEX ix_region_period ON svc_region(period_id, team_code);

-- 불량/유형 분류 (S/W, H/W, 지원 하위 세부)
CREATE TABLE defect_breakdown (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    team_code   TEXT NOT NULL REFERENCES team(code),
    category    TEXT NOT NULL,                 -- 'SW' | 'HW' | '지원' | 'Inbound'
    subtype     TEXT NOT NULL,                 -- '영상품질','Calibration','Generator','Detector','PCB','기구부'...
    cnt_period  INT,
    cnt_ytd     INT
);
CREATE INDEX ix_defect_period ON defect_breakdown(period_id, team_code);

-- 장비 모델별 방문/출하
CREATE TABLE equipment_stat (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id     BIGINT NOT NULL REFERENCES report_period(id),
    team_code     TEXT NOT NULL REFERENCES team(code),
    product_group TEXT,                        -- 'C-arm' | 'Mammo' | 'Dental' | 'ENT'
    model         TEXT NOT NULL,               -- 'ZEN-2090 Turbo','OSCAR-15 FD','PAPAYA 3D-Pre'...
    visit_cnt     INT,
    shipment_cnt  INT
);
CREATE INDEX ix_equip_period ON equipment_stat(period_id, team_code);

-- 수금 현황 (통화별 라인)
CREATE TABLE collection_line (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    team_code   TEXT NOT NULL REFERENCES team(code),
    country     TEXT,
    dealer      TEXT,
    currency    TEXT,
    amount      NUMERIC,
    amount_krw  NUMERIC,                       -- fx_plan 으로 환산
    equipment   TEXT,
    paid_date   DATE,
    note        TEXT
);
CREATE INDEX ix_coll_period ON collection_line(period_id, team_code);

-- 채권 현황 (aging)
CREATE TABLE receivable (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    team_code   TEXT NOT NULL REFERENCES team(code),
    party_type  TEXT,                          -- '법인' | 'GK'
    entity      TEXT,                          -- 'GAI','GEG','GT','GJ','GS' 또는 대리점명
    country     TEXT,
    currency    TEXT,
    amount      NUMERIC,
    paid_amount NUMERIC,
    balance     NUMERIC,
    balance_krw NUMERIC,
    ship_date   DATE,
    due_date    DATE,
    is_new      BOOLEAN DEFAULT FALSE,         -- 미회수 상태(연체/미회수/장기미수)
    status      TEXT,                          -- 원본 연체여부: 연체|정상|완납|미회수|장기미수|과입금
    aging_days  INT,                           -- (period.date_end - due_date)
    note        TEXT
);
CREATE INDEX ix_recv_period ON receivable(period_id, team_code);
CREATE INDEX ix_recv_due ON receivable(due_date);

-- 서비스 케이스 (월간 Raw Data / 향후 AS리포트)
CREATE TABLE svc_case (
    id             BIGSERIAL PRIMARY KEY,
    batch_id       BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id      BIGINT NOT NULL REFERENCES report_period(id),
    team_code      TEXT REFERENCES team(code),
    seq_no         INT,
    region         TEXT,
    country        TEXT,
    install_date   DATE,
    product_model  TEXT,
    product_code   TEXT,
    received_date  DATE,
    action_date    DATE,
    title          TEXT,
    action         TEXT,
    defect_cause   TEXT,                       -- 'Software','Generator','PCB','기구부','사용자 교육'...
    result         TEXT,                       -- '완료' | '대응 중'
    geo_place_id   BIGINT REFERENCES geo_place(id)
);
CREATE INDEX ix_case_period ON svc_case(period_id);
CREATE INDEX ix_case_country ON svc_case(country);
CREATE INDEX ix_case_result ON svc_case(result);

-- 월별 추이 (월간 표지의 1월~당월 매트릭스)
CREATE TABLE monthly_trend (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT REFERENCES report_period(id),
    year        INT NOT NULL,
    month       INT NOT NULL,
    team_code   TEXT NOT NULL REFERENCES team(code),
    service_cnt INT,
    inbound_cnt INT,
    revenue_krw BIGINT,
    revenue_krw_ytd BIGINT,
    UNIQUE (batch_id, year, month, team_code)
);

-- 유지보수(월납) 계약 — 월간보고엔 매출로 잡히나 통합시트 건별탭엔 없음.
-- 통합 구글시트 'AS 유지보수 K' 탭 → gsheet_master 파서가 이 테이블로 적재.
-- K테크 AS매출에 (계약월~만료월 유효한) 활성 계약의 월납액을 월별로 가산한다.
-- batch_id 로 v_latest_batch 에 묶여 재동기화 시 이전 batch 가 자동 대체됨(중복 없음).
CREATE TABLE IF NOT EXISTS maintenance_contract (
    id           BIGSERIAL PRIMARY KEY,
    batch_id     BIGINT REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id    BIGINT REFERENCES report_period(id),
    team_code    TEXT NOT NULL DEFAULT 'K',
    hospital     TEXT NOT NULL,
    device       TEXT,
    serial_no    TEXT,
    delivered_on DATE,
    contract_on  DATE,                 -- 유지보수 계약일 (이 달부터 매출 계상)
    expires_on   DATE,                 -- 계약 만료일 (NULL = 무기한)
    pay_day      TEXT,                 -- '매월 말일' 등 (표시용)
    currency     TEXT NOT NULL DEFAULT 'KRW',  -- 통화 미기재 = KRW
    monthly_fee  BIGINT NOT NULL,      -- 월납액(원본통화)
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS ix_maint_batch ON maintenance_contract(batch_id);

-- KPI 추진 실적 (월간)
CREATE TABLE kpi_item (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    category    TEXT,                          -- '서비스 고도화' | '서비스 상품화' | '조직역량강화'
    team_code   TEXT REFERENCES team(code),    -- NULL = 공통/TS본부
    goal_text   TEXT,
    result_text TEXT,
    achieved    NUMERIC,                       -- 0~1 (실적) / NULL (계획)
    is_plan     BOOLEAN NOT NULL DEFAULT FALSE,-- true = 'N월 목표' 시트(아직 미착수)
    plan_month  INT                            -- is_plan 일 때 대상 월
);
CREATE INDEX ix_kpi_period ON kpi_item(period_id);

-- 사업계획 실행과제 (구글시트 '업무 세부 실행계획' 1건/행)
CREATE TABLE plan_item (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    category    TEXT,                 -- '서비스 고도화' | '서비스 상품화' | '조직 역량 강화'
    plan_name   TEXT,                 -- 실행계획(구분)
    team_code   TEXT,                 -- D|M|K / NULL = TS본부·공통·다팀
    team_label  TEXT,                 -- 담당 원문
    goal_text   TEXT,
    goal_n      INT,                  -- 연간 목표 건수('총 N건'/'N회' 파싱)
    detail      TEXT,
    expect      TEXT,                 -- 기대 효과
    months      TEXT,                 -- {"1":"…계획활동…", ...} JSON
    progress    TEXT,                 -- {"1":0.8, ...} JSON (있으면)
    seq         INT
);
CREATE INDEX ix_plan_period ON plan_item(period_id);

-- 서비스 이슈 (주간/월간)
CREATE TABLE svc_issue (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    team_code   TEXT REFERENCES team(code),
    kind        TEXT,                          -- '주요' | '다발성' | '내방' | '개선'...
    title       TEXT NOT NULL,
    occurrence  TEXT,                          -- [발생현황]
    cause       TEXT,                          -- [원인분석]
    action      TEXT,                          -- [조치내용]/[조치계획]
    ref_url     TEXT
);
CREATE INDEX ix_issue_period ON svc_issue(period_id);

-- 인사/출장/교육
CREATE TABLE hr_event (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id   BIGINT NOT NULL REFERENCES report_period(id),
    team_code   TEXT REFERENCES team(code),
    event_type  TEXT,                          -- '연차','출장','파견','교육','당직','퇴사','입사'
    person      TEXT,
    detail      TEXT,
    date_from   DATE,
    date_to     DATE
);

-- ---------------------------------------------------------------------------
-- AS 접수처리대장 (D/M/K/부산 4개 팀, 장비군·월별 파일. 케이스 1건/행)
-- weekly/monthly 와 독립된 ptype='as_ledger' 기간(월 단위)에 매단다.
-- ---------------------------------------------------------------------------
CREATE TABLE as_ticket (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id     BIGINT NOT NULL REFERENCES report_period(id),
    org           TEXT NOT NULL,               -- 'D' | 'M' | 'K' | '부산'
    src           TEXT,                        -- 유래 탭: 'k_dom'|'overseas_ship'|'md_service' (구글시트) / NULL
    product_line  TEXT,                        -- 파일명 유래: 'C-ARM' | 'DENTAL' | 'DENTAL STANDARD' | 'MAMMO' | '대장비' | '소장비'
    seq_no        INT,                         -- 파일 내 NO
    ticket_no     TEXT,                        -- 접수번호 (D701-2601-1 등)
    shipped_to    TEXT,                        -- 출하처 (해외=국가, 국내=병원명)
    is_overseas   BOOLEAN,                     -- org in (D,M) → true
    region_kr     TEXT,                        -- 국내건일 때 시·도 (K 분석시트/후처리로 채움)
    region        TEXT,                        -- 원본 '지역' 컬럼 (아시아/중동/... 또는 시·군)
    country       TEXT,                        -- 해외건일 때 국가 (=shipped_to 정규화)
    install_date  DATE,                        -- 출하#(출하일)
    product_model TEXT,                        -- 제품명
    serial_no     TEXT,                        -- 제조번호
    udi           TEXT,
    warranty      TEXT,                        -- '무상' | '유상'
    category      TEXT,                        -- 구분 (서비스 등)
    received_date DATE,
    action_date   DATE,
    engineer      TEXT,                        -- 조치자
    symptom       TEXT,                        -- 접수내용
    action        TEXT,                        -- 조치사항
    check_result  TEXT,                        -- 조치후점검 (적합)
    result        TEXT,                        -- 결과 (완료 / 대기)
    repair_currency TEXT,                      -- 수리비용 통화
    repair_amount NUMERIC,
    repair_amount_krw NUMERIC,
    billing       TEXT,                        -- 청구내역
    cause         TEXT,                        -- 원인분석 (자유서술)
    fix_class     TEXT,                        -- 시정조치 구분: 부품 | 기타 | 공정 | 설계
    adverse_event TEXT,                        -- 이상사례: 무 | 유
    followup      TEXT,                        -- 후속조치
    -- K테크 분석시트 유래 코딩 (있을 때만)
    cause_major   TEXT,                        -- EP/SW/OP/MP/MA/EA
    cause_minor   TEXT,                        -- CO/IM/MT/UD/HR/BD/DT/MN/AC/RO/MO/ET
    action_class  TEXT,                        -- TU/PC/BU/UP/TR/ETC
    age_bucket    TEXT                         -- 3개월미만 | 3개월-1년 | 1년-2년 | 2년-5년 | 5년-10년 | 10년이상
);
CREATE INDEX ix_as_period ON as_ticket(period_id, org);
CREATE INDEX ix_as_country ON as_ticket(country);
CREATE INDEX ix_as_model ON as_ticket(product_model);
CREATE INDEX ix_as_result ON as_ticket(result);
CREATE INDEX ix_as_serial ON as_ticket(serial_no);

-- ---------------------------------------------------------------------------
-- 구글 시트 연동 — 동기화 대상 스프레드시트 목록
-- ---------------------------------------------------------------------------
CREATE TABLE gsheet_source (
    id           BIGSERIAL PRIMARY KEY,
    sheet_id     TEXT NOT NULL UNIQUE,          -- 스프레드시트 ID
    title        TEXT,                          -- 표시용(마지막 동기화 시 파일명)
    note         TEXT,
    added_by     TEXT,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_sync_at TIMESTAMPTZ,
    last_status  TEXT,                          -- 'ok' | 'error: ...'
    last_batch_id BIGINT REFERENCES upload_batch(id)
);

-- ---------------------------------------------------------------------------
-- geno-one(사내 ERP, one.genoray.com) AS관리(/aspart) 원본 스냅샷.
-- 해외(M/D)만 존재·K국내 0건이라 as_ticket(통합시트 md_service)과 스코프가 달라
-- 별도 테이블로 격리 적재 후 나중에 교차검증한다. scope_key='geno_one_aspart' →
-- 재동기화 시 이전 batch 자동 대체(v_latest_batch).
-- ---------------------------------------------------------------------------
CREATE TABLE geno_one_ticket (
    id                    BIGSERIAL PRIMARY KEY,
    batch_id              BIGINT NOT NULL REFERENCES upload_batch(id) ON DELETE CASCADE,
    period_id             BIGINT NOT NULL REFERENCES report_period(id),
    seq_no                TEXT,      -- 원본 'No'
    charge_type           TEXT,      -- 담당구분 (본사 등)
    dealer                TEXT,      -- 딜러사
    customer              TEXT,      -- 고객사
    issue                 TEXT,
    product_name          TEXT,      -- 제품명
    warranty_expire       DATE,      -- 보증기간 만료일
    engineer              TEXT,      -- 조치/출장자
    serial_no             TEXT,      -- 시리얼 넘버
    received_date         DATE,      -- 접수일
    action_date           DATE,      -- 조치일
    service_status        TEXT,      -- Service Status (New/Inprogress/Holding/Close)
    contact_point         TEXT,      -- Contact Point
    dealer_country        TEXT,      -- 국가(딜러사)
    period_bucket         TEXT,      -- 기간별
    post_check            TEXT,      -- 조치 후 점검
    result                TEXT,      -- 결과
    symptom               TEXT,      -- 불량증상
    detail                TEXT,      -- 상세설명
    ticket_type           TEXT,      -- 유형
    customer_country      TEXT,      -- 국가(고객사)
    parts_changed         TEXT,      -- 부품변경내역
    action_taken          TEXT,      -- 조치사항
    repair_cost           NUMERIC,   -- 수리비 (720건 중 대부분 공란, 원본 "5,115 USD" 형태)
    repair_currency       TEXT,      -- 수리비 통화 (원본 문자열에서 분리, 예: USD)
    category              TEXT,      -- 구분(서비스, 고객불만)
    followup              TEXT,      -- 후속조치
    line_major            TEXT,      -- 분석표 대분류
    line_mid              TEXT,      -- 분석표 중분류
    line_minor            TEXT,      -- 분석표 소분류
    fix_class             TEXT,      -- 조치분류
    root_cause            TEXT,      -- 원인분석
    udi                   TEXT,
    warranty_period       TEXT,      -- 보증기간
    warranty_paid         TEXT,      -- 유상/무상
    adverse_event         TEXT,      -- 이상사례
    case_class            TEXT,      -- 원본 '구분' (의미 미확인, 원본 그대로 보관)
    ship_date             DATE,      -- 출하일
    region_analysis       TEXT,      -- 지역(분석표)
    defect_class_analysis TEXT,      -- 불량구분(분석표)
    billing_note          TEXT       -- 청구내역
);
CREATE INDEX ix_geno_one_period ON geno_one_ticket(period_id);
CREATE INDEX ix_geno_one_serial ON geno_one_ticket(serial_no);
CREATE INDEX ix_geno_one_status ON geno_one_ticket(service_status);

-- ---------------------------------------------------------------------------
-- (선택) 대시보드 위에서 다는 코멘트 레이어 — 엑셀과 무관한 협업 메모
-- 입력은 업로드로만 하지만, 항목별 토론/주석은 필요할 수 있어 남겨둠.
-- ---------------------------------------------------------------------------
CREATE TABLE annotation (
    id          BIGSERIAL PRIMARY KEY,
    scope       TEXT NOT NULL,                 -- 'period' | 'issue' | 'kpi' | 'receivable' | 'case'
    ref_id      BIGINT NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved    BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ix_annotation_ref ON annotation(scope, ref_id);

-- ---------------------------------------------------------------------------
-- 대시보드 기본 조회용 뷰 (항상 최신 active batch)
-- ---------------------------------------------------------------------------
CREATE VIEW v_latest_batch AS
SELECT DISTINCT ON (period_id, scope_key)
       id AS batch_id, period_id, scope_key, format_detected, uploaded_at
  FROM upload_batch
 WHERE status = 'active'
 ORDER BY period_id, scope_key, uploaded_at DESC;

CREATE VIEW v_summary_latest AS
SELECT s.*, p.label, p.ptype, p.year, p.month, p.week_no
  FROM svc_summary s
  JOIN v_latest_batch lb ON lb.batch_id = s.batch_id
  JOIN report_period p ON p.id = s.period_id;
