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

// Package log 提供日志记录功能
//
// 本包封装了内部 logger 模块，提供结构化的日志记录功能。
// 支持多种日志级别和可配置的输出目标。
//
// 日志级别映射（兼容旧版级别）：
//   - 0/1/2: fatal (致命错误)
//   - 3: error (错误)
//   - 4: warn (警告)
//   - 5/6: info (信息，默认)
//   - 7+: debug (调试)
//
// 配置方式：
//   - 通过 EXECD_LOG_FILE 环境变量指定日志文件路径
//   - 未设置时输出到标准输出
//
// 使用示例:
//
//	log.Init(6) // 初始化日志，级别为 info
//	log.Info("服务启动成功")
//	log.Error("发生错误：%v", err)
package log

import (
	"os"

	slogger "github.com/alibaba/opensandbox/internal/logger"
)

const logFileEnvKey = "EXECD_LOG_FILE"

var current slogger.Logger

// Init 初始化单例日志器
//
// 本函数在启动时调用一次，根据指定的日志级别创建日志器实例。
// 日志级别会映射到标准的日志级别字符串。
//
// 旧版级别映射：
//   - 0/1/2: fatal
//   - 3: error
//   - 4: warn
//   - 5/6: info
//   - 7+: debug
//
// 参数:
//   - level: 日志级别（0-7+）
func Init(level int) {
	current = newLogger(mapLevel(level))
}

// mapLevel 将旧版数字级别映射为标准级别字符串
//
// 参数:
//   - level: 数字级别
//
// 返回值:
//   - string: 标准级别字符串（"fatal"、"error"、"warn"、"info"、"debug"）
func mapLevel(level int) string {
	switch {
	case level <= 2:
		return "fatal"
	case level == 3:
		return "error"
	case level == 4:
		return "warn"
	case level == 5 || level == 6:
		return "info"
	default:
		return "debug"
	}
}

// newLogger 创建新的日志器实例
//
// 本函数根据配置创建日志器，如果设置了 EXECD_LOG_FILE 环境变量，
// 则输出到指定文件，否则使用默认输出。
//
// 参数:
//   - level: 日志级别字符串
//
// 返回值:
//   - slogger.Logger: 日志器实例
func newLogger(level string) slogger.Logger {
	cfg := slogger.Config{
		Level: level,
	}
	// 检查是否配置了日志文件
	if logFile := os.Getenv(logFileEnvKey); logFile != "" {
		cfg.OutputPaths = []string{logFile}
		cfg.ErrorOutputPaths = cfg.OutputPaths
	}
	return slogger.MustNew(cfg)
}

// getLogger 获取当前日志器实例
//
// 如果 current 未初始化，则创建一个默认的 info 级别日志器。
//
// 返回值:
//   - slogger.Logger: 日志器实例
func getLogger() slogger.Logger {
	if current != nil {
		return current
	}
	l := newLogger("info")
	current = l
	return l
}

// Debug 记录调试级别日志
//
// 参数:
//   - format: 日志格式字符串
//   - args: 格式化参数
func Debug(format string, args ...any) {
	getLogger().Debugf(format, args...)
}

// Info 记录信息级别日志
//
// 参数:
//   - format: 日志格式字符串
//   - args: 格式化参数
func Info(format string, args ...any) {
	getLogger().Infof(format, args...)
}

// Warn 记录警告级别日志
//
// 参数:
//   - format: 日志格式字符串
//   - args: 格式化参数
func Warn(format string, args ...any) {
	getLogger().Warnf(format, args...)
}

// Warning 记录警告级别日志（Warn 的别名，用于兼容）
//
// 参数:
//   - format: 日志格式字符串
//   - args: 格式化参数
func Warning(format string, args ...any) {
	Warn(format, args...)
}

// Error 记录错误级别日志
//
// 参数:
//   - format: 日志格式字符串
//   - args: 格式化参数
func Error(format string, args ...any) {
	getLogger().Errorf(format, args...)
}
