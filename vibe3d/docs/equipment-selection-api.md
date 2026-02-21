# Equipment Selection API — Vibe3D ↔ HeatOps Nav X 연동

> **Version**: v2.3
> **Date**: 2026-02-21
> **Status**: Production Ready

---

## 1. 개요

Vibe3D 3D 뷰어(Three.js)에서 설비를 클릭하면, 해당 설비 정보를 부모 윈도우(HeatOps Nav X)로 전달하여 **설비 네비게이터** 페이지로 자동 이동시키는 기능.

### 아키텍처

```
HeatOps Nav X (parent window)
  └─ iframe: https://<tunnel>.trycloudflare.com (Vibe3D)
       └─ Three.js 3D viewer (scene-viewer.js)
            └─ 오브젝트 클릭
                 → onSelect(name)
                 → notifyEquipmentSelected(name)
                 → window.parent.postMessage(event, '*')
                 → HeatOps: message listener → Navigator 이동
```

### 데이터 흐름

```
Unity Scene (MCP)
  → main.py: _node_to_3d_obj()     — tag/type 추출하여 3D data에 포함
  → GET /api/scene/3d-data          — {name, path, tag, type, position, ...}
  → scene-viewer.js: _addObject()   — mesh.userData.tag/type 저장
  → app.js: refresh3DView()         — _sceneObjects 캐시에 tag/type 포함
  → 사용자 클릭
  → onSelect(name)
  → notifyEquipmentSelected(name)
    ├─ obj.tag 우선 사용 (backend 추출), 없으면 extractTag(name) 폴백
    ├─ obj.type 우선 사용 (backend 추출), 없으면 inferAssetType(name) 폴백
    ├─ window.parent.postMessage(event, '*')   ← iframe → HeatOps
    └─ POST /api/equipment/event               ← REST polling 지원
```

---

## 2. 메시지 포맷

```json
{
    "type": "EQUIPMENT_SELECTED",
    "assetId": "Factory/Vessels/Fermentor_Main",
    "assetTag": "TCV-7742",
    "assetName": "Fermentor_Main",
    "assetType": "CONTROL_VALVE",
    "metadata": {
        "position": { "x": 0, "y": 5.2, "z": 10.3 },
        "scale": { "x": 2.0, "y": 8.0, "z": 2.0 },
        "path": "Factory/Vessels/Fermentor_Main",
        "primitive": "Cylinder",
        "color": { "r": 0.75, "g": 0.77, "b": 0.80 }
    },
    "timestamp": 1740000000000
}
```

### 매칭 우선순위

| Vibe3D 전송 | HeatOps Asset | 우선순위 | 소스 |
|-------------|---------------|----------|------|
| `assetTag` | `tag` | 1순위 | `_extract_asset_tag(name)` → P&ID 태그 |
| `assetName` | `name` | 2순위 | Unity 오브젝트 이름 그대로 |
| `assetId` | `id` | 3순위 | Unity 오브젝트 경로 |

### assetType 분류 규칙

| 패턴 | assetType |
|------|-----------|
| ferment, reactor, tank, vessel, digest | `VESSEL` |
| valve (+ control) | `VALVE` / `CONTROL_VALVE` |
| pump | `PUMP` |
| pipe, duct | `PIPE` |
| heat exchanger, cooler, heater | `HEAT_EXCHANGER` |
| motor, engine, turbine, generator | `MACHINE` |
| sensor, gauge, meter | `INSTRUMENT` |
| 기타 | `EQUIPMENT` |

### assetTag 추출 패턴

정규식: `[A-Z]{1,4}-\d{2,5}[A-Z]?`

| 이름 예시 | 추출 결과 |
|-----------|-----------|
| `Valve_TCV-7742` | `TCV-7742` |
| `Fermentor_V-101` | `V-101` |
| `Pump_P-201A` | `P-201A` |
| `HeatExchanger_HX-3001` | `HX-3001` |
| `Floor` (태그 없음) | `Floor` (이름 그대로) |

---

## 3. API 엔드포인트

### POST /api/equipment/event

설비 선택 이벤트 수신 (프론트엔드에서 호출).

```bash
curl -X POST http://127.0.0.1:8091/api/equipment/event \
  -H "Content-Type: application/json" \
  -d '{"type":"EQUIPMENT_SELECTED","assetTag":"TCV-7742","assetName":"Control_Valve_01"}'
```

**Response**: `{"status": "ok"}`

**Side effects**:
- `_last_equipment_event`에 저장
- WebSocket `equipment_selected` 이벤트 브로드캐스트
- 서버 로그 출력

### GET /api/equipment/selected

마지막 선택된 설비 정보 조회 (REST polling용).

