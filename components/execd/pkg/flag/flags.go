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

// Package flag 定义了 execd 服务的全局配置参数
//
// 本包包含所有可通过命令行参数或环境变量配置的服务参数，
// 包括 Jupyter 服务器配置、服务器端口、日志级别、访问令牌等。
// 这些参数在服务启动时通过 InitFlags() 函数初始化。
package flag

import "time"

var (
	// JupyterServerHost 指定目标 Jupyter 服务器的主机地址
	// 用于 execd 与 Jupyter 内核管理器通信，格式应为 http:// 或 https:// 开头的完整 URL
	// 例如：http://localhost 或 http://192.168.1.100
	// 可通过 -jupyter-host 命令行参数或 JUPYTER_HOST 环境变量设置
	JupyterServerHost string

	// JupyterServerToken 用于认证请求到 Jupyter 服务器的令牌
	// 当 Jupyter 服务器启用 token 认证时，此 token 会附加到所有 API 请求中
	// 可通过 -jupyter-token 命令行参数或 JUPYTER_TOKEN 环境变量设置
	JupyterServerToken string

	// ServerPort 控制 execd HTTP 服务器的监听端口
	// 默认值为 44772
	// 可通过 -port 命令行参数设置
	ServerPort int

	// ServerLogLevel 控制服务器日志的详细程度
	// 取值范围 0-7：
	//   0 = LevelEmergency (紧急)
	//   1 = LevelAlert (警报)
	//   2 = LevelCritical (严重)
	//   3 = LevelError (错误)
	//   4 = LevelWarning (警告)
	//   5 = LevelNotice (通知)
	//   6 = LevelInformational (信息，默认值)
	//   7 = LevelDebug (调试)
	// 可通过 -log-level 命令行参数设置
	ServerLogLevel int

	// ServerAccessToken 用于保护 API 入口的访问令牌
	// 当设置此令牌后，所有 API 请求需要在 Header 中提供相应的认证信息
	// 为空时禁用访问令牌认证
	// 可通过 -access-token 命令行参数设置
	ServerAccessToken string

	// ApiGracefulShutdownTimeout 指定服务器优雅关闭时等待 SSE 流结束的超时时间
	// 在收到关闭信号后，服务器会等待此时间段让正在进行的 SSE 连接完成
	// 默认值为 1 秒
	// 可通过 -graceful-shutdown-timeout 命令行参数或 EXECD_API_GRACE_SHUTDOWN 环境变量设置
	ApiGracefulShutdownTimeout time.Duration
)
