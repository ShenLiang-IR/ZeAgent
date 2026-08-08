<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header>
        <span style="font-size: 20px; font-weight: bold;">{{ isRegister ? '注册' : '登录' }}</span>
      </template>
      <el-form :model="form" label-width="80px" @submit.prevent="handleSubmit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="用户名" />
        </el-form-item>
        <el-form-item v-if="isRegister" label="手机号">
          <el-input v-model="form.phone" placeholder="手机号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password />
        </el-form-item>
        <el-form-item v-if="isRegister" label="确认密码">
          <el-input v-model="form.confirmPassword" type="password" placeholder="确认密码" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleSubmit" style="width: 100%;">
            {{ isRegister ? '注册' : '登录' }}
          </el-button>
        </el-form-item>
        <el-form-item>
          <el-link type="primary" @click="isRegister = !isRegister">
            {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
          </el-link>
        </el-form-item>
      </el-form>
      <el-alert v-if="errorMsg" :title="errorMsg" type="error" :closable="false" style="margin-top: 10px;" />
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '../api/index.js'

const router = useRouter()
const isRegister = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const form = ref({ username: '', phone: '', password: '', confirmPassword: '' })

const handleSubmit = async () => {
  errorMsg.value = ''
  if (!form.value.username || !form.value.password) {
    errorMsg.value = '用户名和密码必填'
    return
  }
  if (isRegister.value) {
    if (form.value.password !== form.value.confirmPassword) {
      errorMsg.value = '两次密码不一致'
      return
    }
    if (!form.value.phone) {
      errorMsg.value = '手机号必填'
      return
    }
  }
  loading.value = true
  try {
    let result
    if (isRegister.value) {
      result = await authApi.register(form.value.username, form.value.phone, form.value.password)
    } else {
      result = await authApi.login(form.value.username, form.value.password)
    }
    localStorage.setItem('auth_token', 'Bearer ' + result.token)
    localStorage.setItem('user_info', JSON.stringify(result.user))
    ElMessage.success(isRegister.value ? '注册成功' : '登录成功')
    router.push('/dashboard')
  } catch (e) {
    errorMsg.value = e.message || '操作失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: #f0f2f5;
}
.login-card {
  width: 420px;
}
</style>
