<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span>Agent 团队管理</span>
          <div>
            <el-button @click="openMailbox">Agent 邮箱</el-button>
            <el-button type="primary" @click="openCreate">新建团队</el-button>
          </div>
        </div>
      </template>
      <el-table :data="teams" v-loading="loading" border>
        <el-table-column prop="name" label="团队名称" width="150" />
        <el-table-column prop="members" label="成员" show-overflow-tooltip>
          <template #default="{ row }">
            {{ formatMembers(row.members) }}
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" show-overflow-tooltip />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="openMembers(row)">成员</el-button>
            <el-button size="small" type="success" @click="dispatchTeam(row)">团队调度</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建团队 -->
    <el-dialog v-model="createVisible" title="新建团队" width="600px">
      <el-form label-width="100px">
        <el-form-item label="团队名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" /></el-form-item>
        <el-form-item label="成员">
          <div v-for="(m, i) in form.members" :key="i" style="margin-bottom:8px;display:flex;align-items:center;">
            <el-select v-model="m.agent_id" filterable placeholder="选 Agent" style="width:240px;margin-right:8px;">
              <el-option v-for="a in agents" :key="a.pr_key_id" :label="`${a.agent_name} (id:${a.pr_key_id})`" :value="String(a.pr_key_id)" />
            </el-select>
            <el-input v-model="m.role" placeholder="角色如 researcher" style="width:150px;margin-right:8px;" />
            <el-button size="small" type="danger" @click="form.members.splice(i, 1)">删</el-button>
          </div>
          <el-button size="small" @click="form.members.push({ agent_id: '', role: 'member' })">+ 添加成员</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 成员管理 -->
    <el-dialog v-model="membersVisible" :title="`成员 - ${currentTeam?.name || ''}`" width="600px">
      <div style="margin-bottom:12px;display:flex;align-items:center;">
        <el-select v-model="newMember.agent_id" filterable placeholder="选 Agent" style="width:240px;margin-right:8px;">
          <el-option v-for="a in agents" :key="a.pr_key_id" :label="`${a.agent_name} (id:${a.pr_key_id})`" :value="String(a.pr_key_id)" />
        </el-select>
        <el-input v-model="newMember.role" placeholder="角色" style="width:150px;margin-right:8px;" />
        <el-button size="small" type="primary" @click="addMember">添加</el-button>
      </div>
      <el-table :data="memberList" border size="small">
        <el-table-column label="Agent">
          <template #default="{ row }">{{ agentName(row.agent_id) }}</template>
        </el-table-column>
        <el-table-column prop="role" label="角色" width="150" />
      </el-table>
    </el-dialog>

    <!-- Agent 邮箱 -->
    <el-dialog v-model="mailboxVisible" title="Agent 邮箱" width="760px">
      <el-tabs v-model="mailboxTab">
        <el-tab-pane label="发消息" name="send">
          <el-form label-width="100px">
            <el-form-item label="发送方">
              <el-select v-model="mailForm.from_agent" filterable placeholder="选 Agent" style="width:100%;">
                <el-option v-for="a in agents" :key="a.pr_key_id" :label="a.agent_name" :value="a.agent_name" />
              </el-select>
            </el-form-item>
            <el-form-item label="接收方">
              <el-select v-model="mailForm.to_agent" filterable placeholder="选 Agent" style="width:100%;">
                <el-option v-for="a in agents" :key="a.pr_key_id" :label="a.agent_name" :value="a.agent_name" />
              </el-select>
            </el-form-item>
            <el-form-item label="内容"><el-input type="textarea" v-model="mailForm.content" :rows="3" /></el-form-item>
            <el-form-item label="类型">
              <el-select v-model="mailForm.msg_type" style="width:100%;">
                <el-option label="文本 (text)" value="text" />
                <el-option label="广播 (broadcast)" value="broadcast" />
              </el-select>
            </el-form-item>
            <el-button type="primary" @click="sendMessage" :loading="sending">发送</el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="收件箱" name="inbox">
          <div style="margin-bottom:8px;">
            <el-select v-model="pollAgent" filterable placeholder="选 Agent" style="width:200px;margin-right:8px;">
              <el-option v-for="a in agents" :key="a.pr_key_id" :label="a.agent_name" :value="a.agent_name" />
            </el-select>
            <el-button size="small" @click="pollMessages" :loading="polling">拉取消息</el-button>
          </div>
          <el-table :data="messages" border size="small">
            <el-table-column prop="from_agent" label="来自" width="120" />
            <el-table-column prop="content" label="内容" show-overflow-tooltip />
            <el-table-column prop="msg_type" label="类型" width="80" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" @click="ackMessage(row.message_id)">确认</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { teamApi, agentApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const teams = ref([])
