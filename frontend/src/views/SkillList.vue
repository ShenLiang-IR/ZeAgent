<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">Skill 管理</span>
      <div>
        <el-button @click="reloadSkills">重新加载</el-button>
        <el-button type="primary" @click="showCreate">新增 Skill</el-button>
        <el-button @click="activeTab === 'db' ? loadData() : loadLocalSkills()">刷新</el-button>
      </div>
    </div>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <el-tab-pane label="数据库技能" name="db">
        <el-table :data="list" v-loading="loading" border stripe>
          <el-table-column prop="skill_name" label="名称" width="180" />
          <el-table-column prop="skill_desc" label="描述" show-overflow-tooltip />
          <el-table-column prop="category" label="分类" width="120">
            <template #default="{ row }">
              <el-tag size="small">{{ row.category || 'general' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="skill_id" label="Skill ID" width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'">
                {{ row.enabled ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可见性" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="visTag(row).type" size="small">{{ visTag(row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="工作空间" width="100">
            <template #default="{ row }">{{ workspaceName(row.workspace_id) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="280">
            <template #default="{ row }">
              <el-button size="small" @click="showDetail(row)">详情</el-button>
              <el-button size="small" @click="showEdit(row)">编辑</el-button>
              <el-button size="small" :type="row.enabled ? 'warning' : 'success'" @click="toggleEnabled(row)">
                {{ row.enabled ? '停用' : '启用' }}
              </el-button>
              <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="本地技能（skills/ 目录）" name="local">
        <el-alert title="以下技能来自 skills/ 目录下的 SKILL.md 文件，点击「导入」可将技能元数据写入数据库进行管理。" type="info" :closable="false" style="margin-bottom: 12px" />
        <el-table :data="localSkills" v-loading="localLoading" border stripe>
          <el-table-column prop="name" label="名称" width="180" />
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
          <el-table-column prop="category" label="分类" width="120">
            <template #default="{ row }">
              <el-tag size="small">{{ row.category || 'general' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'">
                {{ row.enabled ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="80">
            <template #default>
              <el-tag type="warning" size="small">磁盘</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="importLocal(row)">导入</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="formVisible" :title="isEdit ? '编辑 Skill' : '新增 Skill'" width="800px">
      <el-form :model="form" label-width="120px">
        <el-divider content-position="left">基本信息</el-divider>
        <el-form-item label="Skill ID" v-if="!isEdit">
          <el-input v-model="form.skill_id" placeholder="唯一标识，如 my-skill" />
        </el-form-item>
        <el-form-item label="Skill ID" v-else>
          <el-input :model-value="form.skill_id" disabled />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.skill_name" placeholder="显示名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.skill_desc" type="textarea" :rows="2" placeholder="Skill 描述" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" style="width: 200px;" allow-create filterable>
            <el-option
              v-for="cat in categories"
              :key="cat.value"
              :label="cat.label"
              :value="cat.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="可见性">
          <el-select v-model="form.visibility" style="width: 200px">
            <el-option label="个人（仅自己可见）" value="private" />
            <el-option label="空间（本空间成员可见）" value="workspace" />
            <el-option label="全局（全系统可见可调度）" value="public" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">执行配置（代码型 Skill）</el-divider>
        <el-form-item label="模块路径">
          <el-input v-model="form.module_path" placeholder="Python 模块路径，如 tools.my_skill" />
        </el-form-item>
        <el-form-item label="类名">
          <el-input v-model="form.class_name" placeholder="要实例化的类名，如 MySkill" />
        </el-form-item>
        <el-form-item label="函数名">
          <el-input v-model="form.function_name" placeholder="要调用的函数名（与类名二选一）" />
        </el-form-item>
        <el-form-item label="延迟加载">
          <el-switch v-model="form.lazy_load" />
        </el-form-item>
        <el-form-item label="预加载优先级">
          <el-input-number v-model="form.preload_priority" :min="0" :max="99" />
        </el-form-item>

        <el-divider content-position="left">输入参数</el-divider>
        <el-form-item label="参数列表">
          <el-table :data="form.parameters" border size="small" style="width: 100%">
            <el-table-column label="参数名" width="140">
              <template #default="{ row }">
                <el-input v-model="row.param_name" size="small" placeholder="param_name" />
              </template>
            </el-table-column>
            <el-table-column label="类型" width="120">
              <template #default="{ row }">
                <el-select v-model="row.param_type" size="small">
                  <el-option label="string" value="string" />
                  <el-option label="integer" value="integer" />
                  <el-option label="number" value="number" />
                  <el-option label="boolean" value="boolean" />
                  <el-option label="array" value="array" />
                  <el-option label="object" value="object" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="描述" min-width="160">
              <template #default="{ row }">
                <el-input v-model="row.param_desc" size="small" placeholder="参数描述" />
              </template>
            </el-table-column>
            <el-table-column label="必填" width="70" align="center">
              <template #default="{ row }">
                <el-checkbox v-model="row.required" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="70" align="center">
              <template #default="{ $index }">
                <el-button size="small" type="danger" link @click="form.parameters.splice($index, 1)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-button size="small" style="margin-top: 8px" @click="form.parameters.push({ param_name: '', param_type: 'string', param_desc: '', required: false })">新增参数</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="Skill 详情" width="700px">
      <el-descriptions :column="1" border v-if="detail">
        <el-descriptions-item label="名称">{{ detail.skill_name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ detail.skill_desc }}</el-descriptions-item>
        <el-descriptions-item label="分类">{{ detail.category }}</el-descriptions-item>
        <el-descriptions-item label="Skill ID">{{ detail.skill_id }}</el-descriptions-item>
        <el-descriptions-item label="模块路径">{{ detail.module_path || '-' }}</el-descriptions-item>
        <el-descriptions-item label="类名/函数名">{{ detail.class_name || '-' }} / {{ detail.function_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="延迟加载">{{ detail.lazy_load ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.enabled ? '启用' : '停用' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ detail.created_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="配置参数">
          <el-input type="textarea" :model-value="detail.config_param" :rows="4" readonly />
        </el-descriptions-item>
        <el-descriptions-item label="输入参数">
          <el-input type="textarea" :model-value="detail.input_json_param" :rows="4" readonly />
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { skillApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const list = ref([])
const loading = ref(false)
const detailVisible = ref(false)
const detail = ref(null)
const formVisible = ref(false)
const isEdit = ref(false)
const form = ref({})
const saving = ref(false)
const categories = ref([])
const activeTab = ref('db')
const localSkills = ref([])
const localLoading = ref(false)

const emptyForm = () => ({
  skill_id: '',
  skill_name: '',
  skill_desc: '',
  category: 'general',
  enabled: true,
  visibility: 'private',
  module_path: '',
  class_name: '',
  function_name: '',
  lazy_load: true,
  preload_priority: 0,
  parameters: [],
})

// 三层可见性 → 标签（兼容旧 is_public 字段）
const workspaceMap = ref({})

const loadWorkspaces = async () => {
  try {
    const token = localStorage.getItem('auth_token') || ''
    const res = await fetch('/api/auth/workspaces', { headers: { Authorization: token } })
    const data = await res.json()
    for (const ws of (data?.list || [])) {
      workspaceMap.value[ws.workspace_id] = ws.name
    }
  } catch { /* ignore */ }
}

const workspaceName = (id) => workspaceMap.value[id] || (id ? `#${id}` : '-')

const visTag = (row) => {
  const v = row.visibility || (row.is_public === 1 ? 'public' : 'workspace')
  if (v === 'public') return { type: 'success', label: '全局' }
  if (v === 'private') return { type: 'info', label: '个人' }
  return { type: 'warning', label: '空间' }
}

const loadData = async () => {
  loading.value = true
  try {
    const data = await skillApi.getList()
    list.value = data?.data?.skills ?? []
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const loadLocalSkills = async () => {
  localLoading.value = true
  try {
    const data = await skillApi.getLocalSkills()
    localSkills.value = data?.data?.skills ?? []
  } catch (e) {
    ElMessage.warning('加载本地技能失败')
  } finally {
    localLoading.value = false
  }
}

const onTabChange = (tab) => {
  if (tab === 'local' && localSkills.value.length === 0) {
    loadLocalSkills()
  }
}

const importLocal = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认将本地技能 "${row.name}" 导入数据库？导入后可通过 CRUD 功能管理。`,
      '导入确认',
      { type: 'info' }
    )
    await skillApi.importLocal(row.name)
    ElMessage.success(`技能 "${row.name}" 已导入数据库`)
    loadLocalSkills()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      const msg = e.response?.data?.detail || '导入失败'
      ElMessage.error(msg)
    }
  }
}

const loadCategories = async () => {
  try {
    const data = await skillApi.getCategories()
    categories.value = data?.data?.categories || []
  } catch {
    categories.value = []
  }
}

const showCreate = () => {
  isEdit.value = false
  form.value = emptyForm()
  formVisible.value = true
}

const showEdit = (row) => {
  isEdit.value = true
  form.value = {
    skill_id: row.skill_id || row.id || '',
    skill_name: row.skill_name || row.name || '',
    skill_desc: row.skill_desc || row.description || '',
    category: row.category || 'general',
    enabled: row.enabled ?? true,
    visibility: row.visibility || (row.is_public === 1 ? 'public' : 'workspace'),
    module_path: row.module_path || '',
    class_name: row.class_name || '',
    function_name: row.function_name || '',
    lazy_load: row.lazy_load ?? true,
    preload_priority: row.preload_priority ?? 0,
    parameters: (row.parameters || []).map(p => ({
      param_name: p.param_name || p.paramName || '',
      param_type: p.param_type || p.paramType || 'string',
      param_desc: p.param_desc || p.paramDesc || '',
      required: p.required ?? (p.is_require === '1' || p.isRequire === '1'),
    })),
  }
  formVisible.value = true
}

const save = async () => {
  if (!isEdit.value && !form.value.skill_id?.trim()) {
    ElMessage.warning('请填写 Skill ID')
    return
  }
  if (!form.value.skill_name?.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await skillApi.update(form.value.skill_id, {
        skill_name: form.value.skill_name,
        skill_desc: form.value.skill_desc,
        category: form.value.category,
        module_path: form.value.module_path,
        class_name: form.value.class_name,
        function_name: form.value.function_name,
        lazy_load: form.value.lazy_load,
        preload_priority: form.value.preload_priority,
        enabled: form.value.enabled,
        visibility: form.value.visibility,
        parameters: form.value.parameters,
      })
    } else {
      await skillApi.create({
        skill_id: form.value.skill_id,
        skill_name: form.value.skill_name,
        skill_desc: form.value.skill_desc,
        category: form.value.category,
        module_path: form.value.module_path,
        class_name: form.value.class_name,
        function_name: form.value.function_name,
        lazy_load: form.value.lazy_load,
        preload_priority: form.value.preload_priority,
        enabled: form.value.enabled,
        visibility: form.value.visibility,
        parameters: form.value.parameters,
      })
    }
    ElMessage.success('保存成功')
    formVisible.value = false
    loadData()
  } catch (e) {
    const msg = e.response?.data?.detail || '保存失败'
    ElMessage.error(msg)
  } finally {
    saving.value = false
  }
}

const showDetail = async (row) => {
  try {
    detail.value = await skillApi.getDetail(row.skill_id || row.id || row.name)
    detail.value = detail.value?.data || detail.value
  } catch {
    detail.value = row
  }
  detailVisible.value = true
}

const toggleEnabled = async (row) => {
  try {
    await skillApi.update(row.skill_id || row.id || row.name, {
      enabled: !row.enabled
    })
    ElMessage.success(row.enabled ? '已停用' : '已启用')
    loadData()
  } catch {
    ElMessage.error('操作失败')
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除 Skill "${row.skill_name || row.skill_id}"？`,
      '提示',
      { type: 'warning' }
    )
    await skillApi.delete(row.skill_id || row.id || row.name)
    ElMessage.success('删除成功')
    loadData()
  } catch {}
}

const reloadSkills = async () => {
  try {
    await skillApi.reload()
    ElMessage.success('Skill 已重新加载')
    loadData()
  } catch {
    ElMessage.error('重新加载失败')
  }
}

onMounted(() => {
  loadWorkspaces()
  loadData()
  loadCategories()
})
</script>
