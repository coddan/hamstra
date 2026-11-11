<script lang="ts">
  import { api } from './api'
  import { bytes } from './fmt'

  type Check = { name: string; status: 'ok' | 'warn' | 'error' | 'off'; detail: string }
  type Job = { at: string; ok: boolean; result: string }
  type Log = { ts: number; level: string; name: string; msg: string }

  let checks = $state<Check[]>([])
  let jobs = $state<Record<string, Job>>({})
  let backups = $state<{ name: string; size: number; created: string }[]>([])
  let logs = $state<Log[]>([])
  let level = $state('INFO')
  let live = $state(true)
  let msg = $state('')

  async function loadHealth() {
    const h = await api<{ checks: Check[]; jobs: Record<string, Job> }>('/system/health')
    checks = h.checks; jobs = h.jobs
    backups = await api('/system/backups')
  }
  async function loadLogs() { logs = await api(`/system/logs?level=${level}&limit=300`) }
  async function backupNow() {
    try { const r = await api<{ name: string }>('/system/backups', 'POST'); msg = `Created ${r.name}`; await loadHealth() } catch (e: any) { msg = e.message }
  }
  async function restore(name: string) {
    if (!confirm(`Restore the database from ${name}?\n\nThe current database is kept as a backup first. The change happens when the app restarts.`)) return
    try {
      await api(`/system/backups/${name}/restore`, 'POST')
      if (confirm('Restore is queued. Restart the app now to apply it?')) { await api('/system/restart', 'POST'); msg = 'Restarting… reload this page in a few seconds.' }
      else msg = 'Queued. It is applied the next time the app starts.'
    } catch (e: any) { msg = e.message }
  }
  async function restartApp() {
    if (!confirm('Restart the app now? Downloads keep going; it is back in a few seconds.')) return
    try { await api('/system/restart', 'POST'); msg = 'Restarting… reload this page in a few seconds.' } catch (e: any) { msg = e.message }
  }
  async function runJob(path: string, label: string) {
    msg = `${label}…`
    try { msg = `${label}: ${JSON.stringify(await api(path, 'POST'))}` } catch (e: any) { msg = e.message }
    await loadLogs()
  }

  $effect(() => { loadHealth() })
  $effect(() => {
    level; loadLogs()
    if (!live) return
    const t = setInterval(loadLogs, 5000)
    return () => clearInterval(t)
  })

  const icon = { ok: '●', warn: '▲', error: '✖', off: '○' }
  const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString()
</script>

<h3>Health</h3>
<div class="checks">
  {#each checks as c}
    <div class="check {c.status}"><span class="ic">{icon[c.status]}</span><div><b>{c.name}</b><br /><small>{c.detail}</small></div></div>
  {/each}
</div>
<button onclick={loadHealth}>Re-check</button>

<h3>Background jobs</h3>
{#if Object.keys(jobs).length === 0}<p><small>No job has run yet since the app started.</small></p>{/if}
<table><tbody>
  {#each Object.entries(jobs) as [name, j]}
    <tr><td>{name}</td><td>{j.at.replace('T', ' ')}</td><td class={j.ok ? 'okc' : 'errc'}>{j.ok ? 'ok' : 'failed'}</td><td><small>{j.result}</small></td></tr>
  {/each}
</tbody></table>
<div class="btns">
  <button onclick={() => runJob('/commands/sync-queue', 'Queue sync')}>Run queue sync</button>
  <button onclick={() => runJob('/commands/rss-sync', 'RSS sync')}>Run RSS sync now</button>
  <button onclick={() => runJob('/commands/search-wanted', 'Search wanted')}>Search all wanted now</button>
</div>
{#if msg}<p class="msg">{msg}</p>{/if}

<h3>Backups</h3>
<p><small>The database (library, settings, accounts) is backed up automatically every night at 03:30; the last 14 are kept in the app's data folder.</small></p>
<button onclick={backupNow}>Back up now</button> <button onclick={restartApp}>Restart app</button>
<table><tbody>
  {#each backups as b}<tr><td>{b.name}</td><td>{b.created.replace('T', ' ')}</td><td>{bytes(b.size)}</td><td><a href={`/api/v1/system/backups/${b.name}`}>Download</a> · <button class="link" onclick={() => restore(b.name)}>Restore…</button></td></tr>{/each}
</tbody></table>

<h3>Log</h3>
<div class="btns">
  <select bind:value={level}><option>INFO</option><option>WARNING</option><option>ERROR</option></select>
  <label><input type="checkbox" bind:checked={live} /> auto-refresh</label>
</div>
<div class="log">
  {#each logs as l}
    <div class="ln {l.level}"><span class="t">{time(l.ts)}</span> <b>{l.level}</b> <span class="n">{l.name}</span> {l.msg}</div>
  {:else}<small>No entries.</small>{/each}
</div>

<style>
  .checks { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: .5rem; margin-bottom: .6rem; }
  .check { display: flex; gap: .6rem; background: #1c2128; padding: .5rem .7rem; border-radius: 6px; border-left: 3px solid #3fb950; word-break: break-word; }
  .check.warn { border-color: #c9a227; } .check.error { border-color: #f66; } .check.off { border-color: #555; opacity: .75; }
  .ic { font-size: .8rem; } .ok .ic { color: #3fb950; } .warn .ic { color: #c9a227; } .error .ic { color: #f66; }
  td { padding: .25rem .8rem; font-size: .85rem; } .okc { color: #3fb950; } .errc { color: #f66; }
  .btns { display: flex; gap: .5rem; align-items: center; margin: .5rem 0; flex-wrap: wrap; }
  .log { background: #0e1115; border-radius: 6px; padding: .5rem; max-height: 22rem; overflow: auto; font: 12px/1.45 ui-monospace, monospace; }
  .ln { white-space: pre-wrap; word-break: break-all; } .t { opacity: .5; } .n { opacity: .6; }
  .WARNING b { color: #c9a227; } .ERROR b, .CRITICAL b { color: #f66; }
  .msg { background: #1c2128; padding: .4rem .7rem; border-radius: 6px; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .3rem .7rem; cursor: pointer; } a { color: #6ea0ff; }
</style>
