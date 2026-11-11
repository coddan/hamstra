<script lang="ts">
  import { api } from './api'

  type F = { id: number; path: string; kind: string; label: string; exists: boolean; writable: boolean; items: number }
  let kinds = $state<Record<string, string>>({})
  let folders = $state<F[]>([])
  let path = $state('')
  let kind = $state('movies')
  let msg = $state('')

  async function load() {
    const r = await api<{ kinds: Record<string, string>; folders: F[] }>('/rootfolders')
    kinds = r.kinds; folders = r.folders
  }
  $effect(() => { load() })

  async function add() {
    try { await api('/rootfolders', 'POST', { path, kind }); path = ''; msg = 'Added'; await load() } catch (e: any) { msg = e.message }
  }
  async function change(f: F, newKind: string) {
    try { await api(`/rootfolders/${f.id}`, 'PATCH', { path: f.path, kind: newKind }); msg = 'Saved' } catch (e: any) { msg = e.message }
    await load()
  }
  async function remove(f: F) {
    if (!confirm(`Remove ${f.path} from the app?\n\nNothing on disk is deleted.`)) return
    try { await api(`/rootfolders/${f.id}`, 'DELETE') }
    catch (e: any) {
      if (e.message.includes('items use this folder') && confirm(`${e.message}\n\nRemove it anyway?`)) await api(`/rootfolders/${f.id}?detach=true`, 'DELETE')
      else { msg = e.message; return }
    }
    msg = 'Removed'; await load()
  }
</script>

<h3>Media folders</h3>
<p><small>The folders the app looks after. The <b>type</b> tells it what a folder holds, so it knows whether to look for a movie or a series.
  Use <b>Movies and series</b> if one folder contains both: they are then told apart by name and file patterns.
  If a folder's contents clearly don't fit its type, the app flags it for you instead of guessing.</small></p>

{#each folders as f (f.id)}
  <div class="row">
    <div class="grow"><code>{f.path}</code>
      <small>{f.exists ? (f.writable ? '✓ found' : '⚠ found, but not writable') : '✗ not found'} · {f.items} item{f.items === 1 ? '' : 's'}</small></div>
    <select value={f.kind} onchange={(e) => change(f, e.currentTarget.value)}>
      {#each Object.entries(kinds) as [k, label]}<option value={k}>{label}</option>{/each}
    </select>
    <button class="danger" onclick={() => remove(f)}>Remove</button>
  </div>
{/each}

<form onsubmit={(e) => { e.preventDefault(); add() }}>
  <input placeholder="/full/path/to/folder" bind:value={path} required />
  <select bind:value={kind}>{#each Object.entries(kinds) as [k, label]}<option value={k}>{label}</option>{/each}</select>
  <button>Add folder</button>
</form>
{#if msg}<p class="msg">{msg}</p>{/if}

<style>
  .row { display: flex; gap: .6rem; align-items: center; background: #1c2128; padding: .45rem .7rem; border-radius: 6px; margin-bottom: .3rem; max-width: 52rem; }
  .grow { flex: 1; display: flex; flex-direction: column; gap: .1rem; word-break: break-all; }
  form { display: flex; gap: .5rem; margin-top: .6rem; max-width: 52rem; } form input { flex: 1; padding: .4rem; } select { padding: .35rem; }
  button { background: #3b6fd8; color: #fff; border: 0; border-radius: 5px; padding: .35rem .8rem; cursor: pointer; } button.danger { background: #3a2226; color: #f99; }
  .msg { background: #1c2128; padding: .4rem .7rem; border-radius: 6px; max-width: 52rem; } code { font-size: .85rem; }
</style>
