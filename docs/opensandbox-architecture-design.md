# OpenSandbox 架构设计文档

## 1. 概述

OpenSandbox 是一个通用沙箱平台，为 AI 应用提供安全、隔离的执行环境。它支持多语言 SDK、统一的沙箱协议和灵活的运行时实现（Docker/Kubernetes）。

### 1.1 设计目标

- **安全性**：通过容器技术提供隔离的执行环境
- **通用性**：支持任何容器镜像作为沙箱基础
- **可扩展性**：插件式运行时架构，支持多种后端
- **易用性**：多语言 SDK，统一的 API 接口
- **可观测性**：完整的生命周期追踪和指标监控

### 1.2 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                      应用层 (Applications)                    │
├─────────────────────────────────────────────────────────────┤
│                   SDKs (Python/Java/TS/C#)                   │
├────────────────────────┬────────────────────────────────────┤
│       生命周期 API      │         执行 API (execd)            │
│    (Lifecycle API)     │      (Execution API)                │
├────────────────────────┴────────────────────────────────────┤
│                   运行时层 (Runtime Layer)                    │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │  Docker Runtime │  │ Kubernetes R.T. │                   │
│  └─────────────────┘  └─────────────────┘                   │
├─────────────────────────────────────────────────────────────┤
│                   沙箱实例层 (Sandbox Instances)              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │ execd Daemon │   │ execd Daemon │   │ execd Daemon │    │
│  │ + User Code  │   │ + User Code  │   │ + User Code  │    │
│  └──────────────┘   └──────────────┘   └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 整体架构

### 2.1 四层架构模型

OpenSandbox 采用四层架构设计：

1. **SDKs 层**：多语言客户端库，提供高级抽象
2. **Specs 层**：OpenAPI 规范定义协议
3. **Runtime 层**：服务器实现，管理沙箱生命周期
4. **Sandbox Instances 层**：运行的沙箱容器，注入执行守护进程

### 2.2 通信协议

- **生命周期 API**：管理沙箱的创建、删除、暂停、恢复
- **执行 API**：与沙箱内的 execd 通信，执行代码和命令

---

## 3. Python Server 架构设计

### 3.1 模块结构

```
server/src/
├── main.py              # FastAPI 应用入口，生命周期管理
├── config.py            # 配置加载和验证
├── api/
│   ├── lifecycle.py     # 沙箱生命周期 API 路由
│   └── schema.py        # Pydantic 数据模型定义
├── services/
│   ├── sandbox_service.py  # 沙箱服务抽象基类
│   ├── docker.py           # Docker 运行时实现
│   ├── factory.py          # 服务工厂
│   ├── helpers.py          # 辅助函数
│   ├── validators.py       # 参数验证
│   ├── runtime_resolver.py # 安全运行时解析
│   ├── ossfs_mixin.py      # OSSFS 挂载支持
│   └── k8s/                # Kubernetes 运行时
│       ├── client.py       # K8s 客户端封装
│       ├── kubernetes_service.py
│       ├── workload_provider.py
│       ├── batchsandbox_provider.py
│       ├── agent_sandbox_provider.py
│       ├── informer.py     # K8s 监听器
│       └── *.py            # 各种辅助模块
└── middleware/
    ├── auth.py             # 认证中间件
    └── request_id.py       # 请求 ID 中间件
```

### 3.2 核心模块设计

#### 3.2.1 main.py - 应用入口

**职责**：
- 初始化 FastAPI 应用
- 配置日志系统（统一格式、请求 ID 追踪）
- 注册中间件（认证、CORS、请求 ID）
- 注册路由和异常处理器
- 管理应用生命周期（lifespan）

**启动流程**：
```
1. 加载配置 (config.py)
2. 配置日志 (logging.config.dictConfig)
3. 创建 lifespan 上下文管理器
   - 启动：创建 http 客户端、验证安全运行时、创建沙箱服务
   - 关闭：关闭 http 客户端
4. 注册中间件（逆序执行）
5. 注册路由（/sandboxes, /v1/sandboxes）
6. 注册异常处理器
```

#### 3.2.2 config.py - 配置管理

**设计模式**：Pydantic Settings

**配置结构**：
```python
AppConfig:
├── server: ServerConfig       # 服务器配置（host, port, api_key）
├── runtime: RuntimeConfig     # 运行时类型（docker/kubernetes）
├── docker: DockerConfig       # Docker 配置
├── kubernetes: K8sConfig      # Kubernetes 配置
└── secure_runtime: ...        # 安全运行时配置（gVisor, Kata）
```

#### 3.2.3 api/lifecycle.py - 路由层

**端点设计**：

| 端点 | 方法 | 描述 |
|------|------|------|
| `/sandboxes` | POST | 创建沙箱 |
| `/sandboxes` | GET | 列表沙箱（支持过滤、分页） |
| `/sandboxes/{id}` | GET | 获取沙箱详情 |
| `/sandboxes/{id}` | DELETE | 删除沙箱 |
| `/sandboxes/{id}/pause` | POST | 暂停沙箱 |
| `/sandboxes/{id}/resume` | POST | 恢复沙箱 |
| `/sandboxes/{id}/renew-expiration` | POST | 续期过期时间 |
| `/sandboxes/{id}/endpoints/{port}` | GET | 获取访问端点 |
| `/sandboxes/{id}/proxy/{port}/{path}` | * | 代理请求到沙箱 |

**代理端点实现**：
- 过滤 hop-by-hop 请求头
- 过滤敏感请求头（authorization, cookie）
- 支持流式响应
- 不支持 WebSocket 升级

#### 3.2.4 services/sandbox_service.py - 服务抽象

**抽象基类设计**：

```python
class SandboxService(ABC):
    @abstractmethod
    def create_sandbox(self, request: CreateSandboxRequest) -> CreateSandboxResponse:
        pass

    @abstractmethod
    def get_sandbox(self, sandbox_id: str) -> Sandbox:
        pass

    @abstractmethod
    def list_sandboxes(self, request: ListSandboxesRequest) -> ListSandboxesResponse:
        pass

    @abstractmethod
    def delete_sandbox(self, sandbox_id: str) -> None:
        pass

    @abstractmethod
    def pause_sandbox(self, sandbox_id: str) -> None:
        pass

    @abstractmethod
    def resume_sandbox(self, sandbox_id: str) -> None:
        pass

    @abstractmethod
    def renew_expiration(self, sandbox_id: str, request: RenewSandboxExpirationRequest) -> RenewSandboxExpirationResponse:
        pass

    @abstractmethod
    def get_endpoint(self, sandbox_id: str, port: int) -> Endpoint:
        pass
```

**通用工具方法**：
- `_generate_sandbox_id()`: UUID4 生成
- `_validate_port()`: 端口验证
- `_get_host_ip()`: 主机 IP 解析

#### 3.2.5 services/docker.py - Docker 运行时实现

**核心功能**：
- 沙箱生命周期管理（创建、删除、暂停、恢复）
- 资源限制配置（CPU、内存、GPU）
- 环境变量注入
- 存储挂载（主机路径、PVC、OSSFS）
- 网络策略 sidecar 注入
- 自动过期清理（Timer 定时器）

**沙箱创建流程**：
```
1. 验证请求参数
2. 生成沙箱 ID 和过期时间
3. 准备 OSSFS 挂载（如果需要）
4. 配置卷绑定
5. 配置网络策略（启动 egress sidecar）
6. 创建并启动 Docker 容器
7. 复制 execd 工具和 bootstrap 脚本
8. 设置过期定时器
9. 返回沙箱信息
```

**并发安全**：
- `_expiration_lock`: 保护过期定时器
- `_execd_archive_lock`: 保护 execd 归档缓存
- `_pending_lock`: 保护待处理操作
- `_ossfs_mount_lock`: 保护 OSSFS 挂载引用计数

#### 3.2.6 services/k8s/ - Kubernetes 运行时

**模块结构**：

```
k8s/
├── client.py                    # K8s 客户端封装（kubeconfig 加载）
├── kubernetes_service.py        # K8s 沙箱服务实现
├── workload_provider.py         # 工作负载提供者接口
├── batchsandbox_provider.py     # BatchSandbox CRD 实现
├── agent_sandbox_provider.py    # Agent-Sandbox CRD 实现
├── informer.py                  # K8s 资源监听器
├── template_manager.py          # Pod 模板管理
├── rate_limiter.py              # 速率限制器
├── volume_helper.py             # 卷挂载辅助
├── egress_helper.py             # Egress 配置辅助
└── image_pull_secret_helper.py  # 镜像拉取密钥辅助
```

**支持的 CRD**：
- **BatchSandbox**：批量沙箱调度，支持沙箱池
- **Agent-Sandbox**：Agent 工作负载管理

---

## 4. Go execd 架构设计

### 4.1 模块结构

```
components/execd/
├── main.go                      # 程序入口
├── pkg/
│   ├── flag/                    # 命令行参数解析
│   │   ├── flags.go
│   │   └── parser.go
│   ├── log/                     # 日志系统
│   │   └── log.go
│   ├── jupyter/                 # Jupyter 内核客户端
│   │   ├── client.go            # WebSocket 客户端
│   │   ├── transport.go         # 传输层
│   │   ├── auth/                # 认证模块
│   │   ├── execute/             # 执行器
│   │   ├── kernel/              # 内核管理
│   │   └── session/             # 会话管理
│   ├── runtime/                 # 执行运行时
│   │   ├── command.go           # 命令执行
│   │   ├── bash_session.go      # Bash 会话
│   │   ├── jupyter.go           # Jupyter 运行时
│   │   ├── sql.go               # SQL 执行
│   │   ├── context.go           # 执行上下文
│   │   └── types.go             # 类型定义
│   └── web/                     # HTTP 层
│       ├── router.go            # 路由配置
│       ├── proxy.go             # 代理中间件
│       ├── controller/          # 控制器
│       │   ├── basic.go         # 基础端点
│       │   ├── ping.go          # 健康检查
│       │   ├── command.go       # 命令执行
│       │   ├── codeinterpreting.go  # 代码解释
│       │   ├── filesystem.go    # 文件系统
│       │   ├── metric.go        # 指标监控
│       │   └── sse.go           # SSE 流式输出
│       └── model/               # 数据模型
│           ├── command.go
│           ├── filesystem.go
│           └── ...
└── ...
```

### 4.2 启动流程

```
1. 解析命令行参数 (--port, --jupyter-host, --access-token)
2. 初始化日志系统
3. 启动 Jupyter Server（内部进程）
4. 创建 HTTP 路由器（Gin 引擎）
5. 注册中间件（日志、认证、代理）
6. 注册所有控制器路由
7. 启动 HTTP 服务器
```

### 4.3 核心模块设计

#### 4.3.1 Jupyter 集成

**架构**：
```
┌─────────────┐    WebSocket    ┌──────────────────┐
│  execd      │ ◄─────────────► │ Jupyter Server   │
│  - client.go│                 │ (port 54321)     │
│  - session/ │                 │ - IPython Kernel │
│  - kernel/  │                 │ - IJava Kernel   │
│             │                 │ - Other Kernels  │
└─────────────┘                 └──────────────────┘
```

**支持的 kernels**：
- Python (IPython)
- Java (IJava)
- JavaScript (IJavaScript)
- TypeScript (ITypeScript)
- Go (gophernotes)
- Bash

#### 4.3.2 命令执行 (pkg/runtime/command.go)

**同步命令执行**：
```go
func runCommand(ctx context.Context, cmd string, opts *CommandOpts) (*CommandResult, error)
```
- 实时捕获 stdout/stderr
- 支持信号转发（Ctrl+C）
- 用户权限控制（UID/GID）
- 环境变量配置

**后台命令执行**：
```go
func runBackgroundCommand(ctx context.Context, cmd string, opts *CommandOpts) (string, error)
```
- 输出重定向到文件
- 支持超时自动终止
- 进程组管理

#### 4.3.3 文件系统操作 (pkg/web/controller/filesystem.go)

**支持的操作**：
- 文件信息获取（GetFilesInfo）
- 文件删除（RemoveFiles）
- 权限修改（ChmodFiles）
- 文件重命名/移动（RenameFiles）
- 目录创建（MakeDirs）
- 目录删除（RemoveDirs）
- 文件搜索（SearchFiles，glob 模式）
- 内容替换（ReplaceContent）
- 文件上传/下载（UploadFile/DownloadFile）

**安全考虑**：
- 路径遍历攻击防护
- 权限检查
- 符号链接处理

---

## 5. Python SDK 架构设计

### 5.1 模块结构

```
sdks/sandbox/python/src/opensandbox/
├── __init__.py                  # 导出主要类
├── sandbox.py                   # Sandbox 主类
├── constants.py                 # 常量定义
├── config/
│   ├── connection.py            # 连接配置（异步）
│   └── connection_sync.py       # 连接配置（同步）
├── models/
│   ├── sandboxes.py             # 沙箱相关模型
│   ├── execd.py                 # 执行相关模型
│   ├── filesystem.py            # 文件系统模型
│   └── ...
├── adapters/                    # 服务适配器
│   ├── sandboxes_adapter.py     # 沙箱服务适配
│   ├── command_adapter.py       # 命令执行适配
│   ├── filesystem_adapter.py    # 文件系统适配
│   ├── health_adapter.py        # 健康检查适配
│   ├── metrics_adapter.py       # 指标监控适配
│   ├── factory.py               # 适配器工厂
│   └── converter/               # 模型转换器
│       ├── command_model_converter.py
│       ├── filesystem_model_converter.py
│       ├── sandbox_model_converter.py
│       ├── execution_converter.py
│       ├── metrics_model_converter.py
│       ├── exception_converter.py
│       └── response_handler.py
├── api/
│   ├── lifecycle/               # 生命周期 API 客户端
│   │   ├── client.py
│   │   ├── errors.py
│   │   └── models/
│   └── execd/                   # 执行 API 客户端
│       ├── client.py
│       ├── errors.py
│       └── models/
└── services/
    ├── command.py               # 命令执行服务
    ├── filesystem.py            # 文件系统的务
    ├── health.py                # 健康检查服务
    └── metrics.py               # 指标监控服务
```

### 5.2 核心类设计

#### 5.2.1 Sandbox 类

**职责**：
- 沙箱生命周期管理（create, kill, pause, resume）
- 组合子服务（commands, filesystem, metrics）
- 自动过期管理（renew_expiration）
- 上下文管理器支持（async with）

**使用示例**：
```python
async with Sandbox.create("ubuntu:22.04", timeout=timedelta(minutes=30)) as sandbox:
    # 执行命令
    result = await sandbox.commands.run("echo hello")
    # 文件操作
    await sandbox.files.write_files([WriteEntry(path="/tmp/test.txt", data="content")])
    # 代码解释
    interpreter = await CodeInterpreter.create(sandbox)
    result = await interpreter.codes.run("print('hello')", language=SupportedLanguage.PYTHON)
```

#### 5.2.2 适配器模式

**设计目的**：
- 解耦 SDK 与底层 API 实现
- 支持多种 API 版本
- 便于测试和模拟

**适配器结构**：
```python
class CommandAdapter:
    """命令执行服务适配器"""
    def __init__(self, api_client, converter):
        self._api_client = api_client
        self._converter = converter

    async def run(self, command, opts):
        # 1. 转换请求模型
        # 2. 调用 API
        # 3. 转换响应模型
        # 4. 返回 SDK 模型
```

---

## 6. CLI 工具架构设计

### 6.1 模块结构

```
cli/src/opensandbox_cli/
├── __init__.py
├── __main__.py                  # 入口点
├── main.py                      # Click 根命令
├── client.py                    # API 客户端封装
├── config.py                    # CLI 配置管理
├── output.py                    # 输出格式化（table/json/yaml）
├── utils.py                     # 工具函数
└── commands/
    ├── __init__.py
    ├── sandbox.py               # sandbox 命令组
    ├── command.py               # command 命令组
    ├── code.py                  # code 命令组
    ├── file.py                  # file 命令组
    └── config_cmd.py            # config 命令
```

### 6.2 命令结构

```
opensandbox
├── sandbox
│   ├── create                  # 创建沙箱
│   ├── list                    # 列表沙箱
│   ├── get                     # 获取沙箱详情
│   ├── delete                  # 删除沙箱
│   ├── pause                   # 暂停沙箱
│   ├── resume                  # 恢复沙箱
│   └── endpoint                # 获取端点
├── command
│   ├── run                     # 运行命令
│   └── exec                    # 执行命令
├── code
│   ├── run                     # 运行代码
│   └── session                 # 会话管理
├── file
│   ├── upload                  # 上传文件
│   ├── download                # 下载文件
│   ├── read                    # 读取文件
│   ├── write                   # 写入文件
│   └── search                  # 搜索文件
└── config
    ├── view                    # 查看配置
    ├── set                     # 设置配置
    └── init                    # 初始化配置
```

---

## 7. Egress 组件架构设计

### 7.1 模块结构

```
components/egress/
├── main.go                      # 入口点
├── nameserver.go                # DNS 解析
├── nft.go                       # nftables 配置
├── policy_server.go             # 策略服务器
└── pkg/
    ├── constants/               # 常量定义
    ├── dnsproxy/                # DNS 代理
    │   ├── proxy.go
    │   ├── exempt.go
    │   └── proxy_linux.go
    ├── events/                  # 事件系统
    │   ├── broadcaster.go
    │   └── webhook.go
    ├── iptables/                # iptables 重定向
    │   └── redirect.go
    ├── log/                     # 日志
    │   └── logger.go
    ├── nftables/                # nftables 管理
    │   ├── manager.go
    │   └── dynamic.go
    └── policy/                  # 策略解析
        └── policy.go
```

### 7.2 核心功能

**网络出口控制**：
- DNS 代理和解析
- nftables 规则管理
- iptables 流量重定向
- Webhook 事件通知

**工作流程**：
```
1. 加载网络策略（环境变量）
2. 配置 DNS 代理（/etc/resolv.conf）
3. 设置 nftables 规则（允许/拒绝列表）
4. 配置 iptables 重定向（沙箱流量 -> egress 代理）
5. 启动策略服务器（动态更新规则）
6. 广播事件到 Webhook
```

---

## 8. 安全设计

### 8.1 容器隔离

- **Docker 容器**：基础隔离
- **gVisor**：用户态内核，增强隔离
- **Kata Containers**：轻量级 VM 隔离
- **Firecracker**：microVM 隔离

### 8.2 网络安全

- **网络策略**：出站规则控制
- **Egress Sidecar**：流量代理和审计
- **DNS 代理**：DNS 请求过滤

### 8.3 认证授权

- **API Key 认证**：生命周期 API
- **Access Token 认证**：执行 API
- **请求 ID 追踪**：审计日志

### 8.4 资源限制

- **CPU/Memory Quota**：容器资源限制
- **超时自动清理**：防止资源泄露
- **并发限制**：防止过载

---

## 9. 关键设计模式

### 9.1 工厂模式

- **服务工厂**：`create_sandbox_service()` 根据配置创建运行时
- **适配器工厂**：`AdapterFactory` 创建服务适配器

### 9.2 适配器模式

- **沙箱服务适配器**：统一不同 API 实现
- **模型转换器**：API 模型与 SDK 模型转换

### 9.3 抽象基类

- **SandboxService**：定义沙箱服务接口
- **WorkloadProvider**：定义 K8s 工作负载提供者接口

### 9.4 混合模式 (Mixin)

- **OSSFSMixin**：提供 OSSFS 挂载能力

### 9.5 监听器模式

- **K8s Informer**：监听 K8s 资源变化
- **事件广播器**：广播网络事件

---

## 10. 通信流程

### 10.1 沙箱创建流程

```
SDK                          Server                          Docker/K8s
 │                             │                                │
 ├──── POST /sandboxes ─────► │                                │
 │                             │  1. 验证请求                    │
 │                             │  2. 生成沙箱 ID                 │
 │                             │  3. 准备存储挂载                │
 │                             │  4. 配置网络策略                │
 ├────────────────────────────►│  5. 创建容器                    │
 │                             │  6. 复制 execd                  │
 │                             │  7. 启动容器                    │
 │                             │  8. 设置过期定时器              │
 │◄──── 202 Accepted ─────────┤                                │
 │                             │                                │
 │  9. 轮询 GET /sandboxes/{id}                                │
 │◄──── 200 OK (状态：Running) ───────────────────────────────►│
```

### 10.2 代码执行流程

```
SDK                          execd                           Jupyter
 │                             │                                │
 ├──── POST /code/context ──► │                                │
 │                             │  1. 创建执行上下文              │
 │◄──── context_id ──────────┤                                │
 │                             │                                │
 ├──── POST /code ──────────► │                                │
 │                             │  2. 路由到 Jupyter 运行时        │
 │                             ├──── WebSocket execute_request ─►
 │                             │                                │ 3. 执行代码
 │                             │◄──── stream events ───────────┤
 │◄──── SSE events ──────────┤                                │
```

### 10.3 文件上传流程

```
SDK                          Server                          execd
 │                             │                                │
 ├──── POST /files/upload ──► │                                │
 │   (multipart/form-data)     │  1. 解析文件数据                │
 │                             │  2. 转发到 execd                │
 │                             ├──── POST /files/upload ──────►│
 │                             │                                │ 3. 写入文件系统
 │◄──── 200 OK ──────────────┤                                │
```

---

## 11. 扩展点

### 11.1 添加新的运行时

1. 继承 `SandboxService` 抽象类
2. 实现所有抽象方法
3. 在 `factory.py` 中注册新的运行时类型

### 11.2 添加新的执行 API

1. 在 `specs/execd-api.yaml` 中定义新端点
2. 使用 `openapi-python-client` 生成 SDK
3. 在 execd 中实现控制器
4. 更新 SDK 适配器

### 11.3 添加新的 Jupyter Kernel

1. 在沙箱镜像中安装 kernel
2. execd 自动发现可用的 kernels
3. SDK 支持新的语言类型

---

## 12. 性能优化

### 12.1 异步处理

- FastAPI 异步路由
- httpx 异步 HTTP 客户端
- asyncio 并发执行

### 12.2 流式处理

- SSE 流式输出代码执行结果
- 文件上传/下载流式传输
- 命令输出实时捕获

### 12.3 连接复用

- httpx Client 复用
- Docker 客户端单例
- K8s 客户端连接池

### 12.4 沙箱池

- BatchSandbox 沙箱池化
- 预创建沙箱减少延迟
- 批量创建提高吞吐量

---

## 13. 监控与日志

### 13.1 日志系统

- 统一日志格式（时间戳 + 请求 ID）
- 结构化日志（JSON 格式可选）
- 日志级别配置

### 13.2 指标监控

- CPU/内存使用率
- 沙箱数量统计
- 请求延迟指标
- 错误率统计

### 13.3 健康检查

- `/ping` - execd 健康检查
- `/health` - Server 健康检查
- K8s Readiness/Liveness Probes

---

## 14. 总结

OpenSandbox 采用分层架构设计，通过清晰的接口定义和模块划分，实现了高度的可扩展性和可维护性。核心设计原则包括：

- **协议优先**：所有交互通过 OpenAPI 规范定义
- **关注点分离**：SDK、Specs、Runtime、Instances 各司其职
- **可扩展性**：插件式运行时，支持自定义实现
- **安全性**：多层隔离，资源限制，网络控制
- **可观测性**：完整的日志、指标、健康检查

通过这套架构，OpenSandbox 能够为 AI 应用提供安全、高效、易用的沙箱执行环境。
