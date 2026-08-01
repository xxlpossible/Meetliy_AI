from utils.env import load_project_env

# 必须在所有业务模块导入之前加载项目根目录下的 .env，
# 否则 settings.py 等模块在 import 时无法读取环境变量
load_project_env()

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.middleware.cors import setup_cors


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app():
    """Create the FastAPI app and include the router."""

    fastapi_app = FastAPI(
        title="基于LangChain的智能会议纪要助手的设计与开发",
        description="邓炳山毕业设计",
        version="0.0.1",
        lifespan=lifespan
    )

    setup_cors(fastapi_app)
    fastapi_app.include_router(router)

    return fastapi_app


app = create_app()

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=31818, workers=1, ws_ping_timeout=60, ws_ping_interval=120)
