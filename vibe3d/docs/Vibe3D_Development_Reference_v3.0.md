# Vibe3D Unity Accelerator — Development Reference v3.0

> **Date**: 2026-03-03
> **Version**: v2.7+ (cumulative)
> **Total Lines of Code**: 36,195+ (Python + JavaScript + C# + JSON Schema)
> **Total Source Files**: 60+
> **Web UI**: http://127.0.0.1:8091
> **API Docs**: http://127.0.0.1:8091/docs

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Version History](#3-version-history)
4. [Backend — Core Modules](#4-backend--core-modules)
5. [Backend — Drone Pipeline](#5-backend--drone-pipeline)
6. [Frontend — Web UI](#6-frontend--web-ui)
7. [Unity C# Scripts](#7-unity-c-scripts)
8. [API Endpoints (60+)](#8-api-endpoints-60)
9. [WebSocket Events](#9-websocket-events)
10. [NLU Pipeline](#10-nlu-pipeline)
11. [Plan Schema & Validation](#11-plan-schema--validation)
12. [3D Scene Viewer (Three.js)](#12-3d-scene-viewer-threejs)
13. [Key Features Summary](#13-key-features-summary)
14. [Technology Stack](#14-technology-stack)
15. [Configuration & Environment](#15-configuration--environment)
16. [Build & Distribution](#16-build--distribution)
17. [Known Pitfalls](#17-known-pitfalls)
18. [File Index with Line Counts](#18-file-index-with-line-counts)

---

## 1. Project Overview

**Vibe3D Unity Accelerator**는 자연어(한국어/영어)를 Unity 3D 명령으로 변환하는 AI-first 시스템입니다.

### 핵심 컨셉
- **자연어 → 3D**: 채팅으로 Unity 씬을 제어 ("10m x 10m 바닥 만들어줘")
- **승인 워크플로우**: 계획 미리보기 → 사용자 승인 → 실행 → 되돌리기(Undo)
- **MCP 프로토콜**: Unity Editor와 HTTP+SSE 통신
- **Web 기반 3D 뷰어**: Three.js로 실시간 씬 시각화
- **Drone→Digital Twin**: 사진측량 파이프라인 (COLMAP → Blender → Unity)
- **GeoBIM**: 건물 자동 추출 (RANSAC+DBSCAN) + 가시성/경로 분석

### 사용 시나리오
1. **산업 시설 설계**: 바이오매스/바이오가스 플랜트 3D 모델링
2. **도시 모델링**: OBJ 타일 기반 도시 데이터 → Unity 스트리밍
3. **드론 촬영 → 3D 변환**: Photogrammetry → 메시 최적화 → Unity Import
4. **GeoBIM 분석**: 건물 추출, 가시성, 경로탐색, 면적 측정

---

## 2. Architecture

```
┌───────────────────────────────────────────────────────┐
│                    Web Browser                         │
│  ┌──────────┐  ┌────────────┐  ┌───────────────────┐  │
│  │ Explorer  │  │ 3D Viewer  │  │  Chat / Jobs      │  │
│  │ (files)   │  │ (Three.js) │  │  (approval cards) │  │
│  └──────────┘  └────────────┘  └───────────────────┘  │
│         │              │                │              │
│         └──────── WebSocket + REST API ─┘              │
└───────────────────────────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │   FastAPI Backend    │
              │   (127.0.0.1:8091)  │
              │                     │
              │  ┌──── NLU ────┐    │
              │  │ Claude API  │    │
              │  │ + Templates │    │
              │  └─────────────┘    │
              │  ┌── Pipeline ─┐    │
              │  │ Generator   │    │
              │  │ Validator   │    │
              │  │ Executor    │    │
              │  └─────────────┘    │
              │  ┌── Drone ────┐    │
              │  │ Ingest/QA   │    │
              │  │ COLMAP      │    │
              │  │ Blender     │    │
              │  │ GeoBIM      │    │
              │  └─────────────┘    │
              └──────────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │    MCP Client       │
              │  (HTTP+SSE Transport)│
              └──────────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │   Unity Editor      │
              │  (MCP for Unity)    │
              │  C# Runtime Scripts │
              └─────────────────────┘
```

---

## 3. Version History

| Version | Commit | Features |
|---------|--------|----------|
| **v1.0** | `48899db` | Unity Accelerator 초기 버전 + Fermentation Digital Twin |
| **v2.1** | `48899db` | NLU 엔진, 계획 생성/검증/실행, WebSocket, 3D 뷰어 |
| **v2.2** | `a9ec48c` | EXE 배포 (PyInstaller), 3D Move Mode, Target Tag, Undo |
| **v2.3** | `55e6587` | Equipment Selection API, WebGL Build, HeatOps 연동 |
| **v2.4** | `8a70e82` | SELECT_OBJECT inbound API, 프리미티브 형상 수정, 시스템 문서 |
| **v2.5** | `9ba8329` | LOD 자동 생성 (Vertex Clustering), 타일 스트리밍 (CityTileStreamer) |
| **v2.6** | (uncommitted) | GeoBIM 파이프라인 (RANSAC+DBSCAN), 측정 도구, NavMesh, 가시성 분석 |
| **v2.7** | (uncommitted) | Mesh Edit 파이프라인, Floating Origin, Building Index, UI 고도화 |

---

## 4. Backend — Core Modules

총 **12,135 lines** (Python, `backend/*.py`)

| Module | Lines | Description |
|--------|-------|-------------|
| `main.py` | 2,128 | FastAPI 앱 + 60+ 라우트 + WebSocket + 미들웨어 |
| `plan_generator.py` | 1,873 | NL→Plan 변환 (Claude API + 템플릿 폴백) |
| `plan_validator.py` | 1,152 | JSON Schema 검증 + 안전성 검사 + MCP 커맨드 변환 |
| `source_analyzer.py` | 1,010 | 소스 파일 품질 분석 (3D/텍스처/데이터 포맷) |
| `webgl_builder.py` | 927 | WebGL 뷰어 셋업 + 빌드 계획 생성 (C# 코드 포함) |
| `executor.py` | 693 | MCP 계획 실행 + Undo 생성 + 진행률 추적 |
| `component_library.py` | 607 | 산업 장비 템플릿 (파이프, 밸브, 센서) |
| `error_analyzer.py` | 598 | 에러 진단 + 복구 제안 |
| `scene_cache.py` | 588 | 씬 계층 캐시 + 공간 추론 |
| `nlu_engine.py` | 525 | AI NLU (색상 파싱, 오타 보정, 한국어) |
| `suggestion_engine.py` | 521 | 예측 명령 제안 (히스토리 기반) |
| `composite_analyzer.py` | 504 | 복합 파일 분석 + 관계 추론 |
| `workflow_manager.py` | 492 | 템플릿 워크플로우 관리 |
| `fermentation_bridge.py` | 450 | 발효 시뮬레이션 ↔ Unity 시각화 브릿지 |
| `config.py` | 67 | 환경 설정 (경로, 환경변수) |

### MCP Client (280 lines)

| Module | Lines | Description |
|--------|-------|-------------|
| `mcp_client/client.py` | 280 | UnityMCP HTTP+SSE 트랜스포트 클라이언트 |

---

## 5. Backend — Drone Pipeline

총 **8,800 lines** (Python, `backend/drone_pipeline/*.py`)

### 핵심 파이프라인

| Module | Lines | Description |
|--------|-------|-------------|
| `pipeline_orchestrator.py` | 640 | Drone2Twin 상태 머신 (싱글톤) |
| `geobim_pipeline.py` | 199 | 건물 추출 파이프라인 (5단계 워크플로우) |
| `geobim_extractor.py` | 563 | RANSAC+DBSCAN 건물 세그멘테이션 + 속성 추출 |
| `geobim_simulation.py` | 639 | 건물 가시성 / 교통 시뮬레이션 |
| `geobim_db.py` | 412 | SQLite 건물 메타데이터 저장소 |
| `geobim_collider_proxy.py` | 253 | Blender 헤드리스 충돌체 생성 |
| `geobim_export.py` | 129 | JSONL 내보내기 + Unity 폴더 구조 |
| `geobim_models.py` | 258 | Pydantic 모델 (Building, PipelineStage) |
| `geobim_router.py` | 407 | GeoBIM REST API (18+ 엔드포인트) |

### 메시 편집 / 최적화

| Module | Lines | Description |
|--------|-------|-------------|
| `mesh_edit_engine.py` | 375 | Blender 기반 메시 편집 |
| `mesh_edit_manager.py` | 666 | 편집 워크플로우 오케스트레이션 |
| `mesh_edit_models.py` | 200 | 메시 편집 Pydantic 모델 |
| `mesh_edit_router.py` | 192 | 메시 편집 REST API |
| `optimize_engine.py` | 384 | Blender 메시 최적화 (Decimation) |
| `tile_validator.py` | 354 | 타일 포맷 유효성 검사 |

### 데이터 수집 / 처리

| Module | Lines | Description |
|--------|-------|-------------|
| `ingest_qa.py` | 477 | 품질 보증 (OBJ/MTL/텍스처 검증) |
| `unity_import_planner.py` | 691 | Unity 임포트 MCP 계획 생성 |
| `obj_folder_scanner.py` | 229 | OBJ 타일 인벤토리 스캔 |
| `lod_server.py` | 143 | LOD 스트리밍 서버 |
| `perf_reporter.py` | 141 | 성능 메트릭 수집 |

### 기타 파이프라인

| Module | Lines | Description |
|--------|-------|-------------|
| `router.py` | 431 | 드론 파이프라인 라우터 |
| `wizard_router.py` | 216 | 인터랙티브 셋업 위저드 |
| `bookmark_manager.py` | 214 | 파일 탐색기 북마크 |
| `bookmark_router.py` | 111 | 북마크 CRUD API |
| `deployment.py` | 240 | NGINX 배포 관리 |
| `models.py` | 233 | 드론 프로젝트 데이터 모델 |

### 외부 엔진 연동

| Module | Lines | Description |
|--------|-------|-------------|
| `recon_engines/colmap_adapter.py` | 415 | COLMAP 사진측량 어댑터 |
| `recon_engines/base.py` | 136 | 복원 엔진 추상 인터페이스 |
| `blender_scripts/tile_edit.py` | 683 | Blender Python 타일 편집 스크립트 |

---

## 6. Frontend — Web UI

총 **10,936 lines** (HTML + JavaScript + CSS)

| File | Lines | Description |
|------|-------|-------------|
| `index.html` | 703 | 4-패널 레이아웃 (Explorer / 3D / Chat / Inspector) |
| `static/app.js` | 4,337 | 메인 UI 컨트롤러 (90+ 함수) |
| `static/scene-viewer.js` | 1,694 | Three.js 3D 씬 뷰어 (`SceneViewer` 클래스) |
| `static/style.css` | 2,217 | 다크 테마 CSS |
| `static/drone-wizard.js` | 836 | 드론 프로젝트 셋업 위저드 |
| `static/plan-visual.js` | 518 | 계획 시각화 (타임라인 + 미니맵) |
| `static/source-picker.js` | 462 | 파일 선택 UI |
| `static/minimap.js` | 392 | 2D 미니맵 오버레이 |
| `static/suggest-ui.js` | 277 | 자동완성 드롭다운 |

### UI 레이아웃 (4-Panel Grid)

```
┌────────────────────────────────────────────────────────────────────┐
│ [Logo]  Vibe3D Unity Accelerator   [Toolbar]   [MCP●] [NLU●]     │
├──────────┬──────────────────────────┬──────────────────────────────┤
│ Explorer │                          │  Chat / AI Assistant         │
│ Drawing  │    3D Scene Viewer       │  ─────────────────           │
│ Presets  │    (Three.js Canvas)     │  Approval Cards              │
│ MeshEdit │                          │  Job Queue                   │
│ Drone2Tw │                          │  ─────────────────           │
│ GeoBIM   │    [Execution Progress]  │  [Hierarchy | Components |   │
│          │                          │   Jobs | Bookmarks | Perf]   │
│          │                          │  ─────────────────           │
│          │                          │  [Chat Input] [Send]         │
├──────────┴──────────────────────────┴──────────────────────────────┤
│ Status: Ready                                                      │
└────────────────────────────────────────────────────────────────────┘
```

### 다크 테마 색상

| Variable | Color | Usage |
|----------|-------|-------|
| `--bg-0` | `#2b2b2b` | 가장 어두운 배경 |
| `--bg-1` | `#383838` | 패널 배경 |
| `--accent` | `#3b8eea` | 파란색 (주요 액션) |
| `--success` | `#00d4a0` | 녹색 |
| `--warning` | `#ffbe44` | 주황색 |
| `--error` | `#ff6b6b` | 빨간색 |

### 키보드 단축키

| 단축키 | 동작 |
|--------|------|
| `Ctrl+Z` | Undo (마지막 작업 되돌리기) |
| `W` | Move Mode 토글 |
| `Enter` | 채팅 메시지 전송 |
| `↑/↓` | 명령 히스토리 탐색 |
| `Alt+↑` | 파일 탐색기 상위 이동 |
| `Esc` | 드롭다운/다이얼로그 닫기 |
| `Ctrl+L` | 주소창 포커스 |

---

## 7. Unity C# Scripts

총 **2,990 lines** (12개 스크립트)

### Editor 스크립트 (에디터 전용)

| Script | Lines | Description |
|--------|-------|-------------|
| `Editor/CityTileImporter.cs` | 366 | OBJ→FBX 배치 임포트, 폴더 구조 생성 |
| `Editor/CityTileLODGenerator.cs` | 491 | Vertex Clustering LOD 생성 (LOD0-3) |
| `Editor/TileEditApplier.cs` | 493 | Blender 편집 메시 → 타일 적용 |
| `Editor/Vibe3DCityTilePostprocessor.cs` | 61 | 임포트 후처리 설정 |

### Runtime 스크립트 (플레이 + 에디터)

| Script | Lines | Description |
|--------|-------|-------------|
| `Runtime/CityTileStreamer.cs` | 386 | 거리 기반 타일 활성화/비활성화 (히스테리시스) |
| `Runtime/FloatingOriginManager.cs` | 106 | 대규모 월드 원점 재계산 (지리공간) |
| `Runtime/BuildingIndexManager.cs` | 170 | GeoBIM 건물 ID 조회 + 캐싱 |
| `Runtime/MeasurementManager.cs` | 251 | 거리/높이/면적 측정 도구 (Raycast) |
| `Runtime/NavMeshPathfinder.cs` | 197 | NavMesh A* 경로탐색 + 시각화 |
| `Runtime/VisibilityAnalyzer.cs` | 188 | 센서 기반 가시성 히트맵 (FOV 제한) |
| `Runtime/SelectionHighlightManager.cs` | 153 | 선택 오브젝트 하이라이트 (아웃라인) |
| `Runtime/UIManager.cs` | 128 | 상태 표시 + 측정 결과 텍스트 |

---

## 8. API Endpoints (60+)

### 명령 실행 & 제어

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/command` | 자연어 명령 → 계획 생성 (메인 엔트리) |
| POST | `/api/command/{job_id}/approve` | 계획 승인 |
| POST | `/api/command/{job_id}/reject` | 계획 거부 |
| POST | `/api/execute` | 사전 검증된 계획 직접 실행 |
| POST | `/api/multi-command` | 순차/병렬 복합 명령 |
| POST | `/api/undo/{job_id}` | 되돌리기 (생성 액션만) |

### 계획 & 검증

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/preview` | 계획 검증 (실행 없음) |
| POST | `/api/scene/context` | 씬 컨텍스트 조회 (NLU용) |
| POST | `/api/scene/context/refresh` | 씬 캐시 갱신 |

### 씬 & 오브젝트

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/hierarchy` | 씬 그래프 (재귀) |
| GET | `/api/object/inspect` | 오브젝트 속성 조회 |
| POST | `/api/object/action` | 오브젝트 수정/삭제/조회 |
| GET | `/api/scene/save` | 씬 저장 |
| GET | `/api/screenshot` | 씬 스크린샷 |
| GET | `/api/scene/3d-data` | 3D 뷰어용 씬 데이터 |

### 시스템 & 상태

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | 서버 + MCP + NLU 상태 |
| GET | `/api/tools` | MCP 도구 목록 |
| POST | `/api/connect` | MCP 재연결 |
| GET | `/api/console` | Unity 콘솔 로그 |
| GET | `/api/jobs` | 작업 히스토리 (페이지네이션) |
| GET | `/api/command-history` | 최근 명령 목록 |

### 파일 관리

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workdir` | 현재 작업 디렉토리 |
| POST | `/api/workdir` | 작업 디렉토리 설정 |
| GET | `/api/files` | 디렉토리 파일 목록 |
| POST | `/api/workdir/pin` | 즐겨찾기 디렉토리 |
| POST | `/api/workdir/unpin` | 즐겨찾기 해제 |
| GET | `/api/files/drives` | 시스템 드라이브 목록 (Windows) |

### 소스 분석

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/source/analyze` | 단일 파일 품질 분석 |
| POST | `/api/source/to-plan` | 파일 → MCP 계획 변환 |
| POST | `/api/source/composite-analyze` | 복합 파일 분석 + 관계 추론 |
| POST | `/api/source/composite-plan` | 복합 파일 → 3D 레이아웃 |
| GET | `/api/source/batch` | 디렉토리 배치 분석 |

### WebGL 빌드

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/webgl/setup` | WebGL 카메라 리그 + 스크립트 설치 |
| POST | `/api/webgl/build` | WebGL 빌드 트리거 |
| GET | `/api/webgl/status` | 빌드 상태 |
| GET | `/api/webgl/build-status` | 상세 빌드 진행률 |

### 워크플로우 & 컴포넌트

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workflows` | 워크플로우 템플릿 목록 |
| POST | `/api/workflows` | 새 템플릿 생성 |
| POST | `/api/workflows/{id}/execute` | 파라미터로 실행 |
| GET | `/api/components` | 장비 템플릿 목록 |
| GET | `/api/suggest` | 예측 명령 제안 |
| GET | `/api/presets` | 장비 프리셋 (P&ID) |

### 채팅

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | 채팅 메시지 → NLU 응답 |
| GET | `/api/chat/history` | 대화 히스토리 |
| POST | `/api/chat/clear` | 대화 초기화 |

### 드론 파이프라인 (20+ 라우트)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/drone/project` | 드론 프로젝트 생성/로드 |
| GET | `/api/drone/projects` | 프로젝트 목록 |
| POST | `/api/drone/ingest` | 수집 + QA 시작 |
| POST | `/api/drone/reconstruct` | COLMAP 복원 |
| POST | `/api/drone/optimize` | Blender 메시 최적화 |
| POST | `/api/drone/unity-import` | Unity 임포트 계획 생성 |

### GeoBIM (18+ 라우트)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/geobim/ingest` | 건물 추출 시작 |
| GET | `/api/geobim/buildings` | 건물 조회 (공간 쿼리) |
| GET | `/api/geobim/simulation` | 가시성/교통 시뮬레이션 |
| POST | `/api/geobim/export` | SQLite+JSONL 내보내기 |

### 메시 편집

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/mesh-edit/start` | 편집 워크플로우 시작 |
| POST | `/api/mesh-edit/edit` | 정점/면 편집 적용 |
| POST | `/api/mesh-edit/save` | 편집 메시 저장 |
| GET | `/api/mesh-edit/status` | 편집 세션 상태 |

### 북마크

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/bookmarks` | 북마크 목록 |
| POST | `/api/bookmarks` | 북마크 생성 |
| DELETE | `/api/bookmarks/{id}` | 북마크 삭제 |

---

## 9. WebSocket Events

### 연결

| Endpoint | Description |
|----------|-------------|
| `/ws` | 메인 실시간 업데이트 |
| `/ws/twin` | 발효 시뮬레이션 상태 |
| `/ws/geobim` | GeoBIM 파이프라인 진행 |

### 이벤트 타입

| Event | Direction | Description |
|-------|-----------|-------------|
| `plan_preview` | Server→Client | 계획 미리보기 (승인 대기) |
| `plan_executing` | Server→Client | 실행 중 (진행률) |
| `action_completed` | Server→Client | 단일 액션 완료 |
| `plan_complete` | Server→Client | 전체 완료 |
| `console_log` | Server→Client | Unity 콘솔 메시지 |
| `scene_updated` | Server→Client | 씬 변경 알림 |

---

## 10. NLU Pipeline

```
사용자 입력 (한국어/영어)
    │
    ▼
┌─────────────────┐
│  NLU Engine      │ ← Claude API (ANTHROPIC_API_KEY)
│  (nlu_engine.py) │ ← 템플릿 폴백 (API 없을 때)
└────────┬────────┘
         │ Intent + Entities
         ▼
┌─────────────────────┐
│  Plan Generator      │ ← 씬 캐시 참조
│  (plan_generator.py) │ ← 컴포넌트 라이브러리
└────────┬────────────┘
         │ Plan JSON (actions[])
         ▼
┌─────────────────────┐
│  Plan Validator      │ ← JSON Schema (834 lines)
│  (plan_validator.py) │ ← Per-type 검증
└────────┬────────────┘
         │ Validated Plan
         ▼
┌─────────────────────┐
│  Approval Card       │ → WebSocket → 사용자 UI
│  (10분 자동 만료)     │ → 승인 / 거부 / 수정
└────────┬────────────┘
         │ Approved
         ▼
┌─────────────────────┐
│  Plan Executor       │ → MCP Batch Commands
│  (executor.py)       │ → Undo Store 생성
└────────┬────────────┘
         │ Results
         ▼
  WebSocket → 3D 뷰어 갱신 → 작업 기록
```

### 지원 의도 (Intent)

| Category | Intents |
|----------|---------|
| **생성** | create_primitive, create_empty, create_prefab |
| **수정** | modify_object (위치/회전/크기), move_relative |
| **삭제** | delete_object, delete_multiple |
| **색상** | apply_material, set_renderer_color |
| **복제** | duplicate_object |
| **조회** | get_hierarchy, inspect_object, count_objects |
| **VFX** | create_particle_system, line_renderer |
| **텍스처** | create_texture, apply_pattern/gradient/noise |
| **프리팹** | create_prefab, instantiate_prefab |
| **씬** | save_scene, load_scene, screenshot |

---

## 11. Plan Schema & Validation

**스키마 파일**: `docs/schemas/unity_plan.schema.json` (834 lines)

### 액션 타입 (65+)

| Category | Types |
|----------|-------|
| Basic Object | create_primitive, create_empty, modify_object, delete_object, duplicate_object, move_relative |
| Material & Color | apply_material, create_material, assign_material, set_material_color, set_renderer_color |
| Components | add_component, remove_component, set_component_property |
| VFX | create_particle_system, create_line_renderer, create_trail_renderer |
| Textures | create_texture, apply_texture_pattern, apply_texture_gradient, apply_texture_noise |
| Prefabs | create_prefab, instantiate_prefab, modify_prefab |
| Scene Mgmt | screenshot, save_scene, load_scene, get_hierarchy |
| Asset Mgmt | import_asset, search_assets, move_asset |

### 검증 단계
1. **JSON Schema 검증**: 구조 + 타입 확인
2. **Per-type 검증**: 액션별 필수 필드 체크
3. **안전성 검사**: 위험 작업 경고
4. **MCP 변환**: Plan → MCP batch commands

---

## 12. 3D Scene Viewer (Three.js)

### 핵심 클래스: `SceneViewer`

**초기화**:
- WebGL Renderer (안티앨리어싱, ACESFilmic 톤맵핑)
- PerspectiveCamera (FOV 50, Near 0.1, Far 500)
- FogExp2 (밀도 0.008)
- OrbitControls (마우스 회전/패닝/줌)
- TransformControls (드래그 이동)
- 조명: Ambient + 2× Directional + Hemisphere
- 그리드 (80×80) + 축

### 좌표계 변환 (Unity → Three.js)

```
Three.js Z = -Unity Z
Three.js RotXY = -Unity RotXY
Three.js RotZ = Unity RotZ
```

### 기능 목록

| Feature | Description |
|---------|-------------|
| **Object Loading** | MCP 계층 → Three.js 프리미티브 (Cube/Sphere/Cylinder 등) |
| **Color Override** | 서버 `_scene_color_overrides` → 뷰어 재적용 |
| **Move Mode** | W키 토글 → TransformControls → Unity 동기화 |
| **Selection** | Raycaster 히트 → 파란 와이어프레임 하이라이트 |
| **Camera Preserve** | 리로드 시 카메라 위치/타겟/줌 유지 |
| **City Tiles** | OBJ 로딩 + LOD (LOD0 < 300m, unload > 600m) |
| **Measurement** | 거리/높이/면적 시각화 (라인 + 라벨) |
| **Pathfinding** | A* 경로 시각화 (실린더 + 구체) |
| **Visibility** | 센서 히트맵 + 커버리지 리포트 |
| **GeoBIM Overlay** | 건물 풋프린트 (폴리곤) + BBox 와이어프레임 |
| **Floating Origin** | 카메라 500m 이동 시 원점 재설정 |
| **Minimap** | 2D 탑다운 오버레이 |

---

## 13. Key Features Summary

### 1. 자연어 명령 처리 (NLU)
- 한국어/영어 동시 지원, 오타 보정
- Claude Sonnet API (선택) + 템플릿 폴백
- 60+ 개의 액션 타입 지원

### 2. 승인 워크플로우
- 계획 미리보기 카드 (액션 수 + 타입 아이콘)
- 승인 / 거부 / 수정 후 재시도
- 10분 자동 만료
- Undo (Ctrl+Z) — 생성 액션 역방향 삭제

### 3. 3D 씬 뷰어
- Three.js WebGL 렌더러 (실시간 동기화)
- Move Mode (TransformControls → Unity 동기화)
- 카메라 유지, 미니맵, 색상 오버라이드

### 4. 파일 탐색기
- 주소창, 북마크, 즐겨찾기
- 드라이브 목록 (Windows)
- 파일 선택 → 분석 기능

### 5. 드론→디지털 트윈 파이프라인
- 사진 수집 → QA → COLMAP 복원 → Blender 최적화 → Unity 임포트
- 인터랙티브 위저드 UI

### 6. GeoBIM 건물 분석
- RANSAC 평면 피팅 + DBSCAN 클러스터링
- 높이/면적/볼륨 속성 추출
- 가시성 분석 (센서 FOV 제한)
- NavMesh A* 경로탐색
- SQLite 저장 + JSONL 내보내기

### 7. 타일 스트리밍 + LOD
- 거리 기반 활성화/비활성화 (히스테리시스)
- Vertex Clustering LOD 자동 생성 (LOD0-3)
- Floating Origin (대규모 월드)

### 8. 메시 편집 파이프라인
- 5단계 워크플로우 (Load → Select → Preset → Process → Results)
- 프리셋: Clean Noise / Decimate / Generate LODs / Collider Proxy / Pack
- 버전 히스토리 + Before/After 비교

### 9. 측정 도구
- 거리: 2점 클릭 → 라인 + 라벨
- 높이: 지면→오브젝트 수직 거리
- 면적: 다각형 (Shoelace 공식)

### 10. 장비 라이브러리
- 산업 장비 템플릿 (탱크, 파이프, 밸브, 센서)
- P&ID 기반 색상 코딩
- 클릭으로 인스턴스 생성

### 11. WebGL 빌드
- CameraRig + OrbitPanZoomController C# 자동 생성
- Unity WebGL 빌드 트리거 + 진행률 추적

### 12. EXE 배포
- PyInstaller 빌드 (Vibe3D.exe + DLL 번들)
- 2단계 .env 로딩 (번들 내부 → exe 인접)
- `build_exe.bat` → `dist/Vibe3D-win64.zip`

---

## 14. Technology Stack

### Backend
| Technology | Usage |
|-----------|-------|
| Python 3.10+ | 메인 언어 |
| FastAPI | REST API + WebSocket |
| Uvicorn | ASGI 서버 |
| Pydantic | 데이터 검증 |
| jsonschema | Plan Schema 검증 |
| Anthropic SDK | Claude API (LLM) |
| SQLite | GeoBIM, Bookmarks DB |
| asyncio | 비동기 처리 |

### Frontend
| Technology | Usage |
|-----------|-------|
| Three.js 0.163 | 3D WebGL 렌더러 |
| Vanilla JS (ES6) | UI 로직 (프레임워크 없음) |
| WebSocket | 실시간 통신 |
| CSS Custom Properties | 다크 테마 |

### Unity Integration
| Technology | Usage |
|-----------|-------|
| MCP Protocol | Unity Editor 통신 |
| Unity 6 LTS | 게임 엔진 |
| NavMesh | 경로탐색 |
| Physics.Raycast | 측정 도구 |
| LODGroup | Level-of-Detail |

### External Tools
| Tool | Usage |
|------|-------|
| Blender (headless) | 메시 최적화, 편집 |
| COLMAP | 사진측량 복원 |
| PyInstaller | EXE 배포 |
| Cloudflared | 터널링 |

---

## 15. Configuration & Environment

### 환경 변수

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_URL` | `http://localhost:8080/mcp` | Unity MCP 서버 |
| `MCP_TIMEOUT` | `60` | MCP 타임아웃 (초) |
| `ANTHROPIC_API_KEY` | (optional) | Claude API 키 |
| `CLAUDE_MODEL` | `claude-sonnet-4-5-20250929` | LLM 모델 |
| `VIBE3D_HOST` | `127.0.0.1` | 서버 호스트 |
| `VIBE3D_PORT` | `8091` | 서버 포트 |
| `UNITY_PROJECT_PATH` | `C:\UnityProjects\My project` | Unity 프로젝트 경로 |
| `DEFAULT_SCENE` | `bio-plants` | 기본 씬 이름 |
| `BLENDER_PATH` | `blender` | Blender 실행 경로 |
| `COLMAP_PATH` | `colmap` | COLMAP 실행 경로 |

### 실행 명령

```bash
# 개발 모드
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8091 --reload

# 또는 start.bat (브라우저 자동 열기)
start.bat

# EXE 빌드
build_exe.bat
```

---

## 16. Build & Distribution

### PyInstaller EXE 빌드

```
build_exe.bat
  → PyInstaller (--onedir)
  → dist/Vibe3D/Vibe3D.exe
  → dist/Vibe3D-win64.zip

번들 포함:
  - Python 3.10 런타임
  - FastAPI + Uvicorn + 의존성
  - frontend/ (정적 파일)
  - docs/schemas/ (JSON Schema)
  - .env (기본값)
```

### EXE 특이사항
- `sys._MEIPASS` 경로 해석 필요
- 2단계 .env: 번들 내부 (기본값) → exe 인접 (사용자 오버라이드)
- 프로세스 Kill 시 orphan 주의 (Windows multiprocessing)

---

## 17. Known Pitfalls

| Issue | Solution |
|-------|----------|
| MCP `set_renderer_color` | `mode="instance"` 필수 |
| MCP color format | `{"r": 0.8, "g": 0.82, "b": 0.85, "a": 1.0}` (0-1 범위) |
| MCP name collision | `search_method: "by_path"` 사용 |
| MCP batch timing | 생성과 수정을 별도 배치로 분리 |
| Korean regex `\b` | 명시적 조사 목록 사용 `(?:을\|를\|의\|에)` |
| TransformControls Z-flip | Three.js Z = -Unity Z 변환 |
| Static file cache | `index.html`에서 `?v=N` 버전 범프 |
| Undo double-fire | `_undo_store.pop()` + `_undoInProgress` 가드 |
| uvicorn orphans (Windows) | `wmic process` 로 수동 kill |
| Minimap overlay | approve/reject 후 `hideMinimap()` 호출 |

---

## 18. File Index with Line Counts

### Backend Core (12,135 lines)
```
backend/main.py                          2,128
backend/plan_generator.py                1,873
backend/plan_validator.py                1,152
backend/source_analyzer.py               1,010
backend/webgl_builder.py                   927
backend/executor.py                        693
backend/component_library.py               607
backend/error_analyzer.py                  598
backend/scene_cache.py                     588
backend/nlu_engine.py                      525
backend/suggestion_engine.py               521
backend/composite_analyzer.py              504
backend/workflow_manager.py                492
backend/fermentation_bridge.py             450
backend/config.py                           67
```

### Backend MCP Client (280 lines)
```
backend/mcp_client/client.py               280
```

### Backend Drone Pipeline (8,800 lines)
```
backend/drone_pipeline/unity_import_planner.py   691
backend/drone_pipeline/mesh_edit_manager.py      666
backend/drone_pipeline/pipeline_orchestrator.py  640
backend/drone_pipeline/geobim_simulation.py      639
backend/drone_pipeline/geobim_extractor.py       563
backend/drone_pipeline/ingest_qa.py              477
backend/drone_pipeline/router.py                 431
backend/drone_pipeline/geobim_db.py              412
backend/drone_pipeline/geobim_router.py          407
backend/drone_pipeline/optimize_engine.py        384
backend/drone_pipeline/mesh_edit_engine.py       375
backend/drone_pipeline/tile_validator.py         354
backend/drone_pipeline/geobim_models.py          258
backend/drone_pipeline/geobim_collider_proxy.py  253
backend/drone_pipeline/deployment.py             240
backend/drone_pipeline/models.py                 233
backend/drone_pipeline/obj_folder_scanner.py     229
backend/drone_pipeline/wizard_router.py          216
backend/drone_pipeline/bookmark_manager.py       214
backend/drone_pipeline/mesh_edit_models.py       200
backend/drone_pipeline/geobim_pipeline.py        199
backend/drone_pipeline/mesh_edit_router.py       192
backend/drone_pipeline/lod_server.py             143
backend/drone_pipeline/perf_reporter.py          141
backend/drone_pipeline/bookmark_router.py        111
backend/drone_pipeline/geobim_export.py          129
```

### Backend External Engines (1,234 lines)
```
backend/drone_pipeline/blender_scripts/tile_edit.py  683
backend/drone_pipeline/recon_engines/colmap_adapter.py 415
backend/drone_pipeline/recon_engines/base.py         136
```

### Frontend (10,936 lines)
```
frontend/index.html                      703
frontend/static/app.js                 4,337
frontend/static/scene-viewer.js        1,694
frontend/static/style.css              2,217
frontend/static/drone-wizard.js          836
frontend/static/plan-visual.js           518
frontend/static/source-picker.js         462
frontend/static/minimap.js               392
frontend/static/suggest-ui.js            277
```

### Unity C# Scripts (2,990 lines)
```
unity-scripts/Editor/TileEditApplier.cs           493
unity-scripts/Editor/CityTileLODGenerator.cs      491
unity-scripts/Editor/CityTileImporter.cs          366
unity-scripts/Editor/Vibe3DCityTilePostprocessor.cs 61
unity-scripts/Runtime/CityTileStreamer.cs          386
unity-scripts/Runtime/MeasurementManager.cs        251
unity-scripts/Runtime/NavMeshPathfinder.cs         197
unity-scripts/Runtime/VisibilityAnalyzer.cs        188
unity-scripts/Runtime/BuildingIndexManager.cs      170
unity-scripts/Runtime/SelectionHighlightManager.cs 153
unity-scripts/Runtime/UIManager.cs                 128
unity-scripts/Runtime/FloatingOriginManager.cs     106
```

### Schema & Config (834 lines)
```
docs/schemas/unity_plan.schema.json      834
```

---

### Total: **36,195+ lines** across **60+ source files**

---

*Generated: 2026-03-03 | Vibe3D Unity Accelerator v2.7+*
