# Meetily 部署踩坑记录

本文档记录了项目实际部署过程中遇到的各类问题和解决方案，供后续排查参考。

---

## 目录

- [1. MySQL 密码不要使用特殊字符](#1-mysql-密码不要使用特殊字符)
- [2. Docker 镜像拉取失败](#2-docker-镜像拉取失败)
- [3. apt-get update 构建卡死](#3-apt-get-update-构建卡死)
- [4. uv sync 安装的包无法被 python 找到](#4-uv-sync-安装的包无法被-python-找到)
- [5. set -e 导致循环提前退出](#5-set--e-导致循环提前退出)
- [6. config.yaml 跨行值被 grep 截断](#6-configyaml-跨行值被-grep-截断)
- [7. 前端注册请求缺少 confirmPassword 字段](#7-前端注册请求缺少-confirmpassword-字段)
- [8. Celery 容器执行了 Backend 的 entrypoint](#8-celery-容器执行了-backend-的-entrypoint)
- [9. Docker 容器中路径推算错误](#9-docker-容器中路径推算错误)
- [10. 缺少 Volume 导致文件无法持久化](#10-缺少-volume-导致文件无法持久化)
- [11. 构建镜像写入磁盘慢](#11-构建镜像写入磁盘慢)

---

## 1. MySQL 密码不要使用特殊字符

**问题**：MySQL 密码设置为 `meetily@0311&` 时，`&` 被 shell 解析为后台运行符号，`@` 在 URL 中被误解析，导致连接失败。

**错误日志**：
```
连接 MySQL 失败: Can't connect to MySQL server on '0311&@mysql'
```

**解决方案**：使用纯字母数字密码，如 `meetily2026`。修改 `.env` 后需要重建 MySQL 数据卷：

```bash
sed -i 's/MYSQL_ROOT_PASSWORD=.*/MYSQL_ROOT_PASSWORD=meetily2026/' .env
docker compose down
docker volume rm meetily-mysql-data
docker compose up -d --build
```

---

## 2. Docker 镜像拉取失败

**问题**：国内服务器从 Docker Hub 拉取镜像极慢或超时。

**解决方案**：使用代理镜像站逐条拉取后打标签：

```bash
docker pull docker.1ms.run/library/mysql:8.0
docker tag docker.1ms.run/library/mysql:8.0 mysql:8.0
# 其他镜像同理
```

---

## 3. apt-get update 构建卡死

**问题**：Docker 构建时 `apt-get update` 从 `deb.debian.org` 下载极慢（17 分钟+）。

**解决方案**：在 `backend/Dockerfile` 中替换为阿里云源：

```dockerfile
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && ...
```

---

## 4. uv sync 安装的包无法被 python 找到

**问题**：`docker-entrypoint.sh` 中执行 `python sql/init_db.py` 报 `ModuleNotFoundError: No module named 'pymysql'`。

**原因**：`uv sync` 将包安装到 `/app/.venv/`，但系统 `python` 没有指向虚拟环境。

**解决方案**：在 `backend/Dockerfile` 中添加环境变量：

```dockerfile
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
```

---

## 5. set -e 导致循环提前退出

**问题**：Python socket 连接 MySQL 失败返回非 0 时，`set -e` 使整个脚本退出，不会重试。

**解决方案**：去掉 `set -e`，改用 `&& break` 逻辑：

```bash
while [ $RETRY -lt $MAX_RETRIES ]; do
    python -c "..." && break
    RETRY=$((RETRY + 1))
    sleep 1
done
```

---

## 6. config.yaml 跨行值被 grep 截断

**问题**：`grep 'database_url' config.yaml` 只匹配到键名行，未取到下一行的 URL 值，导致 `DB_HOST` 和 `DB_PORT` 为空。

**错误日志**：
```
MySQL target: database_url::database_url:
```

**解决方案**：使用 `grep -A1` 取匹配行和下一行：

```bash
DB_URL=$(grep -A1 'database_url' /app/config.yaml | tail -1 | sed 's/.*"\(.*\)".*/\1/')
```

---

## 7. 前端注册请求缺少 confirmPassword 字段

**问题**：注册接口返回 400，后端 Pydantic 校验 `confirmPassword` 为 None。

**原因**：`LoginView.vue` 调用 `authStore.register()` 时未传 `confirmPassword`。

**解决方案**：补传字段：

```typescript
await authStore.register({
  username: registerForm.username,
  password: registerForm.password,
  confirmPassword: registerForm.confirmPassword,  // 补上
})
```

---

## 8. Celery 容器执行了 Backend 的 entrypoint

**问题**：`docker compose logs celery-worker` 显示 Uvicorn 日志，Celery 和 Backend 日志混在一起。

**原因**：Dockerfile 中 `ENTRYPOINT` 对所有容器生效，Celery 容器也执行了 `docker-entrypoint.sh`。

**解决方案**：在 `docker-compose.yml` 中为 celery-worker 覆盖 entrypoint：

```yaml
celery-worker:
  entrypoint: []
  command: celery -A task.celery_app worker --loglevel=info --concurrency=4 --pool=eventlet
```

---

## 9. Docker 容器中路径推算错误

**问题**：`knowledge_file.py`、`oss.py`、`checkpoints.py` 中通过 `__file__` + `dirname` 推算 backend 根目录，在 Docker 中路径多一层 `/app/` 前缀。

**原因**：Dockerfile 中 `COPY backend/ .` 将 `backend/` 内容扁平化到 `/app/`，导致 `backend/app/` 变成 `/app/app/`。

**解决方案**：改为自动向上查找包含 `config.yaml` 的目录：

```python
def _find_backend_dir():
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "config.yaml").exists():
            return current
        current = current.parent
    raise RuntimeError("无法定位 backend 根目录")
```

---

## 10. 缺少 Volume 导致文件无法持久化

**问题**：`knowledge_uploads` 和 `meeting_audio` 目录未挂载 Volume，文件写入容器内部，重启丢失。

**解决方案**：在 `docker-compose.yml` 中为 backend 和 celery-worker 添加共享 Volume：

```yaml
volumes:
  - knowledge_uploads_data:/app/data/knowledge_uploads
  - meeting_audio_data:/app/data/meeting_audio
```

---

## 11. 构建镜像写入磁盘慢

**问题**：首次构建时 `exporting layers` → `unpacking` 耗时 3-5 分钟。

**原因**：阿里云免费试用 ECS 使用 ESSD Entry 云盘，IOPS 较低。

**解决方案**：正常现象，后续构建有缓存，仅变更层需要写入。升级 ESSD PL1 可提速。

---

> 本文档随项目部署过程持续更新。遇到新问题时，请补充到此文档中。
