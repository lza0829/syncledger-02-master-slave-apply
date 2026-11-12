<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON, postJSON } from '../api'

const route = useRoute()
const batches = ref([])
const runs = ref([])
const settings = ref({})
const policy = ref('record_only')
const policyDirty = ref(false)
const selectedBatchId = ref(null)
const note = ref('')
const current = ref(null)
const currentTitle = ref('')
const sides = ref(null)
const showSides = ref(false)
const busy = ref(false)
const err = ref('')
const msg = ref('')

const POLICIES = [
  { value: 'left_wins', label: '以左为准盖右', desc: '以左侧为准，把右侧不一致字段盖成左值' },
  { value: 'right_wins', label: '以右为准盖左', desc: '以右侧为准，把左侧不一致字段盖成右值' },
  { value: 'record_only', label: '只记账不盖写', desc: '两侧都不改，只留处置账' },
]
const policyLabel = { left_wins: '以左为准盖右', right_wins: '以右为准盖左', record_only: '只记账不盖写' }
const statusLabel = { completed: '全成功', partial_success: '部分成功', failed: '失败' }
const statusClass = { completed: 'ok', partial_success: 'warn', failed: 'danger' }
const actionLabel = { overwritten: '已盖写', failed: '失败', skipped: '跳过', recorded: '已记账' }
const actionClass = { overwritten: 'ok', failed: 'danger', skipped: 'warn', recorded: '' }
const kindLabel = { left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }

const selectedBatch = computed(() => batches.value.find(b => b.id === selectedBatchId.value) || null)

async function refresh() {
  batches.value = await getJSON('/api/batches?limit=50')
  runs.value = await getJSON('/api/dispositions?limit=20')
  settings.value = await getJSON('/api/settings')
  if (!policyDirty.value && settings.value.default_policy) policy.value = settings.value.default_policy
  if (selectedBatchId.value == null || !batches.value.some(b => b.id === selectedBatchId.value)) {
    const q = Number(route.query.batch_id)
    if (q && batches.value.some(b => b.id === q)) selectedBatchId.value = q
    else {
      const withFm = batches.value.find(b => b.field_mismatch > 0)
      selectedBatchId.value = withFm ? withFm.id : (batches.value[0]?.id ?? null)
    }
  }
}

async function loadSides() {
  sides.value = null
  if (!selectedBatch.value) return
  sides.value = await getJSON(`/api/pairs/${selectedBatch.value.pair_id}/sides`)
}

