<template>
  <div class="login-page">
    <div class="login-card">
      <h2 class="login-title">知识库问答系统</h2>
      <p class="login-subtitle">请登录后使用</p>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            autocomplete="username"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          class="login-btn"
          :loading="auth.loading"
          @click="handleLogin"
        >
          登 录
        </el-button>
      </el-form>
      <p class="login-hint">默认管理员账号：admin / admin</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const formRef = ref<FormInstance>()

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    const ok = await auth.login({ username: form.username, password: form.password })
    if (ok) {
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/'
      router.push(redirect)
    }
  })
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ef 100%);
}

.login-card {
  width: 380px;
  padding: 40px 36px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
}

.login-title {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 600;
  color: #1a1b1c;
  text-align: center;
}

.login-subtitle {
  margin: 0 0 28px;
  font-size: 13px;
  color: #6b7280;
  text-align: center;
}

.login-btn {
  width: 100%;
  margin-top: 8px;
}

.login-hint {
  margin: 16px 0 0;
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
}
</style>
