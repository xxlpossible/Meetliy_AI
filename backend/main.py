import dotenv
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.router import router


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

    # ✅ 修正部分：显式指定前端的 Origin
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost",
        "http://127.0.0.1",
        "http://192.168.11.210:31818"
    ]

    # ✅ 先加中间件（虽然顺序在这里影响不大，但推荐尽早）
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,  # 明确指定前端地址
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    fastapi_app.include_router(router)

    # 挂载前端测试页面到 /test 路径，便于通过 http://localhost:31818/test/ 访问
    # 同源访问无 CORS 问题
    # frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend_test")
    # if os.path.isdir(frontend_dir):
    #     fastapi_app.mount("/test", StaticFiles(directory=frontend_dir), name="frontend_test")

    return fastapi_app


app = create_app()

dotenv.load_dotenv(".env")

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=31818, workers=1, ws_ping_timeout=60, ws_ping_interval=120)