async function execute() {
  err.value = ''; msg.value = ''; busy.value = true
  try {
    current.value = await postJSON('/api/dispositions', {
      batch_id: Number(selectedBatchId.value),
      policy: policy.value,
      note: note.value || null,
    })
    currentTitle.value = '本次处置结果'
    runs.value = await getJSON('/api/dispositions?limit=20')
    await loadSides()
    showSides.value = true
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function viewRun(id) {
  err.value = ''
  try {
    current.value = await getJSON(`/api/dispositions/${id}`)
    currentTitle.value = `历史处置明细 #${id}`
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function resetFixtures() {
  if (!window.confirm('把所有工作夹具恢复为种子状态？历史批次与处置留痕保留，但侧数据会被还原。')) return
  err.value = ''; msg.value = ''
  try {
    await postJSON('/api/fixtures/reset')
    msg.value = '夹具已恢复种子状态。历史批次与处置留痕保留；如需最新差异请重新对账。'
    await loadSides()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function fmtVal(v) {
  if (v === null || v === undefined) return '(空)'
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

function fmtFields(e) {
  if (!e.fields || !e.fields.length) return '—'
  if (e.action === 'recorded') {
    return e.fields.map(f => `${f.field}: 左=${fmtVal(f.left_value)} 右=${fmtVal(f.right_value)}`).join('；')
  }
  return e.fields.map(f => `${f.field}: ${fmtVal(f.old_value)} → ${fmtVal(f.new_value)}`).join('；')
}

onMounted(async () => {
  try {
    await refresh()
    await loadSides()
  } catch (e) { err.value = String(e.message || e) }
})
watch(selectedBatchId, async () => {
  try { await loadSides() } catch (e) { err.value = String(e.message || e) }
})
</script>

<template>
  <div class="page">
    <h1>差异处置</h1>
    <p class="muted">
      主从盖写落地：三种策略互斥，单次处置只生效所选一种；盖写真实落到目标侧夹具并逐键留痕（键/字段/旧值/新值）。
      不是客服工单台。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag ok">{{ msg }}</p>

    <div class="panel">
      <h3 style="margin-top:0">发起处置</h3>
      <div style="display:flex;flex-wrap:wrap;gap:1.5rem;align-items:flex-start">
        <fieldset style="border:1px solid var(--line);border-radius:4px;margin:0;padding:0.5rem 0.75rem">
          <legend class="muted" style="padding:0 0.25rem">处置策略（互斥，单选）</legend>
          <label v-for="p in POLICIES" :key="p.value" style="display:block;padding:0.2rem 0;cursor:pointer">
            <input type="radio" v-model="policy" :value="p.value" @change="policyDirty = true" style="margin-right:0.35rem" />
            <b>{{ p.label }}</b>
            <span class="muted"> — {{ p.desc }}</span>
          </label>
          <div class="muted" style="font-size:0.82rem;margin-top:0.3rem">
            默认策略来自设置页（当前 {{ policyLabel[settings.default_policy] || settings.default_policy }}），此处选择仅本次生效。
          </div>
        </fieldset>
        <div style="min-width:16rem">
          <label>
            目标批次
            <select v-model.number="selectedBatchId" style="display:block;min-width:22rem;margin-top:0.25rem">
              <option v-for="b in batches" :key="b.id" :value="b.id">
                {{ b.batch_no }} · {{ b.pair_title }} · 字段不一致 {{ b.field_mismatch }} · 差异 {{ b.diff_total }}
              </option>
            </select>
          </label>
          <label style="display:block;margin-top:0.5rem">
            备注（可选）
            <input v-model="note" style="display:block;width:22rem;margin-top:0.25rem" placeholder="本次处置说明" />
          </label>
        </div>
        <div>
          <button :disabled="busy || !selectedBatchId" @click="execute">
            {{ busy ? '处置中…' : '执行处置' }}
          </button>
          <button class="secondary" style="margin-left:0.5rem" :disabled="busy" @click="resetFixtures">
            恢复种子夹具
          </button>
          <div class="muted" style="font-size:0.82rem;margin-top:0.5rem;max-width:22rem">
            失败策略（固定，不混用）：保留已成功盖写，失败键单独留痕，批次记「部分成功」；不做整批回滚。
          </div>
        </div>
      </div>
    </div>

    <div class="panel" v-if="current">
      <h3 style="margin-top:0">{{ currentTitle }}</h3>
      <p>
        处置批 <span class="mono">{{ current.run_no }}</span> · {{ current.pair_title }} ·
        策略 <span class="tag">{{ current.policy_label }}</span>
        <template v-if="current.target_side"> · 目标侧 <span class="tag">{{ current.target_side === 'left' ? '左' : '右' }}</span></template>
        · 状态 <span class="tag" :class="statusClass[current.status]">{{ statusLabel[current.status] || current.status }}</span>
      </p>
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ current.applied }}</div><div class="stat-label">盖写成功（键）</div></div>
        <div class="stat"><div class="stat-num">{{ current.failed }}</div><div class="stat-label">失败（键）</div></div>
        <div class="stat"><div class="stat-num">{{ current.skipped }}</div><div class="stat-label">跳过（键）</div></div>
        <div class="stat"><div class="stat-num">{{ current.recorded }}</div><div class="stat-label">仅记账（键）</div></div>
        <div class="stat"><div class="stat-num">{{ current.remaining_mismatch }}</div><div class="stat-label">仍残留字段不一致</div></div>
      </div>
      <p v-if="current.error" class="tag danger" style="margin-top:0.75rem">{{ current.error }}</p>
      <p class="muted" style="margin-top:0.5rem;font-size:0.85rem">
        残留数按处置后两侧夹具现值重算，与差异列表及下方留痕对账；不是改差异状态得来的。
        <template v-if="current.pair_field_mismatch_now !== undefined">
          该对账对当前字段不一致总数：{{ current.pair_field_mismatch_now }}。
        </template>
      </p>
      <table style="margin-top:0.5rem">
        <thead>
          <tr><th>对齐键</th><th>差异类型</th><th>动作</th><th>目标侧</th><th>字段明细（旧值 → 新值）</th><th>原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in current.entries" :key="e.id">
            <td class="mono">{{ JSON.stringify(e.align_key) }}</td>
            <td>{{ kindLabel[e.kind] || e.kind }}</td>
            <td><span class="tag" :class="actionClass[e.action]">{{ actionLabel[e.action] || e.action }}</span></td>
            <td>{{ e.target_side ? (e.target_side === 'left' ? '左' : '右') : '—' }}</td>
            <td class="mono">{{ fmtFields(e) }}</td>
            <td class="muted">{{ e.reason || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel" v-if="sides">
      <h3 style="margin-top:0">
        侧数据现状
        <button class="secondary" style="font-size:0.8rem;padding:0.2rem 0.6rem" @click="showSides = !showSides">
          {{ showSides ? '收起' : '展开' }}
        </button>
      </h3>
      <p class="muted" style="margin-top:0">直接读工作夹具（{{ sides.left_fixture }} / {{ sides.right_fixture }}），用于核对盖写是否真落到侧数据。</p>
      <div v-if="showSides" style="display:flex;gap:1rem;flex-wrap:wrap">
        <div style="flex:1;min-width:20rem">
          <h4>{{ sides.left_name }}（左）</h4>
          <pre class="mono" style="white-space:pre-wrap;font-size:0.8rem">{{ JSON.stringify(sides.left_rows, null, 1) }}</pre>
        </div>
        <div style="flex:1;min-width:20rem">
          <h4>{{ sides.right_name }}（右）</h4>
          <pre class="mono" style="white-space:pre-wrap;font-size:0.8rem">{{ JSON.stringify(sides.right_rows, null, 1) }}</pre>
        </div>
      </div>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">处置历史</h3>
      <table>
        <thead>
          <tr>
            <th>处置批</th><th>对账批次</th><th>策略</th><th>状态</th>
            <th>成功</th><th>失败</th><th>跳过</th><th>记账</th><th>残留</th><th>时间</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td class="mono">{{ r.run_no }}</td>
            <td class="mono">{{ r.batch_no }}</td>
            <td>{{ r.policy_label }}</td>
            <td><span class="tag" :class="statusClass[r.status]">{{ statusLabel[r.status] || r.status }}</span></td>
            <td>{{ r.applied }}</td>
            <td>{{ r.failed }}</td>
            <td>{{ r.skipped }}</td>
            <td>{{ r.recorded }}</td>
            <td>{{ r.remaining_mismatch }}</td>
            <td class="mono">{{ r.created_at }}</td>
            <td><button class="secondary" style="font-size:0.8rem;padding:0.2rem 0.6rem" @click="viewRun(r.id)">明细</button></td>
          </tr>
          <tr v-if="!runs.length"><td colspan="11" class="muted">还没有处置记录。先去对账台跑一趟，再回这里执行处置。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
