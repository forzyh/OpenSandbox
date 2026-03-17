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

package runtime

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	_ "github.com/go-sql-driver/mysql"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter/execute"
	"github.com/alibaba/opensandbox/execd/pkg/log"
)

// QueryResult 表示 SQL 查询结果
//
// QueryResult 封装了 SQL 查询的响应数据，包括列名、行数据和错误信息。
// 查询结果会被序列化为 JSON 格式返回给调用者。
type QueryResult struct {
	// Columns 列名列表
	// 每个元素对应结果集的一列
	Columns []string `json:"columns,omitempty"`

	// Rows 行数据列表
	// 每个元素是一行数据，行的每个元素是一个接口类型
	Rows [][]any `json:"rows,omitempty"`

	// Error 错误信息
	// 如果查询成功，此字段为空
	Error string `json:"error,omitempty"`
}

// runSQL 根据 SQL 查询类型执行相应的处理逻辑
//
// 本方法负责 SQL 执行的初始化和路由：
// 1. 初始化数据库连接（懒加载）
// 2. 检查数据库连接状态
// 3. 根据 SQL 类型（SELECT/非 SELECT）路由到不同的执行方法
//
// 参数:
//   - ctx: 执行上下文，用于控制超时和取消
//   - request: SQL 执行请求
//
// 返回值:
//   - error: 执行错误（如有）
func (c *Controller) runSQL(ctx context.Context, request *ExecuteCodeRequest) error {
	// 调用初始化回调
	request.Hooks.OnExecuteInit(uuid.New().String())

	// 初始化数据库连接
	err := c.initDB()
	if err != nil {
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "DBInitError", EValue: err.Error()})
		log.Error("DBInitError: error initializing db server: %v", err)
		return err
	}

	// 检查数据库连接状态
	err = c.db.PingContext(ctx)
	if err != nil {
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "DBPingError", EValue: err.Error()})
		log.Error("DBPingError: error pinging db server: %v", err)
		return err
	}

	// 根据 SQL 类型路由到不同的执行方法
	switch c.getQueryType(request.Code) {
	case "SELECT":
		// SELECT 查询：返回结果集
		return c.executeSelectSQLQuery(ctx, request)
	default:
		// 非 SELECT 语句（INSERT/UPDATE/DELETE 等）：返回受影响行数
		return c.executeUpdateSQLQuery(ctx, request)
	}
}

// executeSelectSQLQuery 执行 SELECT 查询语句
//
// 本方法执行 SELECT 查询并将结果集格式化为 JSON 返回。
// 查询结果包括列名和所有行数据。
//
// 参数:
//   - ctx: 执行上下文
//   - request: SQL 执行请求
//
// 返回值:
//   - error: 执行错误（如有）
func (c *Controller) executeSelectSQLQuery(ctx context.Context, request *ExecuteCodeRequest) error {
	startAt := time.Now()

	// 执行查询
	rows, err := c.db.QueryContext(ctx, request.Code)
	if err != nil {
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "DBQueryError", EValue: err.Error()})
		return nil
	}
	defer rows.Close()

	// 获取列名
	columns, err := rows.Columns()
	if err != nil {
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "DBQueryError", EValue: err.Error()})
		return nil
	}

	// 准备存储行数据的切片
	var result [][]any
	values := make([]any, len(columns))
	scanArgs := make([]any, len(columns))
	for i := range values {
		scanArgs[i] = &values[i]
	}

	// 遍历所有行
	for rows.Next() {
		err := rows.Scan(scanArgs...)
		if err != nil {
			request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "RowScanError", EValue: err.Error()})
			return nil
		}
		row := make([]any, len(columns))
		for i, v := range values {
			if v == nil {
				row[i] = nil
			} else {
				row[i] = fmt.Sprintf("%v", v)
			}
		}
		result = append(result, row)
	}

	// 构建查询结果
	queryResult := QueryResult{
		Columns: columns,
		Rows:    result,
	}

	// 序列化为 JSON
	bytes, err := json.Marshal(queryResult)
	if err != nil {
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "JSONMarshalError", EValue: err.Error()})
		return nil
	}

	// 调用结果回调
	request.Hooks.OnExecuteResult(
		map[string]any{
			"text/plain": string(bytes),
		},
		1,
	)

	// 调用完成回调
	request.Hooks.OnExecuteComplete(time.Since(startAt))
	return nil
}

// executeUpdateSQLQuery 执行非 SELECT 语句（INSERT/UPDATE/DELETE 等）
//
// 本方法执行修改数据的 SQL 语句，并返回受影响的行数。
//
// 参数:
//   - ctx: 执行上下文
//   - request: SQL 执行请求
//
// 返回值:
//   - error: 执行错误（如有）
func (c *Controller) executeUpdateSQLQuery(ctx context.Context, request *ExecuteCodeRequest) error {
	startAt := time.Now()

	// 执行 SQL 语句
	result, err := c.db.ExecContext(ctx, request.Code)
	if err != nil {
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "DBExecError", EValue: err.Error()})
		return err
	}

	// 获取受影响行数
	affected, _ := result.RowsAffected()

	// 构建查询结果
	queryResult := QueryResult{
		Rows:    [][]any{{affected}},
		Columns: []string{"affected_rows"},
	}

	// 序列化为 JSON
	bytes, err := json.Marshal(queryResult)
	if err != nil {
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "JSONMarshalError", EValue: err.Error()})
		return err
	}

	// 调用结果回调
	request.Hooks.OnExecuteResult(
		map[string]any{
			"text/plain": string(bytes),
		},
		1,
	)

	// 调用完成回调
	request.Hooks.OnExecuteComplete(time.Since(startAt))
	return nil
}

// getQueryType 提取 SQL 语句的第一个单词来判断查询类型
//
// 本方法通过将 SQL 语句转换为大写并提取第一个单词，
// 来判断是 SELECT 查询还是其他类型的语句。
//
// 参数:
//   - query: SQL 查询字符串
//
// 返回值:
//   - string: 查询类型（如 "SELECT"、"INSERT"、"UPDATE" 等）
func (c *Controller) getQueryType(query string) string {
	// 提取第一个单词并转换为大写
	firstWord := strings.ToUpper(strings.Fields(query)[0])
	return firstWord
}

// initDB 懒加载初始化本地沙箱数据库连接
//
// 本方法使用 sync.Once 确保数据库只初始化一次。
// 初始化过程包括：
// 1. 连接到本地 MySQL 服务器（127.0.0.1:3306）
// 2. 检查连接状态
// 3. 创建 sandbox 数据库（如果不存在）
// 4. 选择 sandbox 数据库
//
// 返回值:
//   - error: 初始化错误（如有）
func (c *Controller) initDB() error {
	var initErr error
	c.dbOnce.Do(func() {
		// 数据库连接字符串
		dsn := "root:@tcp(127.0.0.1:3306)/"

		// 打开数据库连接
		db, err := sql.Open("mysql", dsn)
		if err != nil {
			initErr = err
			return
		}

		// 检查连接状态
		err = db.Ping()
		if err != nil {
			initErr = err
			return
		}

		// 创建 sandbox 数据库（如果不存在）
		_, err = db.Exec("CREATE DATABASE IF NOT EXISTS sandbox")
		if err != nil {
			initErr = err
			return
		}

		// 选择 sandbox 数据库
		_, err = db.Exec("USE sandbox")
		if err != nil {
			initErr = err
			return
		}

		c.db = db
	})

	// 检查初始化结果
	if initErr != nil {
		return initErr
	}
	if c.db == nil {
		return errors.New("db is not initialized")
	}
	return nil
}
