"""
Desktop UI Control MCP Server
- 화면 캡처 (스크린샷)
- 마우스/키보드 제어
- Windows 앱 UI 요소 직접 제어
"""

import asyncio
import base64
import io
import json
from datetime import datetime
from pathlib import Path

import pyautogui
from PIL import Image
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

# pyautogui 안전 설정
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

server = Server("desktop-ui-control")


@server.list_tools()
async def list_tools():
    """사용 가능한 도구 목록"""
    return [
        Tool(
            name="screenshot",
            description="현재 화면 또는 특정 영역의 스크린샷을 찍습니다. 데스크톱 앱 화면을 볼 수 있습니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "object",
                        "description": "캡처할 영역 (선택사항). 미지정시 전체 화면",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"}
                        }
                    },
                    "save_path": {
                        "type": "string",
                        "description": "저장할 파일 경로 (선택사항)"
                    }
                }
            }
        ),
        Tool(
            name="click",
            description="지정한 좌표를 마우스로 클릭합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X 좌표"},
                    "y": {"type": "integer", "description": "Y 좌표"},
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "default": "left"
                    },
                    "clicks": {"type": "integer", "default": 1}
                },
                "required": ["x", "y"]
            }
        ),
        Tool(
            name="type_text",
            description="키보드로 텍스트를 입력합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "입력할 텍스트"},
                    "interval": {"type": "number", "default": 0.05}
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="hotkey",
            description="단축키를 누릅니다. 예: ctrl+c, alt+tab, win+d",
            inputSchema={
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "누를 키 조합. 예: ['ctrl', 'c']"
                    }
                },
                "required": ["keys"]
            }
        ),
        Tool(
            name="move_mouse",
            description="마우스를 지정한 좌표로 이동합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "duration": {"type": "number", "default": 0.2}
                },
                "required": ["x", "y"]
            }
        ),
        Tool(
            name="get_mouse_position",
            description="현재 마우스 위치를 반환합니다.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_screen_size",
            description="화면 해상도를 반환합니다.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="find_window",
            description="창 제목으로 윈도우를 찾습니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "찾을 창 제목 (부분 일치)"}
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="list_windows",
            description="현재 열린 모든 창 목록을 반환합니다.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="focus_window",
            description="특정 창을 활성화(포커스)합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "활성화할 창 제목"}
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="scroll",
            description="마우스 휠 스크롤을 수행합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "스크롤 양 (양수: 위, 음수: 아래)"},
                    "x": {"type": "integer", "description": "스크롤할 X 좌표 (선택)"},
                    "y": {"type": "integer", "description": "스크롤할 Y 좌표 (선택)"}
                },
                "required": ["amount"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """도구 실행"""
    try:
        if name == "screenshot":
            return await take_screenshot(arguments)
        elif name == "click":
            return await do_click(arguments)
        elif name == "type_text":
            return await do_type(arguments)
        elif name == "hotkey":
            return await do_hotkey(arguments)
        elif name == "move_mouse":
            return await do_move(arguments)
        elif name == "get_mouse_position":
            pos = pyautogui.position()
            return [TextContent(type="text", text=f"마우스 위치: x={pos.x}, y={pos.y}")]
        elif name == "get_screen_size":
            size = pyautogui.size()
            return [TextContent(type="text", text=f"화면 크기: {size.width}x{size.height}")]
        elif name == "find_window":
            return await find_window(arguments)
        elif name == "list_windows":
            return await list_all_windows()
        elif name == "focus_window":
            return await focus_window(arguments)
        elif name == "scroll":
            return await do_scroll(arguments)
        else:
            return [TextContent(type="text", text=f"알 수 없는 도구: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"오류 발생: {str(e)}")]


async def take_screenshot(args: dict):
    """스크린샷 찍기"""
    region = args.get("region")
    save_path = args.get("save_path")
    
    if region:
        img = pyautogui.screenshot(region=(
            region["x"], region["y"], 
            region["width"], region["height"]
        ))
    else:
        img = pyautogui.screenshot()
    
    # 이미지 크기 조절 (너무 크면 축소)
    max_size = 1920
    if img.width > max_size or img.height > max_size:
        ratio = min(max_size / img.width, max_size / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    
    if save_path:
        img.save(save_path)
        return [TextContent(type="text", text=f"스크린샷 저장됨: {save_path}")]
    
    # Base64로 인코딩하여 반환
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    return [ImageContent(type="image", data=img_base64, mimeType="image/png")]


async def do_click(args: dict):
    """마우스 클릭"""
    x, y = args["x"], args["y"]
    button = args.get("button", "left")
    clicks = args.get("clicks", 1)
    pyautogui.click(x, y, clicks=clicks, button=button)
    return [TextContent(type="text", text=f"클릭 완료: ({x}, {y}) - {button} 버튼, {clicks}회")]


async def do_type(args: dict):
    """텍스트 입력"""
    text = args["text"]
    interval = args.get("interval", 0.05)
    pyautogui.write(text, interval=interval)
    return [TextContent(type="text", text=f"입력 완료: {text[:50]}...")]


async def do_hotkey(args: dict):
    """단축키 누르기"""
    keys = args["keys"]
    pyautogui.hotkey(*keys)
    return [TextContent(type="text", text=f"단축키 실행: {'+'.join(keys)}")]


async def do_move(args: dict):
    """마우스 이동"""
    x, y = args["x"], args["y"]
    duration = args.get("duration", 0.2)
    pyautogui.moveTo(x, y, duration=duration)
    return [TextContent(type="text", text=f"마우스 이동: ({x}, {y})")]


async def do_scroll(args: dict):
    """스크롤"""
    amount = args["amount"]
    x = args.get("x")
    y = args.get("y")
    if x and y:
        pyautogui.scroll(amount, x=x, y=y)
    else:
        pyautogui.scroll(amount)
    direction = "위" if amount > 0 else "아래"
    return [TextContent(type="text", text=f"스크롤 {direction}로 {abs(amount)} 수행")]


async def find_window(args: dict):
    """창 찾기"""
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        title = args["title"].lower()
        
        found = []
        for win in desktop.windows():
            try:
                win_title = win.window_text()
                if title in win_title.lower():
                    rect = win.rectangle()
                    found.append({
                        "title": win_title,
                        "x": rect.left,
                        "y": rect.top,
                        "width": rect.width(),
                        "height": rect.height()
                    })
            except:
                pass
        
        if found:
            return [TextContent(type="text", text=json.dumps(found, ensure_ascii=False, indent=2))]
        else:
            return [TextContent(type="text", text=f"'{args['title']}' 창을 찾을 수 없습니다.")]
    except Exception as e:
        return [TextContent(type="text", text=f"창 찾기 오류: {str(e)}")]


async def list_all_windows():
    """모든 창 목록"""
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        
        windows = []
        for win in desktop.windows():
            try:
                title = win.window_text()
                if title.strip():
                    rect = win.rectangle()
                    windows.append({
                        "title": title,
                        "x": rect.left,
                        "y": rect.top,
                        "width": rect.width(),
                        "height": rect.height()
                    })
            except:
                pass
        
        return [TextContent(type="text", text=json.dumps(windows[:20], ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=f"창 목록 오류: {str(e)}")]


async def focus_window(args: dict):
    """창 활성화"""
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        title = args["title"].lower()
        
        for win in desktop.windows():
            try:
                win_title = win.window_text()
                if title in win_title.lower():
                    win.set_focus()
                    return [TextContent(type="text", text=f"창 활성화 완료: {win_title}")]
            except:
                pass
        
        return [TextContent(type="text", text=f"'{args['title']}' 창을 찾을 수 없습니다.")]
    except Exception as e:
        return [TextContent(type="text", text=f"창 활성화 오류: {str(e)}")]


async def main():
    """서버 실행"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