```bash
curl http://127.0.0.1:8091/api/equipment/selected
```

**Response**: 마지막 이벤트 데이터 또는 `{"type": "NONE"}`

---

## 4. 연동 방법 (HeatOps Nav X)

### 방법 1: postMessage 수신 (권장)

```javascript
window.addEventListener('message', async (e) => {
    if (!e.origin.includes('trycloudflare.com') &&
        !e.origin.includes('localhost')) return;

    if (e.data?.type === 'EQUIPMENT_SELECTED') {
        const { assetTag, assetName, assetId } = e.data;

        const assets = await base44.entities.Asset.list();
        const matched = assets.find(a =>
            (assetTag && a.tag === assetTag) ||
            (assetName && a.name === assetName) ||
            (assetId && a.id === assetId)
        );

        if (matched) {
            window.location.href = createPageUrl(`Navigator?assetId=${matched.id}`);
        }
    }
});
```

### 방법 2: REST API polling

```javascript
const VIBE3D_API = 'https://<tunnel>.trycloudflare.com';
let lastAssetId = null;

setInterval(async () => {
    try {
        const resp = await fetch(`${VIBE3D_API}/api/equipment/selected`);
        const data = await resp.json();
        if (data.type === 'EQUIPMENT_SELECTED' && data.assetId !== lastAssetId) {
            lastAssetId = data.assetId;
            navigateToEquipmentPage(data.assetTag);
        }
    } catch (e) { /* ignore */ }
}, 1000);
```

### 방법 3: WebSocket 실시간 구독

```javascript
const ws = new WebSocket('wss://<tunnel>.trycloudflare.com/ws');
ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.event === 'equipment_selected') {
        navigateToEquipmentPage(msg.data.assetTag);
    }
};
```

---

## 5. 변경된 파일

| 파일 | 변경 내용 | 변경량 |
|------|-----------|--------|
| `vibe3d/backend/main.py` | `EquipmentEventRequest` 모델, `_extract_asset_tag()`, `_infer_asset_type()`, 2 엔드포인트, 3D data에 tag/type 필드 추가 | +60줄 |
| `vibe3d/frontend/static/app.js` | `notifyEquipmentSelected()`, `inferAssetType()`, `extractTag()`, `_sceneObjects` 캐시, onSelect 수정 | +55줄 |
| `vibe3d/frontend/static/scene-viewer.js` | `mesh.userData.tag/type` 저장 | +2줄 |
| `vibe3d/frontend/index.html` | Cache-busting `?v=9`, WebGL 빌드 버튼 | +8줄 |
| `vibe3d/backend/executor.py` | WebGL 빌드 지원 (non-batchable tools, compile wait, script creation) | +253줄 |
| `vibe3d/backend/webgl_builder.py` | WebGL 빌드 계획 생성기 (신규) | +927줄 |

---

## 6. 테스트

### 브라우저 콘솔 수동 테스트

```javascript
// Vibe3D iframe 내부 콘솔에서 실행
window.parent.postMessage({
    type: 'EQUIPMENT_SELECTED',
    assetTag: 'TCV-7742',
    assetName: '냉각수 펌프 A'
}, '*');
```

### 확인 사항

1. Vibe3D 3D 뷰어에서 오브젝트 클릭
2. 브라우저 콘솔에 `[Vibe3D → HeatOps] EQUIPMENT_SELECTED` 로그 출력
3. `GET /api/equipment/selected` → 선택된 설비 정보 반환
4. HeatOps Nav X에서 Toast 알림 + Navigator 자동 이동

### 디버그 로그

| 로그 메시지 | 의미 |
|-------------|------|
| `[Vibe3D → HeatOps] EQUIPMENT_SELECTED {...}` | 이벤트 생성 성공 |
| `[Vibe3D] postMessage sent to parent window` | iframe에서 부모로 전송 완료 |
| `[Vibe3D] Not in iframe — postMessage skipped` | 직접 접속 (iframe 아님) |

---

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 콘솔에 로그 없음 | 브라우저 캐시 (구 버전 app.js) | Ctrl+Shift+R 강제 새로고침 |
| postMessage skipped | Vibe3D를 직접 접속 (iframe 아님) | HeatOps iframe 내에서 테스트 |
| HeatOps에서 이벤트 못 받음 | origin 체크 실패 | `e.origin` 조건에 tunnel URL 포함 확인 |
| assetTag 매칭 안 됨 | Unity 오브젝트 이름에 P&ID 태그 없음 | 오브젝트 이름에 태그 포함 또는 매핑 테이블 추가 |
| REST polling 응답 없음 | CORS 또는 tunnel 연결 문제 | `/api/equipment/selected` 직접 호출 테스트 |
