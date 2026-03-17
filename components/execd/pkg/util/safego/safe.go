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

// Package safego 提供安全的 goroutine 启动工具
//
// 本包封装了 goroutine 的启动逻辑，添加了 panic 捕获和日志记录功能，
// 防止单个 goroutine 的 panic 导致整个程序崩溃。
//
// 主要功能：
//   - Go: 安全地启动 goroutine，自动捕获 panic
//   - InitPanicLogger: 初始化全局 panic 处理器
//
// 使用示例:
//
//	safego.Go(func() {
//	    // 即使这里发生 panic，也不会导致程序崩溃
//	    panic("something went wrong")
//	})
package safego

import (
	"context"
	"log"
	"net/http"
	"runtime"

	runtimeutil "k8s.io/apimachinery/pkg/util/runtime"
)

// InitPanicLogger 初始化全局 panic 处理器
//
// 本函数设置自定义的 panic 处理函数，当任何 goroutine 发生 panic 时：
// 1. 忽略 http.ErrAbortHandler（这是预期的行为）
// 2. 捕获栈跟踪信息（最多 64KB）
// 3. 将 panic 信息和栈跟踪记录到日志
//
// 参数:
//   - ctx: 上下文（当前未使用，保留用于未来扩展）
func InitPanicLogger(_ context.Context) {
	runtimeutil.PanicHandlers = []func(context.Context, any){
		func(_ context.Context, r any) {
			// 忽略 http.ErrAbortHandler，这是预期的行为
			if r == http.ErrAbortHandler {
				return
			}

			// 分配 64KB 缓冲区用于存储栈跟踪
			const size = 64 << 10
			stacktrace := make([]byte, size)
			stacktrace = stacktrace[:runtime.Stack(stacktrace, false)]

			// 根据 panic 值类型格式化日志
			if _, ok := r.(string); ok {
				log.Printf("Observed a panic: %s\n%s", r, stacktrace)
			} else {
				log.Printf("Observed a panic: %#v (%v)\n%s", r, r, stacktrace)
			}
		},
	}
}

// init 包初始化函数
//
// 设置 runtimeutil.ReallyCrash 为 false，使 panic 处理更加温和，
// 不会立即终止程序，而是尝试恢复。
func init() {
	runtimeutil.ReallyCrash = false
}

// Go 安全地启动一个 goroutine
//
// 本函数在后台 goroutine 中执行给定的函数，并自动捕获可能发生的 panic。
// 如果发生 panic，会调用注册的 PanicHandlers 进行处理，而不会导致程序崩溃。
//
// 参数:
//   - f: 要在后台执行的函数
//
// 使用示例:
//
//	safego.Go(func() {
//	    // 执行耗时任务
//	    result, err := doSomething()
//	    if err != nil {
//	        log.Printf("Error: %v", err)
//	    }
//	    // 即使这里发生 panic，也不会影响主程序
//	})
func Go(f func()) {
	go func() {
		// 使用 defer 捕获 panic
		defer runtimeutil.HandleCrash()

		f()
	}()
}
