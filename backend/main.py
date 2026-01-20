import dotenv
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.router import router


def create_app():
    """Create the FastAPI app and include the router."""

    fastapi_app = FastAPI(
        title="基于LangChain的智能会议纪要助手的设计与开发",
        description="邓炳山毕业设计",
        version="0.0.1"
    )

    # ✅ 修正部分：显式指定前端的 Origin
    origins = [
        "http://localhost:5173",  # 你的前端开发地址
        "http://127.0.0.1:5173",  # 以防你用 IP 访问前端
        "http://localhost",  # 以防万一
        "http://127.0.0.1"  # 以防万一
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
    return fastapi_app


app = create_app()

dotenv.load_dotenv("..\\.env")

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=31818, workers=1, ws_ping_timeout=60, ws_ping_interval=120)
