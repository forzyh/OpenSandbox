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
Package web 提供 HTTP 路由和中间件功能。

本文件负责：
1. 创建和配置 Gin HTTP 引擎
2. 注册所有 API 路由
3. 配置中间件（认证、日志、代理等）

路由分组说明：
- /ping - 健康检查端点
- /files - 文件系统操作（上传、下载、搜索、权限管理等）
- /directories - 目录操作（创建、删除）
- /code - 代码执行相关（执行代码、创建/删除上下文、会话管理）
- /session - 交互式会话管理
- /command - 命令执行（执行、中断、查询状态）
- /metrics - 监控指标获取
*/
package web

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/alibaba/opensandbox/execd/pkg/log"      // 日志系统
	"github.com/alibaba/opensandbox/execd/pkg/web/controller" // 控制器层
	"github.com/alibaba/opensandbox/execd/pkg/web/model" // 数据模型和常量
)

// NewRouter 创建并配置 Gin 路由引擎，注册所有 execd 的 HTTP 路由。
//
// 参数 accessToken: 访问令牌，用于 API 请求的身份认证
//   - 如果为空字符串，则跳过认证检查
//   - 客户端需要在请求头中携带正确的令牌才能访问 API
//
// 返回值：配置好的 Gin 引擎实例，可直接用于启动 HTTP 服务器
//
// 路由结构：
//   1. 全局中间件：日志、认证、代理
//   2. 健康检查：GET /ping
//   3. 文件操作组：/files/*
//   4. 目录操作组：/directories/*
//   5. 代码执行组：/code/*
//   6. 会话管理组：/session/*
//   7. 命令执行组：/command/*
//   8. 监控指标组：/metrics/*
func NewRouter(accessToken string) *gin.Engine {
	// 设置 Gin 为发布模式，减少日志输出以提高性能
	// 开发时可改为 gin.DebugMode 获取更详细的日志
	gin.SetMode(gin.ReleaseMode)

	// 创建新的 Gin 引擎实例
	r := gin.New()

	// 添加 Recovery 中间件，防止 panic 导致服务崩溃
	// 当处理函数发生 panic 时，该中间件会捕获并返回 500 错误
	r.Use(gin.Recovery())

	// 注册自定义中间件
	// 1. logMiddleware: 记录请求日志
	// 2. accessTokenMiddleware: 验证访问令牌
	// 3. ProxyMiddleware: 处理代理相关逻辑
	r.Use(logMiddleware(), accessTokenMiddleware(accessToken), ProxyMiddleware())

	// 注册健康检查端点
	// GET /ping - 用于负载均衡器或容器编排系统检查服务健康状态
	r.GET("/ping", controller.PingHandler)

	// ========== 文件系统操作路由组 ==========
	// 所有路径都带有 /files 前缀
	files := r.Group("/files")
	{
		// DELETE /files - 删除文件
		// 查询参数：path (可多个)
		files.DELETE("", withFilesystem(func(c *controller.FilesystemController) { c.RemoveFiles() }))

		// GET /files/info - 获取文件元信息
		// 查询参数：path (可多个)
		files.GET("/info", withFilesystem(func(c *controller.FilesystemController) { c.GetFilesInfo() }))

		// POST /files/mv - 移动/重命名文件
		// 请求体：JSON 数组，包含源路径和目标路径
		files.POST("/mv", withFilesystem(func(c *controller.FilesystemController) { c.RenameFiles() }))

		// POST /files/permissions - 修改文件权限
		// 请求体：JSON 对象，键为文件路径，值为权限信息
		files.POST("/permissions", withFilesystem(func(c *controller.FilesystemController) { c.ChmodFiles() }))

		// GET /files/search - 搜索文件
		// 查询参数：path (搜索目录), pattern (匹配模式)
		files.GET("/search", withFilesystem(func(c *controller.FilesystemController) { c.SearchFiles() }))

		// POST /files/replace - 替换文件内容
		// 请求体：JSON 对象，包含要替换的旧内容和新内容
		files.POST("/replace", withFilesystem(func(c *controller.FilesystemController) { c.ReplaceContent() }))

		// POST /files/upload - 上传文件
		// 请求体：multipart/form-data
		files.POST("/upload", withFilesystem(func(c *controller.FilesystemController) { c.UploadFile() }))

		// GET /files/download - 下载文件
		// 查询参数：path (文件路径)
		files.GET("/download", withFilesystem(func(c *controller.FilesystemController) { c.DownloadFile() }))
	}

	// ========== 目录操作路由组 ==========
	// 所有路径都带有 /directories 前缀
	directories := r.Group("/directories")
	{
		// POST /directories - 创建目录
		// 请求体：JSON 对象，键为目录路径，值为权限信息
		directories.POST("", withFilesystem(func(c *controller.FilesystemController) { c.MakeDirs() }))

		// DELETE /directories - 删除目录
		// 查询参数：path (可多个)
		directories.DELETE("", withFilesystem(func(c *controller.FilesystemController) { c.RemoveDirs() }))
	}

	// ========== 代码执行路由组 ==========
	// 所有路径都带有 /code 前缀
	code := r.Group("/code")
	{
		// POST /code - 执行代码
		// 请求体：JSON 对象，包含代码和上下文信息
		// 响应：SSE 流式输出执行结果
		code.POST("", withCode(func(c *controller.CodeInterpretingController) { c.RunCode() }))

		// DELETE /code - 中断代码执行
		// 查询参数：id (会话 ID)
		code.DELETE("", withCode(func(c *controller.CodeInterpretingController) { c.InterruptCode() }))

		// POST /code/context - 创建代码执行上下文
		// 请求体：JSON 对象，包含语言和工作目录
		code.POST("/context", withCode(func(c *controller.CodeInterpretingController) { c.CreateContext() }))

		// GET /code/contexts - 列出所有上下文
		// 查询参数：language (可选，按语言过滤)
		code.GET("/contexts", withCode(func(c *controller.CodeInterpretingController) { c.ListContexts() }))

		// DELETE /code/contexts - 删除指定语言的所有上下文
		// 查询参数：language
		code.DELETE("/contexts", withCode(func(c *controller.CodeInterpretingController) { c.DeleteContextsByLanguage() }))

		// DELETE /code/contexts/:contextId - 删除特定上下文
		// 路径参数：contextId
		code.DELETE("/contexts/:contextId", withCode(func(c *controller.CodeInterpretingController) { c.DeleteContext() }))

		// GET /code/contexts/:contextId - 获取特定上下文信息
		// 路径参数：contextId
		code.GET("/contexts/:contextId", withCode(func(c *controller.CodeInterpretingController) { c.GetContext() }))
	}

	// ========== 会话管理路由组 ==========
	// 所有路径都带有 /session 前缀
	session := r.Group("/session")
	{
		// POST /session - 创建新会话
		// 请求体：JSON 对象（可选），可指定工作目录
		session.POST("", withCode(func(c *controller.CodeInterpretingController) { c.CreateSession() }))

		// POST /session/:sessionId/run - 在会话中执行代码
		// 路径参数：sessionId
		// 请求体：JSON 对象，包含代码和超时设置
		// 响应：SSE 流式输出
		session.POST("/:sessionId/run", withCode(func(c *controller.CodeInterpretingController) { c.RunInSession() }))

		// DELETE /session/:sessionId - 删除会话
		// 路径参数：sessionId
		session.DELETE("/:sessionId", withCode(func(c *controller.CodeInterpretingController) { c.DeleteSession() }))
	}

	// ========== 命令执行路由组 ==========
	// 所有路径都带有 /command 前缀
	command := r.Group("/command")
	{
		// POST /command - 执行命令
		// 请求体：JSON 对象，包含命令、超时、用户 ID 等
		// 响应：SSE 流式输出
		command.POST("", withCode(func(c *controller.CodeInterpretingController) { c.RunCommand() }))

		// DELETE /command - 中断命令执行
		// 查询参数：id (会话 ID)
		command.DELETE("", withCode(func(c *controller.CodeInterpretingController) { c.InterruptCommand() }))

		// GET /command/status/:id - 获取命令执行状态
		// 路径参数：id
		command.GET("/status/:id", withCode(func(c *controller.CodeInterpretingController) { c.GetCommandStatus() }))

		// GET /command/:id/logs - 获取后台命令的日志输出
		// 路径参数：id
		// 查询参数：cursor (分页游标)
		command.GET("/:id/logs", withCode(func(c *controller.CodeInterpretingController) { c.GetBackgroundCommandOutput() }))
	}

	// ========== 监控指标路由组 ==========
	// 所有路径都带有 /metrics 前缀
	metric := r.Group("/metrics")
	{
		// GET /metrics - 获取当前监控指标快照
		metric.GET("", withMetric(func(c *controller.MetricController) { c.GetMetrics() }))

		// GET /metrics/watch - 流式监听监控指标变化
		// 响应：SSE 流式输出
		metric.GET("/watch", withMetric(func(c *controller.MetricController) { c.WatchMetrics() }))
	}

	return r
}

