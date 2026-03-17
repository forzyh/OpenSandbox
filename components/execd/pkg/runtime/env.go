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
	"fmt"
	"os"
	"strings"

	"github.com/alibaba/opensandbox/execd/pkg/log"
)

// loadExtraEnvFromFile 从 EXECD_ENVS 环境变量指定的文件中读取额外的键值对
//
// 本函数读取由 EXECD_ENVS 环境变量指定的文件，解析其中的键值对作为额外环境变量。
// 文件格式：
//   - 每行一个键值对，格式为 KEY=VALUE
//   - 空行被忽略
//   - 以 # 开头的行被视为注释被忽略
//   - VALUE 中可以使用 ${VAR} 或 $VAR 引用其他环境变量
//
// 返回值:
//   - map[string]string: 解析后的环境变量映射
//   - 如果 EXECD_ENVS 未设置或读取失败，返回 nil
func loadExtraEnvFromFile() map[string]string {
	// 获取环境变量指定的文件路径
	path := os.Getenv("EXECD_ENVS")
	if path == "" {
		return nil
	}

	// 读取文件内容
	data, err := os.ReadFile(path)
	if err != nil {
		log.Warn("EXECD_ENVS: failed to read file %s: %v", path, err)
		return nil
	}

	// 解析环境变量
	envs := make(map[string]string)
	lines := strings.Split(string(data), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		// 跳过空行和注释行
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		// 分割键值对
		kv := strings.SplitN(line, "=", 2)
		if len(kv) != 2 {
			log.Warn("EXECD_ENVS: skip malformed line: %s", line)
			continue
		}
		// 展开 VALUE 中的环境变量引用
		envs[kv[0]] = os.ExpandEnv(kv[1])
	}

	return envs
}

// mergeEnvs 将额外的环境变量合并到基础环境列表中
//
// 本函数将 extra 映射中的键值对合并到 base 列表中。
// 如果 extra 中的键与 base 中的键冲突，extra 的值会覆盖 base 的值。
//
// 参数:
//   - base: 基础环境列表，格式为 ["KEY1=VALUE1", "KEY2=VALUE2", ...]
//   - extra: 额外的环境变量映射
//
// 返回值:
//   - []string: 合并后的环境列表
func mergeEnvs(base []string, extra map[string]string) []string {
	// 如果没有额外的环境变量，直接返回基础环境
	if len(extra) == 0 {
		return base
	}

	// 创建映射存储合并后的环境变量
	merged := make(map[string]string, len(base)+len(extra))

	// 先将基础环境转换为映射
	for _, kv := range base {
		pair := strings.SplitN(kv, "=", 2)
		if len(pair) == 2 {
			merged[pair[0]] = pair[1]
		}
	}

	// 合并额外的环境变量（会覆盖冲突的键）
	for k, v := range extra {
		merged[k] = v
	}

	// 将映射转换回列表格式
	out := make([]string, 0, len(merged))
	for k, v := range merged {
		out = append(out, fmt.Sprintf("%s=%s", k, v))
	}

	return out
}

// mergeExtraEnvs 合并来自文件和请求级别的环境变量
//
// 本函数将两个环境变量映射合并，fromRequest 中的值会覆盖 fromFile 中的同名键。
//
// 参数:
//   - fromFile: 从文件读取的环境变量
//   - fromRequest: 从请求中指定的环境变量
//
// 返回值:
//   - map[string]string: 合并后的环境变量映射
func mergeExtraEnvs(fromFile, fromRequest map[string]string) map[string]string {
	// 如果请求中没有额外的环境变量，直接返回文件中的环境变量
	if len(fromRequest) == 0 {
		return fromFile
	}

	// 创建合并后的映射
	merged := make(map[string]string, len(fromFile)+len(fromRequest))

	// 先复制文件中的环境变量
	for k, v := range fromFile {
		merged[k] = v
	}

	// 再合并请求中的环境变量（会覆盖同名的键）
	for k, v := range fromRequest {
		merged[k] = v
	}

	return merged
}
