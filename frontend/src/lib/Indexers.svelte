<script lang="ts">
  import { api } from './api'

  type Field = { name: string; label: string; secret: boolean; required: boolean; placeholder: string }
  type Kind = { kind: string; label: string; default_url: string; fields: Field[] }
  type Ix = { id: number; name: string; kind: string; url: string; username: string; enabled: boolean; priority: number; failures: number
    disabled_until: string | null;
    last_error: string | null; has_key: boolean; has_cookie: boolean; seed_ratio: number | null; seed_hours: number | null }

  let kinds = $state<Kind[]>([])
  let list = $state<Ix[]>([])
  let kind = $state('torznab')
  let form = $state<Record<string, string>>({ name: '' })
  let seedRatio = $state('')
  let seedHours = $state('')
  let msg = $state('')

  const spec = $derived(kinds.find((k) => k.kind === kind))

  async function load() { list = await api('/indexers') }
  async function add() {
    msg = 'Testing…'
    try {
      await api('/indexers', 'POST', {
        ...form, kind,
        seed_ratio: seedRatio ? Number(seedRatio) : null, seed_hours: seedHours ? Number(seedHours) : null,
      })
      msg = 'Added'
      form = { name: '' }; seedRatio = ''; seedHours = ''
      await load()
    } catch (e: any) { msg = e.message }
  }
  async function test(id: number) {
    const r = await api<{ ok: boolean; error?: string }>(`/indexers/${id}/test`, 'POST')
    msg = r.ok ? 'OK' : r.error ?? 'Failed'
    await load()
  }
  async function patch(i: Ix, body: { enabled?: boolean; priority?: number }) {
    try { await api(`/indexers/${i.id}`, 'PATCH', body); msg = '' } catch (e: any) { msg = e.message }
    await load()
  }
  async function del(id: number) { await api(`/indexers/${id}`, 'DELETE'); await load() }
  $effect(() => { api<Kind[]>('/indexers/kinds').then((k) => (kinds = k)); load() })
</script>

{#each list as i (i.id)}
  <div class="row" class:disabled={!i.enabled}>
    <label class="sw" title={i.enabled ? 'Enabled' : 'Disabled'}>
      <input type="checkbox" checked={i.enabled} onchange={(e) => patch(i, { enabled: e.currentTarget.checked })} />
    </label>
    <label class="prio" title="1 = searched first and preferred on ties, 50 = last">Priority
      <input type="number" min="1" max="50" value={i.priority}
        onchange={(e) => patch(i, { priority: Number(e.currentTarget.value) })} />
    </label>
    <div class="grow"><strong>{i.name}</strong> <small>{i.kind} · {i.url}{i.username ? ' · ' + i.username : ''}
      {i.has_key ? '· key set' : ''}{i.has_cookie ? '· cookie set' : ''}</small>
      {#if i.seed_ratio !== null || i.seed_hours !== null}<br /><small>seed: ratio {i.seed_ratio ?? 'default'}, {i.seed_hours ?? 'default'} h</small>{/if}
      {#if i.last_error}<br /><span class="err">{i.last_error} (failures: {i.failures}{i.disabled_until ? `, paused until ${i.disabled_until.slice(11, 16)} UTC` : ''})</span>{/if}</div>
    <button onclick={() => test(i.id)}>Test</button>
    <button onclick={() => del(i.id)}>Delete</button>
  </div>
{/each}

<h3>Add indexer</h3>
<form onsubmit={(e) => { e.preventDefault(); add() }}>
  <select bind:value={kind}>{#each kinds as k}<option value={k.kind}>{k.label}</option>{/each}</select>
  <input placeholder="Name" bind:value={form.name} required />
  {#each spec?.fields ?? [] as f (kind + f.name)}
    <input type={f.secret ? 'password' : 'text'} placeholder={f.label + (f.required ? '' : ' (optional)') + (f.placeholder ? ' – ' + f.placeholder : '')}
      bind:value={form[f.name]} required={f.required} autocomplete="off" />
  {/each}
  <details><summary>Seeding override (private trackers)</summary>
    <input placeholder="Min ratio" bind:value={seedRatio} /> <input placeholder="Min hours" bind:value={seedHours} />
  </details>
  <button>Test &amp; add</button>
</form>
<p>{msg}</p>

<style>
  .row { display: flex; gap: .5rem; align-items: center; background: #1c2128; padding: .5rem; margin-bottom: .4rem; border-radius: 6px; }
  .grow { flex: 1; word-break: break-all; }
  .disabled { opacity: .5; }
  .prio { display: flex; align-items: center; gap: .3rem; font-size: .8rem; } .prio input { width: 3.4rem; padding: .2rem; }
  form { display: flex; flex-direction: column; gap: .4rem; max-width: 34rem; }
  input, select { padding: .35rem; }
  .err { color: #f66; font-size: .85rem; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .3rem .6rem; cursor: pointer; }
</style>
