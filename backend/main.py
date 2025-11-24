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

    fastapi_app.include_router(router)
    return fastapi_app


app = create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许的源，可以设置为具体的前端地址，比如["http://localhost:5500"]，使用"*"允许所有源
    allow_credentials=True,
    allow_methods=["*"],  # 允许的HTTP方法
    allow_headers=["*"],  # 允许的HTTP头
)

dotenv.load_dotenv("..\.env")

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=31818, workers=1, ws_ping_timeout=60, ws_ping_interval=120)
