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

/*
Package controller 提供 HTTP 控制器层，处理具体的业务逻辑。

本文件（codeinterpreting.go）负责代码解释器相关的所有功能：

1. 代码执行上下文管理
   - 创建上下文（CreateContext）
   - 获取上下文（GetContext）
   - 列出上下文（ListContexts）
   - 删除上下文（DeleteContext, DeleteContextsByLanguage）

2. 代码执行
   - 执行代码（RunCode）
   - 中断执行（InterruptCode）

3. 会话管理
   - 创建会话（CreateSession）
   - 在会话中执行（RunInSession）
   - 删除会话（DeleteSession）

4. 命令执行
   - 执行命令（RunCommand）
   - 中断命令（InterruptCommand）
   - 获取状态（GetCommandStatus）
   - 获取后台命令输出（GetBackgroundCommandOutput）

实现原理：
- 使用全局 codeRunner（runtime.Controller）与底层运行时交互
- 通过 Jupyter Kernel 执行多语言代码
- 使用 SSE（Server-Sent Events）流式输出执行结果
*/
package controller

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/alibaba/opensandbox/execd/pkg/flag"     // 配置标志
	"github.com/alibaba/opensandbox/execd/pkg/runtime" // 代码执行运行时
	"github.com/alibaba/opensandbox/execd/pkg/web/model" // 数据模型
)

// codeRunner 全局代码执行控制器实例。
// 这是一个单例，在应用启动时初始化，所有控制器共享使用。
// 它负责管理与 Jupyter 内核的连接、执行代码、管理会话等。
var codeRunner *runtime.Controller

// InitCodeRunner 初始化全局代码执行控制器。
//
// 此函数在 main.go 的 main() 函数中被调用，负责创建并初始化
// codeRunner 实例，建立与 Jupyter Kernel Gateway 的连接。
//
// 参数来源：
//   - flag.JupyterServerHost: Jupyter 服务器地址（如 http://localhost:8888）
//   - flag.JupyterServerToken: Jupyter 服务器认证令牌
//
// 注意：此函数必须在处理任何请求之前调用，否则 codeRunner 将为 nil。
func InitCodeRunner() {
	codeRunner = runtime.NewController(flag.JupyterServerHost, flag.JupyterServerToken)
}

// CodeInterpretingController 代码解释器控制器，处理所有代码执行相关的 HTTP 请求。
//
// 该控制器提供以下功能：
//   - 代码执行上下文的生命周期管理
//   - 代码执行和结果流式输出
//   - Bash 会话管理
//   - 系统命令执行
//
// 结构体字段：
//   - basicController: 基础控制器，提供通用的 HTTP 处理方法
//   - chunkWriter: 互斥锁，用于序列化 SSE 事件写入，防止多个 goroutine 同时写入导致输出混乱
type CodeInterpretingController struct {
	*basicController

	// chunkWriter 用于序列化 SSE 事件写入的互斥锁。
	// 由于代码执行结果可能来自多个 goroutine（如 stdout、stderr、状态更新等），
	// 需要使用锁来保证写入响应流的原子性，避免输出内容交错混乱。
	chunkWriter sync.Mutex
}

// NewCodeInterpretingController 创建新的代码解释器控制器实例。
//
// 参数 ctx: Gin HTTP 上下文，包含请求和响应信息
// 返回值：初始化好的控制器实例，可直接调用其方法处理请求
func NewCodeInterpretingController(ctx *gin.Context) *CodeInterpretingController {
	return &CodeInterpretingController{
		basicController: newBasicController(ctx),
	}
}

