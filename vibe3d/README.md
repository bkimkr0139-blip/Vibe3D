# Vibe3D Unity Accelerator

자연어 명령으로 Unity 씬을 제어하는 AI 기반 도구입니다.

## 실행 전 준비 사항

### 1. Unity + MCP 서버
- **Unity 6 LTS** 이상 설치
- Unity 프로젝트에 **MCP-FOR-UNITY** 패키지 설치
- Unity 에디터에서 프로젝트를 열고 **Play 모드 진입 없이** MCP 서버 활성화
- MCP 서버 기본 주소: `http://localhost:8080/mcp`

### 2. (선택) Anthropic API Key
- AI 기반 자연어 명령을 사용하려면 `ANTHROPIC_API_KEY` 필요
- API Key 없이도 템플릿 기반 명령(생성, 삭제, 색상 변경 등)은 동작합니다

## 실행 방법

### EXE 실행 (배포 패키지)
1. ZIP 파일을 원하는 위치에 압축 해제
2. `Vibe3D.exe` 더블클릭
3. 콘솔 창에 서버 주소가 표시되면 브라우저가 자동으로 열립니다

### Python 소스 실행 (개발용)
```bash
cd vibe3d
pip install -r requirements.txt
python -m uvicorn vibe3d.backend.main:app --host 127.0.0.1 --port 8091
```

## .env 설정

`Vibe3D.exe`와 같은 폴더에 `.env` 파일이 있습니다. 텍스트 편집기로 수정 후 재시작하면 반영됩니다.

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `MCP_SERVER_URL` | `http://localhost:8080/mcp` | Unity MCP 서버 주소 |
| `MCP_TIMEOUT` | `60` | MCP 요청 타임아웃 (초) |
| `VIBE3D_HOST` | `127.0.0.1` | 웹 서버 바인딩 주소 |
| `VIBE3D_PORT` | `8091` | 웹 서버 포트 |
| `ANTHROPIC_API_KEY` | *(빈 값)* | Claude API 키 (AI 명령용) |
| `CLAUDE_MODEL` | `claude-sonnet-4-5-20250929` | 사용할 Claude 모델 |
| `UNITY_PROJECT_PATH` | `C:\UnityProjects\My project` | Unity 프로젝트 경로 |
| `DEFAULT_SCENE` | `bio-plants` | 기본 씬 이름 |

## 트러블슈팅

### 포트 충돌 (Address already in use)
`.env`에서 `VIBE3D_PORT`를 다른 번호(예: 8092)로 변경하거나, 기존 프로세스를 종료합니다:
```
netstat -ano | findstr :8091
taskkill /PID <PID> /F
```

### MCP 연결 실패
- Unity 에디터가 실행 중인지 확인
- MCP 서버가 활성화되어 있는지 확인 (Unity 콘솔에서 MCP 로그 확인)
- `.env`의 `MCP_SERVER_URL`이 올바른지 확인

### 방화벽 차단
Windows 방화벽이 `Vibe3D.exe`의 네트워크 접근을 차단할 수 있습니다.
Windows 보안 → 방화벽 → 앱 허용에서 Vibe3D를 추가하세요.

### 브라우저가 자동으로 열리지 않는 경우
콘솔에 표시된 주소(기본: `http://127.0.0.1:8091`)를 브라우저에 직접 입력하세요.

## 폴더 구조 (EXE 배포)

```
Vibe3D/
├── Vibe3D.exe            ← 실행 파일
├── README.md             ← 이 문서
├── .env                  ← 설정 파일 (편집 가능)
├── vibe3d/
│   ├── frontend/         ← 웹 UI (HTML/JS/CSS)
│   ├── data/             ← workflows.json
│   └── docs/             ← 스키마, 프롬프트
└── (Python 런타임 + DLLs)
```
