# 用户鉴权体系完善 — 实现总结

> 资深开发工程师主导的双 Token 鉴权体系落地
> 日期：2026-07-08

## 一、改造目标

完善项目中未完成的用户注册、用户登录、接口鉴权和 Token 刷新四大功能，建立统一、安全的 JWT 双 Token 鉴权体系。

## 二、技术方案：双 Token 机制

| Token | 用途 | 有效期 | 载荷标识 |
|-------|------|--------|----------|
| Access Token | 接口鉴权 | 30 分钟 | `type=access` |
| Refresh Token | 刷新 Access Token | 7 天 | `type=refresh` |

两种 Token 共用同一 `SECRET_KEY` 签名，通过 `type` 声明**严格区分、互不通用**——用 refresh token 访问受保护接口或用 access token 刷新，均返回 401。

## 三、改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/utils/security.py` | **重写** | 双 Token 签发 + `decode_token` 校验，密钥改环境变量读取 |
| `backend/utils/dependencies.py` | **新建** | 统一鉴权依赖 `get_current_user`，401 处理 |
| `backend/database/models/user.py` | 更新 | `UserDao` 新增 `get_by_id` |
| `backend/database/schemas/schema.py` | 更新 | 注册/登录增加格式校验 + 新增 `RefreshTokenRequest` |
| `backend/api/schemas.py` | 更新 | `TokenData` 升级为 access+refresh 四字段 |
| `backend/api/v1/auth.py` | **重写** | 注册/登录/刷新三接口，防用户名枚举 |
| `backend/api/v1/knowledge.py` | 更新 | 4 个接口接入鉴权依赖 |
| `backend/api/v1/chat_message.py` | 更新 | 5 个 HTTP 接口 + WebSocket Token 校验 |
| `backend/api/v1/user.py` | 更新 | TTS 中继接口接入鉴权依赖 |
| `backend/.env` | 更新 | 新增 `JWT_SECRET_KEY` 等配置项 |

## 四、四大功能实现细节

### 1. 用户注册 `/api/v1/auth/register`

- **参数校验**（Schema 层，自动返回 422）：
  - 用户名：3-20 位，以字母开头，仅含字母/数字/下划线
  - 密码：6-20 位，必须同时含字母和数字
- **两次密码一致性校验**：不一致返回 400
- **重复注册检测**：用户名已存在返回 400
- **密码加密存储**：`pbkdf2_sha256` 加盐哈希（在 `UserDao.add` 内完成）
- **DB 异常兜底**：入库失败返回 500 并记录异常日志

### 2. 用户登录 `/api/v1/auth/login`

- 校验账号密码正确性（用户不存在与密码错误返回**同一提示**"用户名或密码错误"，防止用户名枚举攻击）
- 登录成功签发 **access + refresh 双 Token**
- 返回结构：`{access_token, refresh_token, token_type, expires_in}`

### 3. 接口鉴权 `get_current_user` 依赖

- 从 `Authorization: Bearer <token>` 头解析 Access Token
- 校验项：签名合法性、是否过期、`type=access`
- 失败统一返回 **401** + `WWW-Authenticate: Bearer` 头
- 已接入的受保护接口：
  - `knowledge`：upload / file_list / get_file_chunks / delete_file
  - `chat`：question / temp/question / list / add / update + WebSocket(`/ws/chat`)
  - `user`：tts/relay
- **公开接口**（无需鉴权）：`auth/register`、`auth/login`、`auth/refresh`

### 4. Token 刷新 `/api/v1/auth/refresh`

- 入参：`{refresh_token}`
- 校验 refresh token 的签名、过期、`type=refresh`
- 校验对应用户仍存在（用户被删则视为失效）
- 通过后签发**全新的双 Token**（refresh token 滚动续期）
- refresh token 过期或失效返回 401，提示重新登录

## 五、安全设计要点

1. **密钥外置**：`SECRET_KEY` 从环境变量 `JWT_SECRET_KEY` 读取，`.env` 提前加载
2. **防用户名枚举**：登录失败不区分"用户不存在"与"密码错误"
3. **Token 类型隔离**：access/refresh 互不可混用
4. **密码哈希**：`pbkdf2_sha256` 加盐，不可逆
5. **WebSocket 鉴权**：通过 query 参数传 token，自定义关闭码 4401 表示认证失败

## 六、验证结果

| 验证项 | 结果 |
|--------|------|
| 9 个文件语法编译 | 全部通过 |
| 模块导入与符号引用 | 全部通过 |
| Token 类型互斥校验 | refresh 当 access → 401 ✓ / access 当 refresh → 401 ✓ |
| Schema 校验（14 用例） | 14/14 全部通过 |
| FastAPI 应用构建 | 24 条路由注册成功，含新增 `/auth/refresh` |

## 七、前端对接说明

前端登录后需保存返回的 `access_token` 与 `refresh_token`：

- **请求受保护接口**：添加请求头 `Authorization: Bearer <access_token>`
- **access_token 过期（401）**：调用 `/api/v1/auth/refresh` 用 refresh_token 换取新 token，原请求重试
- **refresh_token 也过期（401）**：跳转登录页重新登录
- **WebSocket 连接**：`ws://host/api/v1/chat/ws/chat?task_id=xxx&token=<access_token>`，认证失败收到关闭码 4401
