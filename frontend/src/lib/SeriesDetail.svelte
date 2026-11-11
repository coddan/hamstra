<script lang="ts">
  import { api } from './api'
  import { auth } from './auth.svelte'
  const admin = $derived(!auth.user || auth.user.is_admin)
  import Releases from './Releases.svelte'

  type Ep = { id: number; season: number; number: number; title: string | null; air_date: string | null; has_file: boolean; absolute?: number | null }
  let { id, onback }: { id: number; onback: () => void } = $props()
  let s = $state<any>(null)
  let msg = $state('')
  let releases = $state<Ep | null>(null)
  let seasonReleases = $state<number | null>(null)
  let profiles = $state<{ id: number; name: string }[]>([])
  $effect(() => { api<typeof profiles>('/profiles').then((p) => (profiles = p)) })
  async function setProfile(pid: number) { await api(`/series/${id}`, 'PATCH', { quality_profile_id: pid }); s = await api(`/series/${id}`) }

  $effect(() => { api(`/series/${id}`).then((r) => (s = r)) })

  const seasons = $derived(s ? [...new Set((s.episodes as Ep[]).map((e) => e.season))].sort((a, b) => (a === 0 ? 1 : b === 0 ? -1 : a - b)) : [])

  async function searchAll() {
    msg = 'Searching for everything missing…'
    try {
      const r = await api<{ searched: number; grabbed: number }>(`/series/${id}/search`, 'POST')
      msg = `Searched ${r.searched} item(s), grabbed ${r.grabbed}`
    } catch (e: any) { msg = e.message }
  }
  async function refresh() {
    msg = 'Refreshing from TVmaze…'
    try { const r = await api<{ added: number; changed: number }>(`/series/${id}/refresh`, 'POST'); msg = `${r.added} new episode(s), ${r.changed} updated`; s = await api(`/series/${id}`) } catch (e: any) { msg = e.message }
  }
  async function removeSeries() {
    if (!s || !confirm(`Remove "${s.title}" from the library?`)) return
    const files = s.file_count > 0 && confirm('Also DELETE its files from disk?\n\nOK = delete the files too\nCancel = keep the files, only remove it from the library')
    try { await api(`/series/${id}?delete_files=${files}`, 'DELETE'); onback() } catch (e: any) { msg = e.message }
  }
  async function setAbsolute(v: boolean) {
    await api(`/series/${id}`, 'PATCH', { absolute_numbering: v })
    s = await api(`/series/${id}`)
  }
  async function setMonitored(v: boolean) {
    await api(`/series/${id}`, 'PATCH', { monitored: v })
    s = await api(`/series/${id}`)
  }

  async function searchSeason(n: number) {
    msg = 'Searching for a season pack…'
    const r = await api<{ grabbed: string | null; detail?: string }>(`/series/${id}/seasons/${n}/search`, 'POST')
    msg = r.grabbed ? `Grabbed ${r.grabbed}` : r.detail ?? 'No suitable season pack found'
  }

  async function search(e: Ep) {
    msg = 'Searching…'
    const r = await api<{ grabbed: string | null }>(`/series/${id}/episodes/${e.id}/search`, 'POST')
    msg = r.grabbed ? `Grabbed ${r.grabbed}` : 'No suitable release found'
  }
</script>

<button onclick={onback}>← Back</button>
{#if s}
  <h2>{s.title} <small>{s.year ?? ''}</small></h2>
  <div class="opts"><label><input type="checkbox" checked={s.monitored} onchange={(ev) => setMonitored(ev.currentTarget.checked)} /> Monitored (search and download missing episodes automatically)</label>
  <label title="For anime: releases are named 'Show - 137' without a season. Hamstra counts episodes across seasons to match them. Check that the numbering matches your releases."><input type="checkbox" checked={s.absolute_numbering} onchange={(ev) => setAbsolute(ev.currentTarget.checked)} /> Absolute numbering (anime)</label>
  <label>Quality profile <select value={s.quality_profile_id} onchange={(e) => setProfile(Number(e.currentTarget.value))}>{#each profiles as p}<option value={p.id}>{p.name}</option>{/each}</select></label></div>
  <p>{s.overview ?? ''}</p>
  {#if admin}
    <div class="finder">
      <b>Find releases</b>
      <button onclick={searchAll}>Search all missing (automatic)</button>
      <button onclick={refresh}>Refresh episode list</button>
      <button class="rm" onclick={removeSeries}>Remove from library…</button>
      <small>For interactive search pick a season below and press <b>Season releases</b>, or <b>Releases</b> on a single episode.</small>
    </div>
  {/if}
  {#if msg}<p>{msg}</p>{/if}
  {#each seasons as n}
    <details open={n !== 0 && (seasons.length <= 3 || n === seasons.filter((x) => x !== 0).slice(-1)[0])}>
      <summary>{n === 0 ? 'Specials' : `Season ${n}`} {#if n === 0}<small>(not searched automatically; use Auto or Releases on an episode)</small> {/if}{#if admin && n !== 0}<button onclick={(ev) => { ev.preventDefault(); searchSeason(n) }}>Auto-search pack</button> <button onclick={(ev) => { ev.preventDefault(); seasonReleases = n }}>Season releases</button>{/if}</summary>
      <table>
        <tbody>
          {#each (s.episodes as Ep[]).filter((e) => e.season === n) as e}
            <tr>
              <td>{e.number}{#if e.absolute}<small title="absolute number"> (#{e.absolute})</small>{/if}</td><td>{e.title}</td><td>{e.air_date ?? ''}</td>
              <td>{e.has_file ? '✓' : '—'}</td>
              <td>{#if admin}<button onclick={() => search(e)}>Auto</button> <button onclick={() => (releases = e)}>Releases</button>{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </details>
  {/each}
  {#if seasonReleases !== null}
    <Releases path={`/series/${id}/seasons/${seasonReleases}/releases`} grabBody={{ series_id: id, season: seasonReleases }} onclose={() => (seasonReleases = null)} />
  {/if}
  {#if releases}
    <Releases path={`/series/${id}/episodes/${releases.id}/releases`} grabBody={{ series_id: id, episode_id: releases.id }} onclose={() => (releases = null)} />
  {/if}
{/if}

<style>
  td { padding: .25rem .6rem; }
  .rm { background: #3a2226; color: #f99; margin-left: auto; }
  .opts { display: flex; gap: 2rem; align-items: center; flex-wrap: wrap; margin: .4rem 0; }
  .finder { display: flex; gap: .8rem; align-items: center; flex-wrap: wrap; background: #1c2128; padding: .6rem .8rem; border-radius: 8px; margin: .6rem 0; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .2rem .5rem; cursor: pointer; }
</style>