// CreateContext 创建新的代码执行上下文。
//
// 上下文（Context）是代码执行的环境，包含：
//   - 编程语言（如 python、bash 等）
//   - 工作目录
//   - 相关的 Jupyter Kernel 会话
//
// 请求体格式（JSON）：
//   {
//     "language": "python",  // 编程语言
//     "cwd": "/path/to/dir"  // 工作目录（可选）
//   }
//
// 响应格式（JSON）：
//   {
//     "id": "context-xxx",   // 上下文唯一标识
//     "language": "python",
//     "cwd": "/path/to/dir"
//   }
func (c *CodeInterpretingController) CreateContext() {
	// 定义请求结构体变量
	var request model.CodeContextRequest

	// 从 HTTP 请求体中解析 JSON 数据
	// bindJSON 是基础控制器提供的方法，自动处理 JSON 解析错误
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	// 调用运行时层创建上下文
	// 将 HTTP 层的请求转换为运行时层的数据结构
	session, err := codeRunner.CreateContext(&runtime.CreateContextRequest{
		Language: runtime.Language(request.Language), // 转换为运行时语言类型
		Cwd:      request.Cwd,                        // 工作目录
	})
	if err != nil {
		// 创建失败，返回 500 错误
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error creating code context. %v", err),
		)
		return
	}

	// 构建响应对象，包含上下文 ID 和原始请求参数
	resp := model.CodeContext{
		ID:                 session,                            // 新生成的上下文 ID
		CodeContextRequest: request,                            // 回显请求参数
	}
	c.RespondSuccess(resp) // 返回 200 成功响应
}

// InterruptCode 中断正在执行的代码。
//
// 当用户需要停止长时间运行的代码时，调用此接口。
// 底层会向 Jupyter Kernel 发送中断信号。
//
// 查询参数：
//   - id: 要中断的会话 ID
func (c *CodeInterpretingController) InterruptCode() {
	// 委托给内部 interrupt() 方法处理
	c.interrupt()
}

// RunCode 在上下文中执行代码，并通过 SSE 流式输出结果。
//
// 这是代码执行的核心接口，支持：
//   - 多种编程语言（通过 Jupyter 内核）
//   - 实时输出（stdout、stderr、状态更新）
//   - 执行超时控制
//   - 错误处理和堆栈追踪
//
// 请求体格式（JSON）：
//   {
//     "code": "print('hello')",  // 要执行的代码
//     "context": {
//       "id": "context-xxx",     // 上下文 ID
//       "language": "python"
//     },
//     "timeoutMs": 30000         // 超时时间（毫秒）
//   }
//
// 响应：SSE（Server-Sent Events）流
//   - 事件类型：stdout, stderr, status, complete, error
func (c *CodeInterpretingController) RunCode() {
	// 定义请求结构体变量
	var request model.RunCodeRequest

	// 解析请求体 JSON
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	// 验证请求参数的合法性
	// 如检查代码是否为空、超时时间是否合理等
	err := request.Validate()
	if err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("invalid request, validation error %v", err),
		)
		return
	}

	// 创建可取消的上下文
	// 用于在客户端断开连接或超时时取消代码执行
	ctx, cancel := context.WithCancel(c.ctx.Request.Context())
	defer cancel() // 确保函数返回时释放资源

	// 构建运行时执行请求
	runCodeRequest := c.buildExecuteCodeRequest(request)

	// 设置服务器端事件处理器
	// 该处理器负责将执行结果通过 SSE 发送给客户端
	eventsHandler := c.setServerEventsHandler(ctx)
	runCodeRequest.Hooks = eventsHandler

	// 配置 SSE 响应头
	// 设置 Content-Type 为 text/event-stream，启用流式传输
	c.setupSSEResponse()

	// 执行代码
	// codeRunner 会调用底层 Jupyter 内核或命令执行器
	err = codeRunner.Execute(runCodeRequest)
	if err != nil {
		// 执行失败，返回 500 错误
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error running codes %v", err),
		)
		return
	}

	// 等待一小段时间，确保所有 SSE 事件都已发送完成
	// 这是优雅关闭的需要，避免客户端丢失最后的输出
	time.Sleep(flag.ApiGracefulShutdownTimeout)
}

// GetContext 根据 ID 获取代码执行上下文的详细信息。
//
// 路径参数：
//   - contextId: 上下文的唯一标识
//
// 响应：上下文的完整信息，包括语言、工作目录、创建时间等
func (c *CodeInterpretingController) GetContext() {
	// 从路径参数中获取上下文 ID
	contextID := c.ctx.Param("contextId")

	// 验证参数是否为空
	if contextID == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing path parameter 'contextId'",
		)
		return
	}

	// 调用运行时层获取上下文
	codeContext, err := codeRunner.GetContext(contextID)
	if err != nil {
		// 区分错误类型：上下文不存在 vs 其他错误
		if errors.Is(err, runtime.ErrContextNotFound) {
			// 上下文不存在，返回 404
			c.RespondError(
				http.StatusNotFound,
				model.ErrorCodeContextNotFound,
				fmt.Sprintf("context %s not found", contextID),
			)
			return
		}
		// 其他错误，返回 500
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error getting code context %s. %v", contextID, err),
		)
		return
	}
	// 返回上下文信息
	c.RespondSuccess(codeContext)
}

