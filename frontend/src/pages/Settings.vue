<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, putJSON } from '../api'

const settings = ref({})
const policy = ref('record_only')
const err = ref('')
const msg = ref('')

const POLICIES = [
  { value: 'left_wins', label: '以左为准盖右', desc: '处置时以左侧为准，把右侧不一致字段盖成左值' },
  { value: 'right_wins', label: '以右为准盖左', desc: '处置时以右侧为准，把左侧不一致字段盖成右值' },
  { value: 'record_only', label: '只记账不盖写', desc: '两侧都不改，只留处置账（默认）' },
]

async function refresh() {
  settings.value = await getJSON('/api/settings')
  policy.value = settings.value.default_policy || 'record_only'
}

async function save() {
  err.value = ''; msg.value = ''
  try {
    settings.value = await putJSON('/api/settings', { key: 'default_policy', value: policy.value })
    msg.value = '已保存。对账台与差异处置页的新处置将默认使用该策略。'
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>设置</h1>
    <p class="muted">全局策略键值。处置策略三选一、互斥生效；单次处置仍可在处置页临时改选。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag ok">{{ msg }}</p>

    <div class="panel">
      <h3 style="margin-top:0">默认处置策略（default_policy）</h3>
      <label v-for="p in POLICIES" :key="p.value" style="display:block;padding:0.25rem 0;cursor:pointer">
        <input type="radio" v-model="policy" :value="p.value" style="margin-right:0.35rem" />
        <b>{{ p.label }}</b>
        <span class="muted"> — {{ p.desc }}</span>
      </label>
      <p class="muted" style="font-size:0.85rem">
        失败策略固定为「保留已成功盖写、失败键单独留痕、批次记部分成功」，不整批回滚，不混用。
      </p>
      <button @click="save">保存默认策略</button>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">全部设置项</h3>
      <table>
        <thead><tr><th>键</th><th>值</th></tr></thead>
        <tbody>
          <tr v-for="(v, k) in settings" :key="k">
            <td class="mono">{{ k }}</td>
            <td class="mono">{{ v }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
