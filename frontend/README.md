# 프런트엔드 (React + Vite + ECharts)

당신이 구현. 아래는 화면/컴포넌트 분해와 지도 코드 스니펫.

## 스택
- Vite + React 18 + TypeScript
- 상태/패칭: TanStack Query (`@tanstack/react-query`) — API 폴링·캐시
- 차트·세계지도: `echarts` + `echarts-for-react`
- 국내 상세지도: `react-leaflet` + `leaflet` (타일 URL 은 `/api/map/config` 에서)
- 표: `@tanstack/react-table` 또는 AG Grid Community

```
npm create vite@latest frontend -- --template react-ts
npm i @tanstack/react-query echarts echarts-for-react react-leaflet leaflet
```

## 화면 구성

```
App
├─ TopBar        기간 선택(주간/월간 드롭다운, /api/dashboard/periods), 업로드 버튼
├─ UploadDialog  드래그&드롭 → POST /api/ingest → 결과 토스트(삽입 건수 + warnings)
├─ Tabs
│  ├─ 개요(Overview)
│  │   ├─ KpiCards        팀별 접수/완료/Inbound/매출 + 합계   (GET /overview)
│  │   ├─ TrendChart      월별 매출·서비스 추이 라인           (GET /trend)
│  │   ├─ DefectBar       S/W·H/W·지원 세부 분류 누적막대      (GET /defects)
│  │   └─ EquipmentTable  장비 모델별 방문/출하               (GET /equipment)
│  ├─ 지도(Map)
│  │   ├─ 세계 탭  WorldChoropleth   (GET /map/countries?metric=…)   ← 키 불필요
│  │   └─ 국내 탭  KoreaSiteMap      (GET /map/kr-sites, /map/config) ← config.kr_enabled 일 때만
│  ├─ 채권(Receivables)  AgingBars + 라인 테이블               (GET /receivables)
│  ├─ 이슈(Issues)       주요/다발성 카드 + 코멘트             (GET /issues, /annotations)
│  ├─ KPI               카테고리별 목표/실적/달성률            (GET /kpi)
│  └─ 케이스(Cases)      국가·결과·검색 필터 테이블            (GET /cases)
└─ AnnotationPanel  우측 슬라이드, scope+ref_id 별 코멘트 스레드
```

폴링: `useQuery({ queryKey, queryFn, refetchInterval: 60_000 })` — 다른 PC의 업로드가 1분 내 반영.
즉시 반영이 필요하면 `/api/batches` 최신 `uploaded_at` 을 30초 폴링해서 변하면 invalidate.

## 세계 지도 (ECharts, 키 불필요)

`public/world.json` 에 world TopoJSON 배치 (Natural Earth 1:110m, 한 번만 커밋).
ISO A3 속성이 있는 것으로 — 예: `world-atlas` 의 countries-110m 를 GeoJSON+iso_a3 로 변환.

```tsx
import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const METRIC_LABEL: Record<string, string> = {
  cases: "AS 케이스 수", open_issues: "대응 중", revenue: "수금액(₩)", receivable: "미회수채권(₩)",
};

export function WorldChoropleth({ periodId }: { periodId?: number }) {
  const [ready, setReady] = useState(false);
  const [metric, setMetric] = useState("cases");

  useEffect(() => {
    fetch("/world.json").then(r => r.json()).then(geo => {
      echarts.registerMap("world", geo);
      setReady(true);
    });
  }, []);

  const { data } = useQuery({
    queryKey: ["map-countries", metric, periodId],
    queryFn: () => fetch(`/api/map/countries?metric=${metric}` +
      (periodId ? `&period_id=${periodId}` : "")).then(r => r.json()),
  });

  if (!ready || !data) return <div>지도 로딩…</div>;

  const rows = data.rows.filter((r: any) => r.iso3);
  const values = rows.map((r: any) => Number(r.value) || 0);
  const max = Math.max(1, ...values);

  const option = {
    tooltip: {
      trigger: "item",
      formatter: (p: any) =>
        `${p.name}<br/>${METRIC_LABEL[metric]}: ${p.value?.toLocaleString?.() ?? "-"}`,
    },
    visualMap: {
      min: 0, max, right: 10, bottom: 10, calculable: true,
      inRange: { color: ["#eef2ff", "#6366f1", "#312e81"] },
    },
    series: [{
      type: "map", map: "world", roam: true, nameProperty: "iso_a3",
      emphasis: { label: { show: false } },
      data: rows.map((r: any) => ({ name: r.iso3, value: Number(r.value) || 0, meta: r })),
    }],
  };

  return (
    <div>
      <select value={metric} onChange={e => setMetric(e.target.value)}>
        {Object.entries(METRIC_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <ReactECharts option={option} style={{ height: 520 }} notMerge />
      {data.unmatched_countries?.length > 0 && (
        <p style={{ color: "#b45309", fontSize: 12 }}>
          좌표 미매칭: {data.unmatched_countries.join(", ")} → data/geo_place_seed.csv 에 추가
        </p>
      )}
    </div>
  );
}
```

> 국가명 대신 버블(값=원 크기)로 보고 싶으면 `series[0]` 를 `type:"scatter", coordinateSystem:"geo"` +
> `geo:{ map:"world" }` 로 바꾸고 `data` 를 `[lng, lat, value]` 로. (`/api/map/countries` 가 lat/lng 도 반환)

## 국내 상세 지도 (Leaflet, 타일 키 필요)

```tsx
import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import { useQuery } from "@tanstack/react-query";
import "leaflet/dist/leaflet.css";

export function KoreaSiteMap({ periodId }: { periodId?: number }) {
  const { data: cfg } = useQuery({ queryKey: ["map-config"],
    queryFn: () => fetch("/api/map/config").then(r => r.json()) });
  const { data } = useQuery({ queryKey: ["kr-sites", periodId],
    queryFn: () => fetch(`/api/map/kr-sites` + (periodId ? `?period_id=${periodId}` : ""))
      .then(r => r.json()) });

  if (!cfg?.kr_enabled) return <p>국내 상세 지도 타일이 아직 설정되지 않았습니다 (README §5 옵션 ②).</p>;
  if (!data) return <div>로딩…</div>;

  return (
    <MapContainer center={[36.5, 127.9]} zoom={7} style={{ height: 520 }}>
      <TileLayer url={cfg.kr_tile_url} attribution={cfg.kr_attribution} />
      {data.sites.map((s: any, i: number) => (
        <CircleMarker key={i} center={[s.lat, s.lng]} radius={6 + Math.sqrt(s.visits) * 2}>
          <Tooltip>{s.city} · 방문 {s.visits}건<br/>{(s.models || []).join(", ")}</Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
```

## nginx (배포)
`frontend/dist` 를 `web` 컨테이너가 서빙, `/api` 는 backend 로 프록시 → 같은 오리진이라 CORS 불필요.
개발 중에는 Vite `server.proxy` 로 `/api → http://localhost:8000`.
