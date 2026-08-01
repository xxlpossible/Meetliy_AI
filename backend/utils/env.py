"""
统一环境变量加载工具。

设计目标：后端所有模块统一从「项目根目录」加载 .env 文件，
同时适配本地开发（Windows/项目根目录）与服务器部署（如 /root/meetily/.env）。

约定：
    - 项目根目录 = 包含 backend/ 目录的上一级目录。
      本地：d:/Python/Code/the_graduation_project
      服务器：/root/meetily
    - 统一读取 <项目根目录>/.env，不再读取 backend/.env。
"""
import os
from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """
    向上查找包含 backend 目录的项目根目录。
    从本文件所在位置（backend/utils/）向上逐级查找，找到含 backend/ 的目录即返回。
    """
    current = (start or Path(__file__).resolve().parent).resolve()
    for _ in range(8):
        if (current / "backend").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # 兜底：返回调用文件所在目录的上级（尽量靠近根）
    return current


# 项目根目录
PROJECT_ROOT = find_project_root()

# 统一 .env 路径
ENV_PATH = PROJECT_ROOT / ".env"


def load_project_env() -> Path | None:
    """
    加载项目根目录下的 .env 文件。
    返回加载的文件路径；若不存在则返回 None（不抛错，便于兼容）。
    """
    from dotenv import load_dotenv

    if ENV_PATH.exists():
        # override=False：已存在的系统环境变量优先，避免覆盖部署平台注入的变量
        load_dotenv(ENV_PATH, override=False)
        return ENV_PATH
    return None
