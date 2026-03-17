// Copyright 2025 Alibaba Group Holding Ltd.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Package runtime 提供代码执行运行时管理功能
//
// 本包是 execd 服务的核心运行时管理模块，负责：
//   - 管理多种语言的代码执行（Command、Bash、Python、Java、JavaScript、TypeScript、Go、SQL）
//   - 管理 Jupyter 内核会话
//   - 管理 Bash 会话（基于管道的实现）
//   - 提供上下文（会话）的创建、查询、删除功能
//   - 支持流式输出和后台执行模式
//
// 主要类型：
//   - Controller: 运行时控制器，统一管理所有执行后端
//   - ExecuteCodeRequest: 代码执行请求结构
//   - ExecuteResultHook: 执行结果回调函数集合
//   - Language: 编程语言类型枚举
package runtime

import (
	"context"
	"database/sql"
	"fmt"
	"sync"
	"time"

	"k8s.io/apimachinery/pkg/util/wait"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter"
)

// kernelWaitingBackoff 定义内核等待的重试策略
//
// 当创建 Jupyter 内核失败时，使用此退避策略进行重试：
//   - Steps: 最多重试 60 次
//   - Duration: 初始等待 500 毫秒
//   - Factor: 每次重试等待时间乘以 1.5
//   - Jitter: 添加 10% 的随机抖动，避免并发请求同步
var kernelWaitingBackoff = wait.Backoff{
	Steps:    60,
	Duration: 500 * time.Millisecond,
	Factor:   1.5,
	Jitter:   0.1,
}

// Controller 是运行时管理的核心控制器
//
// Controller 统一管理多种代码执行后端：
//   - Jupyter 内核：用于 Python、Java、JavaScript 等语言
//   - 命令执行：用于执行 shell 命令
//   - Bash 会话：用于有状态的 shell 会话
//   - SQL 执行：用于 SQL 查询
//
// 所有字段的并发访问都是安全的：
//   - mu: 保护需要互斥访问的字段
//   - sync.Map: 用于存储会话到内核的映射，支持并发读写
type Controller struct {
	// baseURL Jupyter 服务器的基础 URL
	baseURL string

	// token Jupyter 服务器的认证令牌
	token string

	// mu 互斥锁，保护需要互斥访问的字段
	mu sync.RWMutex

	// jupyterClientMap 存储会话 ID 到 Jupyter 内核的映射
	// 类型：map[sessionID]*jupyterKernel
	jupyterClientMap sync.Map

	// defaultLanguageSessions 存储每种语言的默认会话
	// 用于无状态执行模式，避免每次都创建新会话
	// 类型：map[Language]string（语言 -> 会话 ID）
	defaultLanguageSessions sync.Map

	// commandClientMap 存储会话 ID 到命令内核的映射
	// 类型：map[sessionID]*commandKernel
	commandClientMap sync.Map

	// bashSessionClientMap 存储会话 ID 到 Bash 会话的映射
	// 类型：map[sessionID]*bashSession
	bashSessionClientMap sync.Map

	// db SQL 执行使用的数据库连接
	db *sql.DB

	// dbOnce 确保数据库只初始化一次
	dbOnce sync.Once
}

// jupyterKernel 表示一个 Jupyter 内核实例
//
// jupyterKernel 封装了与 Jupyter 内核通信所需的所有信息，
// 包括内核 ID、客户端实例和语言类型。
type jupyterKernel struct {
	// mu 互斥锁，保护内核状态
	mu sync.Mutex

	// kernelID 内核的唯一标识符
	kernelID string

	// client Jupyter 客户端，用于与内核通信
	client *jupyter.Client

	// language 内核支持的语言类型
	language Language
}

// commandKernel 表示一个命令执行实例
//
// commandKernel 记录了命令执行的完整状态信息，
// 包括进程 ID、输出文件路径、执行时间、退出码等。
type commandKernel struct {
	// pid 命令进程的 ID
	pid int

	// stdoutPath 标准输出日志文件路径
	stdoutPath string

	// stderrPath 标准错误日志文件路径
	stderrPath string

	// startedAt 命令开始执行的时间
	startedAt time.Time

	// finishedAt 命令执行完成的时间（如果已完成）
	finishedAt *time.Time

	// exitCode 命令退出码（如果已完成）
	exitCode *int

	// errMsg 错误消息（如果有）
	errMsg string

	// running 命令是否正在运行
	running bool

	// isBackground 是否是后台命令
	isBackground bool

	// content 执行的命令内容
	content string
}

// NewController 创建一个新的运行时控制器
//
// 参数:
//   - baseURL: Jupyter 服务器的基础 URL
//   - token: Jupyter 服务器的认证令牌
//
// 返回值:
//   - *Controller: 新创建的控制器实例
func NewController(baseURL, token string) *Controller {
	return &Controller{
		baseURL: baseURL,
		token:   token,
	}
}

// Execute 分发代码执行请求到相应的后端
//
// 本方法根据请求的语言类型，将执行请求路由到不同的执行引擎：
//   - Command: 执行 shell 命令（同步模式）
//   - BackgroundCommand: 执行 shell 命令（后台模式）
//   - Bash/Python/Java/JavaScript/TypeScript/Go: 通过 Jupyter 内核执行
//   - SQL: 执行 SQL 查询
//
// 如果请求指定了超时时间，会创建带超时的 context。
//
// 参数:
//   - request: 代码执行请求
//
// 返回值:
//   - error: 执行错误（如有）
func (c *Controller) Execute(request *ExecuteCodeRequest) error {
	var cancel context.CancelFunc
	var ctx context.Context

	// 根据是否指定超时时间创建不同的 context
	if request.Timeout > 0 {
		ctx, cancel = context.WithTimeout(context.Background(), request.Timeout)
	} else {
		ctx, cancel = context.WithCancel(context.Background())
	}

	// 根据语言类型路由到不同的执行引擎
	switch request.Language {
	case Command:
		defer cancel()
		return c.runCommand(ctx, request)
	case BackgroundCommand:
		// 后台命令不等待完成，不立即调用 cancel
		return c.runBackgroundCommand(ctx, cancel, request)
	case Bash, Python, Java, JavaScript, TypeScript, Go:
		defer cancel()
		return c.runJupyter(ctx, request)
	case SQL:
		defer cancel()
		return c.runSQL(ctx, request)
	default:
		defer cancel()
		return fmt.Errorf("unknown language: %s", request.Language)
	}
}
