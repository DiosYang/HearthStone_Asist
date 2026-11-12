"""只读取配置；不请求模型，不创建聊天历史，不打印密钥。"""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str
    base_url: str
    project_root: Path
    env_file: Path


def load_settings(project_root=PROJECT_ROOT):
    root = Path(project_root).resolve()
    local_env = root / ".env"
    env_file = local_env if local_env.is_file() else root.parent / ".env"
    # 已存在的终端环境变量优先；本地.env存在时不混用上级.env。
    load_dotenv(env_file, override=False)
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
    if not model:
        raise ValueError("DEEPSEEK_MODEL不能为空")
    address = urlparse(base_url)
    if address.scheme != "https" or address.netloc != "api.deepseek.com" or address.path not in ("", "/v1"):
        raise ValueError("第一阶段只允许DeepSeek官方HTTPS地址，避免误把Key发送到其他站点")
    return Settings(key, model, base_url, root, env_file)