// ListContexts 列出所有活动的代码执行上下文。
//
// 支持按语言过滤：
//   - 查询参数 language: 可选，只返回指定语言的上下文
//
// 响应：上下文列表
func (c *CodeInterpretingController) ListContexts() {
	// 获取可选的语言过滤参数
	language := c.ctx.Query("language")

	// 调用运行时层获取上下文列表
	contexts, err := codeRunner.ListContext(language)
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			err.Error(),
		)
		return
	}

	c.RespondSuccess(contexts)
}

// DeleteContextsByLanguage 删除指定语言的所有上下文。
//
// 这是一个批量删除操作，用于清理特定语言的所有执行环境。
//
// 查询参数：
//   - language: 要删除的编程语言（如 python、bash）
func (c *CodeInterpretingController) DeleteContextsByLanguage() {
	// 获取语言参数
	language := c.ctx.Query("language")

	// 验证参数是否为空
	if language == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing query parameter 'language'",
		)
		return
	}

	// 调用运行时层删除指定语言的所有上下文
	err := codeRunner.DeleteLanguageContext(runtime.Language(language))
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error deleting code context %s. %v", language, err),
		)
		return
	}

	c.RespondSuccess(nil)
}

// DeleteContext 删除指定的代码执行上下文。
//
// 删除上下文会释放相关资源，包括：
//   - Jupyter Kernel 会话
//   - 内存中的状态
//   - 临时文件等
//
// 路径参数：
//   - contextId: 要删除的上下文 ID
func (c *CodeInterpretingController) DeleteContext() {
	// 从路径参数获取上下文 ID
	contextID := c.ctx.Param("contextId")

	// 验证参数是否为空
	if contextID == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing path parameter 'contextId'",
		)
		return
	}

	// 调用运行时层删除上下文
	err := codeRunner.DeleteContext(contextID)
	if err != nil {
		// 区分错误类型处理
		if errors.Is(err, runtime.ErrContextNotFound) {
			// 上下文不存在，返回 404
			c.RespondError(
				http.StatusNotFound,
				model.ErrorCodeContextNotFound,
				fmt.Sprintf("context %s not found", contextID),
			)
			return
		} else {
			// 其他错误，返回 500
			c.RespondError(
				http.StatusInternalServerError,
				model.ErrorCodeRuntimeError,
				fmt.Sprintf("error deleting code context %s. %v", contextID, err),
			)
			return
		}
	}

	c.RespondSuccess(nil)
}

// CreateSession 创建新的 bash 会话。
//
// 会话（Session）是持久的交互式环境，支持：
//   - 多次命令执行
//   - 状态保持（变量、目录等）
//   - 类似于 SSH 的交互式体验
//
// 请求体格式（JSON，可选）：
//   {
//     "cwd": "/path/to/dir"  // 工作目录（可选）
//   }
//
// 空请求体使用默认配置。
//
// 响应：
//   {
//     "sessionId": "session-xxx"
//   }
func (c *CodeInterpretingController) CreateSession() {
	var request model.CreateSessionRequest

	// 解析请求体
	// 注意：允许 EOF 错误，因为空请求体是合法的
	if err := c.bindJSON(&request); err != nil && !errors.Is(err, io.EOF) {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request. %v", err),
		)
		return
	}

	// 创建 bash 会话
	sessionID, err := codeRunner.CreateBashSession(&runtime.CreateContextRequest{
		Cwd: request.Cwd,
	})
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error creating session. %v", err),
		)
		return
	}

	c.RespondSuccess(model.CreateSessionResponse{SessionID: sessionID})
}

