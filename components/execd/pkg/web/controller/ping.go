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

package controller

import "github.com/gin-gonic/gin"

// MainController 主控制器，处理基本的服务器操作
//
// MainController 封装了基础控制器功能，
// 提供服务器健康检查等基础 API。
type MainController struct {
	// basicController 基础控制器嵌入
	*basicController
}

// NewMainController 创建主控制器实例
//
// 参数:
//   - ctx: Gin 上下文
//
// 返回值:
//   - *MainController: 新创建的控制器实例
func NewMainController(ctx *gin.Context) *MainController {
	return &MainController{basicController: newBasicController(ctx)}
}

// Ping 检查服务器是否存活
//
// 本方法用于健康检查，返回空的成功响应。
// 客户端可以通过此 API 确认服务器是否正常运行。
func (c *MainController) Ping() {
	c.RespondSuccess(nil)
}

// PingHandler Ping 接口的 Gin 处理器
//
// 本函数是 Ping 方法的 Gin 适配器，
// 用于注册到 Gin 路由。
//
// 参数:
//   - ctx: Gin 上下文
func PingHandler(ctx *gin.Context) {
	NewMainController(ctx).Ping()
}