// withFilesystem 创建文件系统控制器的包装函数。
//
// 这是一个高阶函数，接收一个操作 FilesystemController 的函数，
// 返回一个 Gin 处理器（HandlerFunc）。
//
// 工作原理：
// 1. 当请求匹配路由时，创建新的 FilesystemController 实例
// 2. 调用传入的处理函数执行具体业务逻辑
//
// 参数 fn: 接收 FilesystemController 并执行具体业务逻辑的函数
// 返回值：Gin HandlerFunc，可直接注册为路由处理器
func withFilesystem(fn func(*controller.FilesystemController)) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// 创建文件系统控制器实例
		// 控制器封装了 HTTP 上下文和业务逻辑方法
		fn(controller.NewFilesystemController(ctx))
	}
}

// withCode 创建代码解释器控制器的包装函数。
//
// 与 withFilesystem 类似，但用于代码执行相关的控制器。
//
// 参数 fn: 接收 CodeInterpretingController 并执行具体业务逻辑的函数
// 返回值：Gin HandlerFunc，可直接注册为路由处理器
func withCode(fn func(*controller.CodeInterpretingController)) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// 创建代码解释器控制器实例
		fn(controller.NewCodeInterpretingController(ctx))
	}
}

// withMetric 创建监控指标控制器的包装函数。
//
// 与 withFilesystem 类似，但用于监控指标相关的控制器。
//
// 参数 fn: 接收 MetricController 并执行具体业务逻辑的函数
// 返回值：Gin HandlerFunc，可直接注册为路由处理器
func withMetric(fn func(*controller.MetricController)) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// 创建监控指标控制器实例
		fn(controller.NewMetricController(ctx))
	}
}

