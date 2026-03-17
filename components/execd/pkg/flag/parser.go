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

package flag

import (
	"flag"
	stdlog "log"
	"os"
	"strings"
	"time"

	"github.com/alibaba/opensandbox/execd/pkg/log"
)

const (
	// jupyterHostEnv 指定 Jupyter 服务器主机地址的环境变量名
	jupyterHostEnv = "JUPYTER_HOST"

	// jupyterTokenEnv 指定 Jupyter 服务器认证令牌的环境变量名
	jupyterTokenEnv = "JUPYTER_TOKEN"

	// gracefulShutdownTimeoutEnv 指定 API 优雅关闭超时时间的环境变量名
	gracefulShutdownTimeoutEnv = "EXECD_API_GRACE_SHUTDOWN"
)

// InitFlags 初始化并解析命令行参数和环境变量配置
//
// 本函数负责设置 execd 服务的所有配置参数，处理逻辑如下：
// 1. 首先设置各参数的默认值
// 2. 从环境变量读取配置（如果环境变量已设置）
// 3. 定义命令行参数，以当前值作为默认值
// 4. 解析命令行参数（命令行参数优先级高于环境变量）
// 5. 记录最终使用的配置值
//
// 环境变量优先级 < 命令行参数优先级
//
// 如果 JUPYTER_HOST 环境变量格式不正确（不以 http:// 或 https:// 开头），
// 或者 EXECD_API_GRACE_SHUTDOWN 无法解析为有效的时间 Duration，程序将 panic。
func InitFlags() {
	// 设置默认值
	ServerPort = 44772
	ServerLogLevel = 6
	ServerAccessToken = ""
	ApiGracefulShutdownTimeout = time.Second * 1

	// 首先从环境变量读取默认值
	if jupyterFromEnv := os.Getenv(jupyterHostEnv); jupyterFromEnv != "" {
		// 验证 URL 格式必须以 http:// 或 https:// 开头
		if !strings.HasPrefix(jupyterFromEnv, "http://") && !strings.HasPrefix(jupyterFromEnv, "https://") {
			stdlog.Panic("Invalid JUPYTER_HOST format: must start with http:// or https://")
		}
		JupyterServerHost = jupyterFromEnv
	}

	// 从环境变量读取 Jupyter 认证令牌
	if jupyterTokenFromEnv := os.Getenv(jupyterTokenEnv); jupyterTokenFromEnv != "" {
		JupyterServerToken = jupyterTokenFromEnv
	}

	// 定义命令行参数，使用当前值（可能来自环境变量）作为默认值
	flag.StringVar(&JupyterServerHost, "jupyter-host", JupyterServerHost, "Jupyter server host address (e.g., http://localhost, http://192.168.1.100)")
	flag.StringVar(&JupyterServerToken, "jupyter-token", JupyterServerToken, "Jupyter server authentication token")
	flag.IntVar(&ServerPort, "port", ServerPort, "Server listening port (default: 44772)")
	flag.IntVar(&ServerLogLevel, "log-level", ServerLogLevel, "Server log level (0=LevelEmergency, 1=LevelAlert, 2=LevelCritical, 3=LevelError, 4=LevelWarning, 5=LevelNotice, 6=LevelInformational, 7=LevelDebug, default: 6)")
	flag.StringVar(&ServerAccessToken, "access-token", ServerAccessToken, "Server access token for API authentication")

	// 从环境变量读取优雅关闭超时时间并解析为 time.Duration
	if graceShutdownTimeout := os.Getenv(gracefulShutdownTimeoutEnv); graceShutdownTimeout != "" {
		duration, err := time.ParseDuration(graceShutdownTimeout)
		if err != nil {
			stdlog.Panicf("Failed to parse graceful shutdown timeout from env: %v", err)
		}
		ApiGracefulShutdownTimeout = duration
	}

	flag.DurationVar(&ApiGracefulShutdownTimeout, "graceful-shutdown-timeout", ApiGracefulShutdownTimeout, "API graceful shutdown timeout duration (default: 3s)")

	// 解析命令行参数 - 命令行参数会覆盖环境变量设置的值
	flag.Parse()

	// 记录最终使用的配置值
	log.Info("Jupyter server host is: %s", JupyterServerHost)
	log.Info("Jupyter server token is: %s", JupyterServerToken)
}
