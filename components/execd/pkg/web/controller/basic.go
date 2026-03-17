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

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/alibaba/opensandbox/execd/pkg/web/model"
)

// basicController 基础控制器
//
// basicController 封装了 Gin 上下文的常用操作，
// 提供统一的响应格式和请求处理方法。
type basicController struct {
	// ctx Gin 上下文
	ctx *gin.Context
}

// newBasicController 创建基础控制器实例
//
// 参数:
//   - ctx: Gin 上下文
//
// 返回值:
//   - *basicController: 新创建的控制器实例
func newBasicController(ctx *gin.Context) *basicController {
	return &basicController{ctx: ctx}
}

// RespondError 返回错误响应
//
// 本方法以指定的状态码和错误码返回错误响应。
//
// 参数:
//   - status: HTTP 状态码
//   - code: 错误码
//   - message: 错误消息（可选）
func (c *basicController) RespondError(status int, code model.ErrorCode, message ...string) {
	resp := model.ErrorResponse{
		Code:    code,
		Message: "",
	}
	if len(message) > 0 {
		resp.Message = message[0]
	}
	c.ctx.JSON(status, resp)
}

// RespondSuccess 返回成功响应
//
// 本方法以 200 OK 状态码返回成功响应。
// 如果 data 为 nil，则只返回状态码不返回 body。
//
// 参数:
//   - data: 响应数据（可选）
func (c *basicController) RespondSuccess(data any) {
	if data == nil {
		c.ctx.Status(http.StatusOK)
		return
	}
	c.ctx.JSON(http.StatusOK, data)
}

// QueryInt64 解析 int64 类型的查询参数
//
// 本方法尝试将查询参数解析为 int64 类型，
// 如果解析失败则返回默认值。
//
// 参数:
//   - query: 查询参数名称
//   - defaultValue: 默认值（解析失败时返回）
//
// 返回值:
//   - int64: 解析后的值或默认值
func (c *basicController) QueryInt64(query string, defaultValue int64) int64 {
	val, err := strconv.ParseInt(query, 10, 64)
	if err != nil {
		return defaultValue
	}
	return val
}

// bindJSON 将请求体解析为 JSON 结构
//
// 本方法从请求体读取 JSON 数据并反序列化到目标结构体。
//
// 参数:
//   - target: 目标结构体指针
//
// 返回值:
//   - error: 解析错误（如有）
func (c *basicController) bindJSON(target any) error {
	decoder := json.NewDecoder(c.ctx.Request.Body)
	return decoder.Decode(target)
}
