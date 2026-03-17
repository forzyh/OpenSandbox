// Copyright 2026 Alibaba Group Holding Ltd.
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

// 日志工具包。
//
// 本文件提供全局日志函数和上下文相关的日志记录器。
package log

import (
	"context"
	"os"

	slogger "github.com/alibaba/opensandbox/internal/logger"
)

// Logger 是 egress 组件的共享日志记录器实例。
var Logger slogger.Logger = slogger.MustNew(slogger.Config{Level: "info"}).Named("opensandbox.egress")

// WithLogger 替换 egress 组件使用的全局日志记录器。
//
// 参数：
//   ctx: 上下文
//   logger: 新的日志记录器
//
// 返回：
//   原始上下文（日志记录器存储在全局变量中）
func WithLogger(ctx context.Context, logger slogger.Logger) context.Context {
	if logger != nil {
		Logger = logger
	}
	return ctx
}

// Debugf 记录调试级别日志。
func Debugf(template string, args ...any) {
	Logger.Debugf(template, args...)
}

// Infof 记录信息级别日志。
func Infof(template string, args ...any) {
	Logger.Infof(template, args...)
}

// Warnf 记录警告级别日志。
func Warnf(template string, args ...any) {
	Logger.Warnf(template, args...)
}

// Errorf 记录错误级别日志。
func Errorf(template string, args ...any) {
	Logger.Errorf(template, args...)
}

// Fatalf 记录致命错误并退出程序。
func Fatalf(template string, args ...any) {
	Logger.Errorf(template, args...)
	_ = Logger.Sync()
	os.Exit(1)
}
