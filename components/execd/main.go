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
Package main 是 OpenSandbox execd 组件的主入口文件。

execd 是一个提供代码执行能力的后端服务，主要功能包括：
1. 代码解释器功能 - 支持多种编程语言的代码执行（通过 Jupyter 内核）
2. 命令执行功能 - 执行 shell 命令并获取输出
3. 文件系统操作 - 提供文件上传、下载、搜索、权限修改等功能
4. 会话管理 - 支持创建和管理交互式会话

实现原理：
- 使用 Gin 框架构建 HTTP API 服务
- 通过 Jupyter Kernel Gateway 实现多语言代码执行
- 使用 Go 的 exec 包执行系统命令
- 提供 SSE（Server-Sent Events）实时流式输出执行结果

启动流程：
1. 打印版本信息
2. 初始化命令行标志（flags）
3. 初始化日志系统
4. 初始化代码执行器（Controller）
5. 创建 HTTP 路由并启动服务器
*/
package main

import (
	"fmt"

	"github.com/alibaba/opensandbox/internal/version"

	_ "go.uber.org/automaxprocs/maxprocs" // 自动设置 GOMAXPROCS 以匹配容器 CPU 限制

	"github.com/alibaba/opensandbox/execd/pkg/flag"     // 命令行标志和配置
	"github.com/alibaba/opensandbox/execd/pkg/log"      // 日志系统
	_ "github.com/alibaba/opensandbox/execd/pkg/util/safego" // 安全的 goroutine 启动工具
	"github.com/alibaba/opensandbox/execd/pkg/web"      // HTTP 路由
	"github.com/alibaba/opensandbox/execd/pkg/web/controller" // HTTP 控制器
)

// main 是程序的入口函数，负责初始化并启动 execd 服务器。
//
// 执行步骤：
// 1. 打印版本信息到控制台
// 2. 初始化命令行标志（从环境变量或配置文件读取配置）
// 3. 初始化日志系统，设置日志级别
// 4. 初始化代码执行器（CodeRunner），建立与 Jupyter 内核的连接
// 5. 创建 HTTP 路由引擎，配置中间件（认证、日志等）
// 6. 监听指定端口并启动 HTTP 服务器
func main() {
	// 打印组件版本信息，用于启动时的版本确认
	version.EchoVersion("OpenSandbox Execd")

	// 初始化命令行标志，从环境变量或配置文件中读取配置参数
	// 包括服务器端口、访问令牌、Jupyter 服务器地址等
	flag.InitFlags()

	// 初始化日志系统，使用配置的日志级别
	// 日志级别控制输出详细程度（如 DEBUG、INFO、WARNING、ERROR）
	log.Init(flag.ServerLogLevel)

	// 初始化代码执行控制器
	// 该控制器负责管理与 Jupyter 内核的连接和代码执行会话
	controller.InitCodeRunner()

	// 创建 HTTP 路由引擎
	// 传入访问令牌用于后续请求的认证校验
	engine := web.NewRouter(flag.ServerAccessToken)

	// 构建监听地址，格式为 ":端口号"
	// 例如 ":8080" 表示监听所有网络接口的 8080 端口
	addr := fmt.Sprintf(":%d", flag.ServerPort)

	// 记录服务器启动日志
	log.Info("execd listening on %s", addr)

	// 启动 HTTP 服务器并监听指定地址
	// 如果启动失败（如端口被占用），记录错误日志
	if err := engine.Run(addr); err != nil {
		log.Error("failed to start execd server: %v", err)
	}
}
