from typing import Any, Final, TypedDict, List, Optional
import httpx
from mcp.server.lowlevel import Server
import mcp.types as types
import os
import logging
from datetime import datetime, timedelta
from functools import wraps
from dataclasses import dataclass
import json

# 初始化服务器
app = Server("weather-server")

# 常量
NWS_API_BASE: Final = "https://api.weather.gov"
USER_AGENT: Final = "weather-app/1.0"
CACHE_EXPIRATION: Final = 300  # 5分钟
MAX_RETRIES: Final = 3
REQUEST_TIMEOUT: Final = 30.0
# 存储API密钥 - 多种方式获取
OPENWEATHER_API_KEY: str = os.getenv("openweather_api_key", "")
# 如果环境变量没有设置，尝试使用配置文件中的默认值（MCP配置中的值）
if not OPENWEATHER_API_KEY:
    OPENWEATHER_API_KEY = ""  # 从mcp.json复制过来的值，用于临时测试

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('weather_service.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """处理来自客户端的工具调用。"""
    try:
        if name == "get_alerts":
            state = arguments.get("state", "")
            if not state:
                return [types.TextContent(type="text", text="错误：请提供州代码")]
            result = await get_alerts(state)
            return [types.TextContent(type="text", text=result)]
        elif name == "get_forecast":
            latitude = arguments.get("latitude")
            longitude = arguments.get("longitude")
            if latitude is None or longitude is None:
                return [types.TextContent(type="text", text="错误：请提供纬度和经度")]
            result = await get_forecast(latitude, longitude)
            return [types.TextContent(type="text", text=result)]
        else:
            return [types.TextContent(type="text", text=f"错误：未知工具：{name}")]
    except Exception as e:
        logger.error(f"工具调用错误：{str(e)}")
        return [types.TextContent(type="text", text=f"错误：{str(e)}")]

async def make_nws_request(url: str) -> dict[str, Any] | None:  
    """Make a request to the NWS API with proper error handling and retry mechanism."""  
    headers = {  
        "User-Agent": USER_AGENT,  
        "Accept": "application/geo+json",  
        "Content-Type": "application/json"  # 添加内容类型头
    }  
    async with httpx.AsyncClient(timeout=30.0) as client:  # 直接在客户端设置超时
        try:  
            response = await client.get(url, headers=headers)  
            response.raise_for_status()  
            return response.json()  
        except httpx.HTTPStatusError as e:  
            logger.error(f"HTTP error occurred: {e.response.status_code}")  
            return None  
        except httpx.RequestError as e:  
            print(f"Request error occurred: {str(e)}")  
            return None  
        except Exception as e:  
            print(f"Unexpected error: {str(e)}")  
            return None  
async def get_alerts(state: str) -> str:
    """获取指定州的天气警报"""
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "无法获取警报或未找到警报"

    if not data["features"]:
        return "该州没有活跃的警报"

    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)

def format_alert(feature: dict) -> str:
    """格式化警报信息"""
    props = feature["properties"]
    return f"""
事件：{props.get('event', '未知')}
地区：{props.get('areaDesc', '未知')}
严重程度：{props.get('severity', '未知')}
描述：{props.get('description', '无可用描述')}
说明：{props.get('instruction', '未提供具体说明')}
"""

async def get_forecast(latitude: float, longitude: float) -> str:
    """获取指定位置的天气预报"""
    global OPENWEATHER_API_KEY
    
    if not OPENWEATHER_API_KEY:
        return "请在MCP配置中设置 openweather_api_key"

    url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={OPENWEATHER_API_KEY}&units=metric"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            return format_openweather_data(data)
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenWeather API HTTP错误：{e.response.status_code}")
            return f"天气服务错误：{e.response.status_code}"
        except httpx.RequestError as e:
            logger.error(f"OpenWeather API 请求错误：{str(e)}")
            return "天气服务暂时不可用"
        except Exception as e:
            logger.error(f"OpenWeather API 未知错误：{str(e)}")
            return "天气服务暂时不可用"

def format_openweather_data(data: dict) -> str:
    """格式化OpenWeatherMap API响应数据"""
    try:
        temp = data.get('main', {}).get('temp', 0)
        weather = data.get('weather', [{}])[0]
        condition = weather.get('main', '未知')
        description = weather.get('description', '无可用描述')
        wind = data.get('wind', {})
        wind_speed = f"{wind.get('speed', 0)} m/s"
        wind_deg = wind.get('deg')
        wind_dir = get_wind_direction(wind_deg) if wind_deg is not None else '未知方向'
        
        return f"""当前天气：
温度：{temp}°C
状况：{condition}
风速：{wind_speed} {wind_dir}
描述：{description}"""
    except Exception as e:
        logger.error(f"格式化天气数据错误：{e}")
        return "无法格式化天气数据"

