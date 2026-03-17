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
	"bytes"
	"net/http/httptest"

	"github.com/gin-gonic/gin"
)

// newTestContext 创建测试用的 Gin 上下文
//
// 本函数用于单元测试，创建一个模拟的 HTTP 请求和响应记录器，
// 并返回配置好的 Gin 上下文。
//
// 参数:
//   - method: HTTP 方法（如 "GET"、"POST"）
//   - path: 请求路径
//   - body: 请求体内容
//
// 返回值:
//   - *gin.Context: 测试上下文
//   - *httptest.ResponseRecorder: 响应记录器
//
// nolint:unused
func newTestContext(method, path string, body []byte) (*gin.Context, *httptest.ResponseRecorder) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(w)
	req := httptest.NewRequest(method, path, bytes.NewReader(body))
	ctx.Request = req
	return ctx, w
}
