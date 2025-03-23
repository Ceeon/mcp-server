from typing import Any, Final, TypedDict, List, Optional
import httpx  
from mcp.server.fastmcp import FastMCP  
from tenacity import retry, stop_after_attempt, wait_exponential
import logging
from functools import wraps, lru_cache
from dataclasses import dataclass
from typing import Optional
import os
from datetime import datetime, timedelta
  
# Initialize FastMCP server  
mcp = FastMCP("weather")  
  
# 从MCP配置中获取API密钥

# Constants  
NWS_API_BASE: Final = "https://api.weather.gov"  
USER_AGENT: Final = "weather-app/1.0"  
CACHE_EXPIRATION: Final = 300  # 5 minutes  
MAX_RETRIES: Final = 3  
REQUEST_TIMEOUT: Final = 30.0  

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
  
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
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
  
def format_alert(feature: dict) -> str:  
    """Format an alert feature into a readable string."""  
    props = feature["properties"]  
    return f"""  
Event: {props.get('event', 'Unknown')}  
Area: {props.get('areaDesc', 'Unknown')}  
Severity: {props.get('severity', 'Unknown')}  
Description: {props.get('description', 'No description available')}  
Instructions: {props.get('instruction', 'No specific instructions provided')}  
"""  
  
@mcp.tool()  
async def get_alerts(state: str) -> str:  
    """Get weather alerts for a US state.  
  
    Args:        state: Two-letter US state code (e.g. CA, NY)    """    
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"  
    data = await make_nws_request(url)  
  
    if not data or "features" not in data:  
        return "Unable to fetch alerts or no alerts found."  
  
    if not data["features"]:  
        return "No active alerts for this state."  
  
    alerts = [format_alert(feature) for feature in data["features"]]  
    return "\n---\n".join(alerts)  
  
def validate_coordinates(func):
    @wraps(func)
    async def wrapper(latitude: float, longitude: float, *args, **kwargs):
        try:
            lat = float(latitude)
            lon = float(longitude)
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return "Invalid latitude or longitude values"
            return await func(lat, lon, *args, **kwargs)
        except ValueError:
            return "Coordinates must be valid numbers"
    return wrapper

@mcp.tool()
@validate_coordinates
async def get_forecast(latitude: float, longitude: float) -> str:  
    """Get weather forecast for a location.  
  
    Args:        latitude: Latitude of the location        longitude: Longitude of the location    """    
    try:
        # 从MCP配置获取API密钥
        api_key = os.getenv("openweather_api_key")
        if not api_key:
            return "请在MCP配置中设置 openweather_api_key"
            
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={api_key}&units=metric"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()
            
            if response.status_code == 200:
                return format_openweather_data(data)
            else:
                logger.error(f"OpenWeather API error: {response.status_code}")
                return "Weather service temporarily unavailable1"
                
    except Exception as e:
        logger.error(f"Forecast error: {str(e)}")
        return "Weather service temporarily unavailable2"
  
@dataclass
class WeatherData:
    temperature: float
    condition: str
    wind_speed: str
    wind_direction: str
    description: str

def format_openweather_data(data: dict) -> str:
    """Format OpenWeatherMap API response data."""
    try:
        # 获取温度，默认为0
        temp = data.get('main', {}).get('temp', 0)
        
        # 获取天气状况，默认为未知
        weather = data.get('weather', [{}])[0]
        condition = weather.get('main', 'Unknown')
        description = weather.get('description', 'No description available')
        
        # 获取风速，默认为0
        wind = data.get('wind', {})
        wind_speed = f"{wind.get('speed', 0)} m/s"
        
        # 获取风向，如果deg不存在则显示未知方向
        wind_deg = wind.get('deg')
        wind_dir = get_wind_direction(wind_deg) if wind_deg is not None else 'Unknown direction'
        
        return f"""Current Weather:
Temperature: {temp}°C
Condition: {condition}
Wind: {wind_speed} {wind_dir}
Description: {description}"""
    except Exception as e:
        logger.error(f"Error formatting weather data: {e}")
        return "Unable to format weather data"

def get_wind_direction(degrees: float) -> str:
    """Convert wind degrees to cardinal direction."""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = round(degrees / 45) % 8
    return directions[index]

async def get_backup_forecast(latitude: float, longitude: float) -> str:
    """备用天气API处理函数"""
    try:
        # 从MCP配置获取API密钥
        api_key = os.getenv("openweather_api_key")
        if not api_key:
            return "请在MCP配置中设置 openweather_api_key"
            
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={api_key}&units=metric"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()
            
            if response.status_code == 200:
                return format_openweather_data(data)
            else:
                logger.error(f"Backup API error: {response.status_code}")
                return "Weather service temporarily unavailable3"
                
    except Exception as e:
        logger.error(f"Backup forecast error: {str(e)}")
        return "Weather service temporarily unavailable4"  
  
class TimedCache:
    def __init__(self, expiration_time: int = 300):  # 默认5分钟过期
        self.cache = {}
        self.expiration_time = expiration_time

    def get(self, key: str) -> Optional[dict]:
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.expiration_time):
                return data
            else:
                del self.cache[key]
        return None

    def set(self, key: str, value: dict):
        self.cache[key] = (value, datetime.now())

weather_cache = TimedCache()
  
if __name__ == "__main__":  
    # 按照官方文档的方式运行服务器
    print("正在启动MCP服务器...")
    try:
        # 设置环境变量
        os.environ["openweather_api_key"] = "f2860a0db0f7b3c3aab6322d8e04d4e6"
        # 获取 PORT 环境变量，默认为 10000
        port = int(os.environ.get("PORT", 10000))
        # 使用默认传输方式运行，指定主机和端口
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    except Exception as e:
        print(f"启动失败: {e}")

class WeatherPeriod(TypedDict):
    name: str
    temperature: float
    temperatureUnit: str
    windSpeed: str
    windDirection: str
    detailedForecast: str

class ForecastResponse(TypedDict):
    properties: dict
    periods: List[WeatherPeriod]