// RunInSession 在现有 bash 会话中执行代码，并流式输出结果。
//
// 与会话无关的 RunCode 不同，此方法：
//   - 保持会话状态（变量、当前目录等）
//   - 支持交互式命令
//   - 多次调用共享同一环境
//
// 路径参数：
//   - sessionId: 会话 ID
//
// 请求体格式（JSON）：
//   {
//     "code": "echo hello",  // 要执行的命令
//     "cwd": "/path",        // 工作目录（可选，覆盖会话默认值）
//     "timeoutMs": 30000     // 超时时间
//   }
//
// 响应：SSE 流式输出
func (c *CodeInterpretingController) RunInSession() {
	// 获取会话 ID
	sessionID := c.ctx.Param("sessionId")

	// 验证参数
	if sessionID == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing path parameter 'sessionId'",
		)
		return
	}

	var request model.RunInSessionRequest

	// 解析请求体
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request. %v", err),
		)
		return
	}

	// 验证请求参数
	if err := request.Validate(); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("invalid request. %v", err),
		)
		return
	}

	// 转换超时时间为 time.Duration
	timeout := time.Duration(request.TimeoutMs) * time.Millisecond

	// 构建运行时执行请求
	runReq := &runtime.ExecuteCodeRequest{
		Language: runtime.Bash,       // 固定使用 bash
		Context:  sessionID,          // 指定会话 ID
		Code:     request.Code,       // 要执行的代码
		Cwd:      request.Cwd,        // 工作目录
		Timeout:  timeout,            // 超时设置
	}

	// 创建可取消上下文
	ctx, cancel := context.WithCancel(c.ctx.Request.Context())
	defer cancel()

	// 设置事件处理器
	runReq.Hooks = c.setServerEventsHandler(ctx)

	// 配置 SSE 响应
	c.setupSSEResponse()

	// 在会话中执行
	err := codeRunner.RunInBashSession(ctx, runReq)
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error running in session. %v", err),
		)
		return
	}

	// 优雅关闭等待
	time.Sleep(flag.ApiGracefulShutdownTimeout)
}

// DeleteSession 删除 bash 会话。
//
// 删除会话会释放所有相关资源，之后无法再使用该会话执行命令。
//
// 路径参数：
//   - sessionId: 要删除的会话 ID
func (c *CodeInterpretingController) DeleteSession() {
	sessionID := c.ctx.Param("sessionId")

	if sessionID == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing path parameter 'sessionId'",
		)
		return
	}

	err := codeRunner.DeleteBashSession(sessionID)
	if err != nil {
		if errors.Is(err, runtime.ErrContextNotFound) {
			c.RespondError(
				http.StatusNotFound,
				model.ErrorCodeContextNotFound,
				fmt.Sprintf("session %s not found", sessionID),
			)
			return
		}
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error deleting session %s. %v", sessionID, err),
		)
		return
	}

	c.RespondSuccess(nil)
}

// buildExecuteCodeRequest 将 HTTP 层的 RunCodeRequest 转换为运行时层的 ExecuteCodeRequest。
//
// 这是一个内部辅助方法，负责：
//   - 数据类型转换
//   - 默认值设置（如语言为空时默认为 Command）
//
// 参数 request: HTTP 层请求对象
// 返回值：运行时层请求对象
func (c *CodeInterpretingController) buildExecuteCodeRequest(request model.RunCodeRequest) *runtime.ExecuteCodeRequest {
	req := &runtime.ExecuteCodeRequest{
		Language: runtime.Language(request.Context.Language), // 转换语言类型
		Code:     request.Code,                               // 代码内容
		Context:  request.Context.ID,                         // 上下文 ID
	}

	// 如果语言为空，默认为 Command 类型
	// Command 表示执行 shell 命令而非编程语言代码
	if req.Language == "" {
		req.Language = runtime.Command
	}

	return req
}

// interrupt 中断代码/命令执行的内部实现。
//
// 这是一个通用方法，被 InterruptCode 和 InterruptCommand 共享使用。
//
// 查询参数：
//   - id: 要中断的会话 ID
func (c *CodeInterpretingController) interrupt() {
	// 获取会话 ID
	session := c.ctx.Query("id")

	// 验证参数
	if session == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing query parameter 'id'",
		)
		return
	}

	// 调用运行时层中断执行
	err := codeRunner.Interrupt(session)
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error interruptting code context. %v", err),
		)
		return
	}

	c.RespondSuccess(nil)
}