const agents = ref([])
const loading = ref(false)
const createVisible = ref(false)
const saving = ref(false)
const form = ref({ name: '', description: '', members: [{ agent_id: '', role: 'member' }] })
const membersVisible = ref(false)
const currentTeam = ref(null)
const memberList = ref([])
const newMember = ref({ agent_id: '', role: 'member' })
const mailboxVisible = ref(false)
const mailboxTab = ref('send')
const mailForm = ref({ from_agent: '', to_agent: '', content: '', msg_type: 'text' })
const sending = ref(false)
const pollAgent = ref('')
const messages = ref([])
const polling = ref(false)

const formatMembers = (membersJson) => {
  try {
    const arr = JSON.parse(membersJson || '[]')
    return arr.map(m => `${agentName(m.agent_id)}(${m.role})`).join(', ')
  } catch { return membersJson || '' }
}

const agentName = (id) => {
  const a = agents.value.find(x => String(x.pr_key_id) === String(id))
  return a ? a.agent_name : id
}

const loadData = async () => {
  loading.value = true
  try {
    const res = await teamApi.list()
    // 后端团队路由统一用 wrap_response → {code, message, data:{teams, total}}
    // axios 响应拦截器已提取 response.data，故业务字段在 res.data
    teams.value = res.data?.teams || []
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const loadAgents = async () => {
  try {
    const res = await agentApi.getList({ limit: 100 })
    agents.value = res?.agents ?? []
  } catch (e) { ElMessage.error('加载 Agent 列表失败') }
}

const openCreate = () => {
  form.value = { name: '', description: '', members: [{ agent_id: '', role: 'member' }] }
  createVisible.value = true
}

const save = async () => {
  if (!form.value.name) { ElMessage.warning('请输入团队名称'); return }
  saving.value = true
  try {
    await teamApi.create({
      name: form.value.name,
      description: form.value.description,
      members: form.value.members.filter(m => m.agent_id),
    })
    ElMessage.success('创建成功')
    createVisible.value = false
    loadData()
  } catch (e) { ElMessage.error('创建失败') }
  finally { saving.value = false }
}

const openMembers = async (row) => {
  currentTeam.value = row
  try {
    const res = await teamApi.detail(row.team_id)
    memberList.value = JSON.parse(res.data?.members || '[]')
  } catch { memberList.value = [] }
  newMember.value = { agent_id: '', role: 'member' }
  membersVisible.value = true
}

const addMember = async () => {
  if (!newMember.value.agent_id) { ElMessage.warning('请选择 Agent'); return }
  try {
    await teamApi.addMember(currentTeam.value.team_id, newMember.value)
    ElMessage.success('已添加')
    const res = await teamApi.detail(currentTeam.value.team_id)
    memberList.value = JSON.parse(res.data?.members || '[]')
    newMember.value = { agent_id: '', role: 'member' }
    loadData()
  } catch (e) { ElMessage.error('添加失败') }
}

const dispatchTeam = async (row) => {
  try {
    await ElMessageBox.confirm(`用团队「${row.name}」发起调度？（自动展开为团队成员）`, '团队调度', { type: 'info' })
    router.push({ path: '/agents', query: { teamDispatch: row.team_id } })
  } catch { /* 取消 */ }
}

const openMailbox = () => {
  mailboxTab.value = 'send'
  mailForm.value = { from_agent: '', to_agent: '', content: '', msg_type: 'text' }
  messages.value = []
  mailboxVisible.value = true
}

const sendMessage = async () => {
  if (!mailForm.value.from_agent || !mailForm.value.to_agent || !mailForm.value.content) {
    ElMessage.warning('请填写完整'); return
  }
  sending.value = true
  try {
    await teamApi.sendMessage(mailForm.value)
    ElMessage.success('已发送')
    mailForm.value.content = ''
  } catch (e) { ElMessage.error('发送失败') }
  finally { sending.value = false }
}

const pollMessages = async () => {
  if (!pollAgent.value) { ElMessage.warning('请选择 Agent'); return }
  polling.value = true
  try {
    const res = await teamApi.pollMessages(pollAgent.value)
    messages.value = res.data?.messages || []
  } catch (e) { ElMessage.error('拉取失败') }
  finally { polling.value = false }
}

const ackMessage = async (messageId) => {
  try {
    await teamApi.ackMessage(messageId)
    ElMessage.success('已确认')
    if (pollAgent.value) pollMessages()
  } catch (e) { ElMessage.error('确认失败') }
}

onMounted(() => {
  loadData()
  loadAgents()
})
</script>
