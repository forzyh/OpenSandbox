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

// Language 表示编程语言或执行模式
//
// Language 类型定义了 execd 支持的所有代码执行模式：
//   - Command: 执行 shell 命令（同步，等待完成）
//   - BackgroundCommand: 执行 shell 命令（后台，不等待完成）
//   - Bash: 使用 Bash shell 执行（通过 Jupyter 内核）
//   - Python: 使用 Python 执行（通过 Jupyter 内核）
//   - Java: 使用 Java 执行（通过 Jupyter 内核）
//   - JavaScript: 使用 JavaScript 执行（通过 Jupyter 内核）
//   - TypeScript: 使用 TypeScript 执行（通过 Jupyter 内核）
//   - Go: 使用 Go 执行（通过 Jupyter 内核）
//   - SQL: 执行 SQL 查询
type Language string

const (
	// Command 表示同步 shell 命令执行模式
	// 命令会立即执行并等待完成，输出通过管道流式返回
	Command Language = "command"

	// Bash 表示 Bash shell 执行模式
	// 通过 Jupyter 内核执行 Bash 脚本
	Bash Language = "bash"

	// Python 表示 Python 执行模式
	// 通过 Jupyter 内核执行 Python 代码
	Python Language = "python"

	// Java 表示 Java 执行模式
	// 通过 Jupyter 内核执行 Java 代码（使用 IJava 内核）
	Java Language = "java"

	// JavaScript 表示 JavaScript 执行模式
	// 通过 Jupyter 内核执行 JavaScript 代码（使用 JavaScript 内核）
	JavaScript Language = "javascript"

	// TypeScript 表示 TypeScript 执行模式
	// 通过 Jupyter 内核执行 TypeScript 代码
	TypeScript Language = "typescript"

	// Go 表示 Go 执行模式
	// 通过 Jupyter 内核执行 Go 代码（使用 gophernotes 内核）
	Go Language = "go"

	// SQL 表示 SQL 执行模式
	// 直接连接 MySQL 数据库执行 SQL 查询
	SQL Language = "sql"

	// BackgroundCommand 表示后台 shell 命令执行模式
	// 命令在后台执行，立即返回，可通过会话 ID 查询状态和输出
	BackgroundCommand Language = "background-command"
)

// String 返回语言类型的字符串表示
//
// 本方法实现 fmt.Stringer 接口，使 Language 类型可以直接
// 用于 fmt.Print 等函数。
//
// 返回值:
//   - string: 语言类型的字符串表示
func (l Language) String() string {
	return string(l)
}
