"""CORS 中间件配置（从 main.py 提取）。"""

from starlette.middleware.cors import CORSMiddleware

# 允许的 Origins
ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost",
    "http://127.0.0.1",
    "http://192.168.11.210:31818",
]


def setup_cors(app):
    """为 FastAPI 应用添加 CORS 中间件。"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
