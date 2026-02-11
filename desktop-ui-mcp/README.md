# Desktop UI Control MCP

Claude가 데스크톱 앱 화면을 보고 조작할 수 있게 해주는 MCP 서버입니다.

## 기능

- **screenshot**: 화면 캡처 (전체 또는 특정 영역)
- **click**: 마우스 클릭
- **type_text**: 키보드 텍스트 입력
- **hotkey**: 단축키 실행 (ctrl+c, alt+tab 등)
- **move_mouse**: 마우스 이동
- **scroll**: 마우스 휠 스크롤
- **get_mouse_position**: 현재 마우스 위치
- **get_screen_size**: 화면 해상도
- **list_windows**: 열린 창 목록
- **find_window**: 창 찾기
- **focus_window**: 창 활성화

## 설치

```bash
pip install pyautogui pywinauto pillow mcp
```

## Claude Desktop 설정

`claude_desktop_config.json`에 추가:

```json
{
  "mcpServers": {
    "desktop-ui": {
      "command": "C:\\Python313\\python.exe",
      "args": ["경로/server.py"]
    }
  }
}
```

## 사용 예시

Claude에게 요청:
- "현재 화면 보여줘"
- "GitHub Desktop 창 찾아서 클릭해줘"
- "열린 창 목록 보여줘"