def get_wind_direction(degrees: float) -> str:
    """将风向度数转换为方位"""
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    index = round(degrees / 45) % 8
    return directions[index]

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """列出可用工具"""
    return [
        types.Tool(
            name="get_alerts",
            description="获取指定州的天气警报",
            inputSchema={
                "type": "object",
                "required": ["state"],
                "properties": {
                    "state": {"type": "string", "description": "两字母州代码（例如 CA, NY）"}
                }
            }
        ),
        types.Tool(
            name="get_forecast",
            description="获取指定位置的天气预报",
            inputSchema={
                "type": "object",
                "required": ["latitude", "longitude"],
                "properties": {
                    "latitude": {"type": "number", "description": "位置的纬度"},
                    "longitude": {"type": "number", "description": "位置的经度"}
                }
            }
        )
    ]

if __name__ == "__main__":
    import sys
    # 默认使用标准输入输出传输
    transport = "sse"
    port = 9000
    # 检查命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "sse":
            transport = "sse"
        if len(sys.argv) > 2:
            try:
                port = int(sys.argv[2])
            except ValueError:
                pass
    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        import uvicorn
        
        # 使用通配符路径，允许捕获路径中的API密钥
        sse = SseServerTransport("/messages/")
        
        async def handle_sse(request):
            global OPENWEATHER_API_KEY
            
            # 尝试从路由参数中获取API密钥
            api_key = request.path_params.get("api_key")
            if api_key:
                OPENWEATHER_API_KEY = api_key
                logger.info(f"从URL路径参数成功获取OpenWeather API密钥: {api_key[:4]}...{api_key[-4:]}")
            else:
                # 如果路由参数中没有API密钥，尝试从URL路径中提取
                path = request.scope["path"]
                logger.info(f"请求路径: {path}")
                
                if path.startswith('/sse/'):
                    # 从路径中提取密钥 - 格式 /sse/API_KEY
                    path_parts = path.split('/sse/')
                    if len(path_parts) > 1 and path_parts[1]:
                        OPENWEATHER_API_KEY = path_parts[1]
                        logger.info(f"从URL路径成功获取OpenWeather API密钥: {OPENWEATHER_API_KEY[:4]}...{OPENWEATHER_API_KEY[-4:]}")
                else:
                    # 如果URL中没有找到密钥，尝试从环境变量获取
                    api_keys_to_try = [
                        os.getenv("openweather_api_key"),           # 系统环境变量
                        os.getenv("OPENWEATHER_API_KEY"),           # 大写变量名
                        os.environ.get("openweather_api_key")       # environ字典
                    ]
                    
                    # 尝试所有可能的API密钥获取方式
                    for key in api_keys_to_try:
                        if key:
                            OPENWEATHER_API_KEY = key
                            logger.info(f"成功获取OpenWeather API密钥: {key[:4]}...{key[-4:]}")
                            break
            
            if not OPENWEATHER_API_KEY:
                logger.warning("无法从任何来源获取OpenWeather API密钥")
            
            # 创建初始化选项，但不尝试修改它
            init_options = app.create_initialization_options()
            
            # 连接SSE并运行应用
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await app.run(streams[0], streams[1], init_options)
        
        # 添加两个路由：一个是基本的/sse路径，另一个是带密钥的/sse/{api_key}路径
        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/sse/{api_key:path}", endpoint=handle_sse),  # 捕获API密钥作为路径参数
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )
        print(f"在端口{port}上启动MCP服务器，使用SSE传输")
        logger.info(f"在端口{port}上启动MCP服务器，使用SSE传输")
        if OPENWEATHER_API_KEY:
            masked_key = f"{OPENWEATHER_API_KEY[:4]}...{OPENWEATHER_API_KEY[-4:]}"
            logger.info(f"OpenWeather API密钥已配置: {masked_key}")
        else:
            logger.warning("OpenWeather API密钥未配置，天气预报功能将不可用")
        logger.info(f"当前环境变量: {os.environ.get('openweather_api_key', '未设置')}")
        uvicorn.run(starlette_app, host="0.0.0.0", port=port)
    else:
        from mcp.server.stdio import stdio_server
        import anyio
