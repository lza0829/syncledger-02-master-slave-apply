<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const stats = ref(null)
const err = ref('')
const policyLabel = { left_wins: '以左为准盖右', right_wins: '以右为准盖左', record_only: '只记账不盖写' }
const statusLabel = { completed: '全成功', partial_success: '部分成功', failed: '失败' }
const statusClass = { completed: 'ok', partial_success: 'warn', failed: 'danger' }
onMounted(async () => {
  try { stats.value = await getJSON('/api/dashboard') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>总览</h1>
    <p class="muted">跨库对齐对账：双端抽取、对齐键匹配、差异记账，主从处置盖写落到侧夹具并留痕。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="stats">
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ stats.pair_count }}</div><div class="stat-label">对账对</div></div>
        <div class="stat"><div class="stat-num">{{ stats.enabled_pairs }}</div><div class="stat-label">已启用</div></div>
        <div class="stat"><div class="stat-num">{{ stats.batch_count }}</div><div class="stat-label">对账批次</div></div>
        <div class="stat"><div class="stat-num">{{ stats.diff_count }}</div><div class="stat-label">差异行</div></div>
        <div class="stat"><div class="stat-num">{{ stats.disposition_runs }}</div><div class="stat-label">处置批次</div></div>
      </div>
      <p style="margin-top:1rem">
        默认处置策略 <span class="tag">{{ policyLabel[stats.policy] || stats.policy }}</span>
        <template v-if="stats.last_disposition">
          · 最近处置 <span class="mono">{{ stats.last_disposition.run_no }}</span>
          <span class="tag" :class="statusClass[stats.last_disposition.status]">
            {{ statusLabel[stats.last_disposition.status] || stats.last_disposition.status }}
          </span>
          · 残留字段不一致 {{ stats.last_disposition.remaining_mismatch }}
        </template>
      </p>
      <p>
        <router-link to="/run">去对账台跑一趟 →</router-link>
        ·
        <router-link to="/dispositions">去差异处置 →</router-link>
      </p>
    </div>
  </div>
</template>