// accessTokenMiddleware 创建访问令牌认证中间件。
//
// 功能：验证请求是否携带有效的访问令牌。
//
// 认证流程：
// 1. 如果配置的 token 为空，跳过认证（允许匿名访问）
// 2. 从请求头中读取 X-API-Access-Token
// 3. 比较请求令牌与配置令牌是否匹配
// 4. 不匹配则返回 401 未授权错误
//
// 参数 token: 服务端配置的有效访问令牌
// 返回值：Gin HandlerFunc 中间件
func accessTokenMiddleware(token string) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// 如果未配置访问令牌，则跳过认证，直接放行
		if token == "" {
			ctx.Next()
			return
		}

		// 从请求头中获取客户端提供的访问令牌
		// ApiAccessTokenHeader 常量值为 "X-API-Access-Token"
		requestedToken := ctx.GetHeader(model.ApiAccessTokenHeader)

		// 验证令牌：检查是否为空或是否匹配
		if requestedToken == "" || requestedToken != token {
			// 终止请求处理，返回 401 未授权状态码
			// 响应体包含错误信息，提示客户端需要提供有效的访问令牌
			ctx.AbortWithStatusJSON(http.StatusUnauthorized, map[string]any{
				"error": "Unauthorized: invalid or missing header " + model.ApiAccessTokenHeader,
			})
			return
		}

		// 认证通过，继续处理请求
		ctx.Next()
	}
}

// logMiddleware 创建请求日志中间件。
//
// 功能：记录每个 HTTP 请求的方法和 URL，用于调试和审计。
//
// 日志格式：Requested: {METHOD} - {URL}
// 例如：Requested: POST - /code
//
// 返回值：Gin HandlerFunc 中间件
func logMiddleware() gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// 记录请求方法和完整 URL
		// ctx.Request.Method: HTTP 方法（GET、POST、DELETE 等）
		// ctx.Request.URL.String(): 请求的完整 URL 路径
		log.Info("Requested: %v - %v", ctx.Request.Method, ctx.Request.URL.String())

		// 继续执行后续处理器
		ctx.Next()
	}
}
