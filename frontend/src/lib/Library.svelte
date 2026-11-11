<script lang="ts">
  import { api, type Movie, type Series } from './api'
  import AddNew from './AddNew.svelte'
  import AddTorrent from './AddTorrent.svelte'
  import AZRail from './AZRail.svelte'
  import Grid from './Grid.svelte'
  import MovieDetail from './MovieDetail.svelte'
  import Releases from './Releases.svelte'
  import SeriesDetail from './SeriesDetail.svelte'
  import { auth } from './auth.svelte'
  import { nav } from './nav.svelte'
  import { letterOf, sortKey } from './sort'
  const admin = $derived(!auth.user || auth.user.is_admin)

  let { kind }: { kind: 'movies' | 'series' } = $props()
  type Item = Movie | Series
  let items = $state<Item[]>([])
  let loading = $state(true)
  let error = $state('')
  let msg = $state('')
  let releasesFor = $state<Movie | null>(null)
  let openSeries = $state<number | null>(null)
  let detailFor = $state<number | null>(null)
  let adding = $state(false)
  let addingTorrent = $state(false)

  let filter = $state('')
  let kidsAdults = $state('all')
  let status = $state('all')
  let active = $state('')

  async function load() {
    loading = true
    try { items = await api(`/${kind}`) } catch (e: any) { error = e.message }
    loading = false
  }
  async function remove(id: number) {
    if (!confirm('Remove from the library?')) return
    const files = confirm('Also DELETE its files from disk?\n\nOK = delete the files too\nCancel = keep the files, just remove it from the library')
    await api(`/${kind}/${id}?delete_files=${files}`, 'DELETE')
    await load()
  }
  // From "Add & choose release": go straight to the interactive search for the new title.
  async function choose(type: 'movies' | 'series', id: number) {
    adding = false
    if (type === kind) await openChoice(type, id)
    else { nav.openMovie = type === 'movies' ? id : null; nav.openSeries = type === 'series' ? id : null; nav.page = type }
  }
  async function openChoice(type: string, id: number) {
    await load()
    if (type === 'movies') releasesFor = items.find((m) => m.id === id) as Movie ?? null
    else openSeries = id
  }
  $effect(() => {
    if (loading) return
    if (kind === 'movies' && nav.openMovie !== null) { const id = nav.openMovie; nav.openMovie = null; openChoice('movies', id) }
    if (kind === 'movies' && nav.showMovie !== null) { detailFor = nav.showMovie; nav.showMovie = null }
    if (kind === 'series' && nav.openSeries !== null) { const id = nav.openSeries; nav.openSeries = null; openChoice('series', id) }
  })

  async function autoSearch(id: number) {
    msg = 'Searching…'
    try {
      const r = await api<{ grabbed: string | null }>(`/movies/${id}/search`, 'POST')
      msg = r.grabbed ? `Grabbed ${r.grabbed}` : 'No suitable release found'
    } catch (e: any) { msg = e.message }
  }
  $effect(() => { kind; openSeries = null; filter = ''; kidsAdults = 'all'; status = 'all'; load() })

  const filtered = $derived.by(() => {
    const f = filter.trim().toLowerCase()
    return items
      .filter((i) => !f || i.title.toLowerCase().includes(f) || sortKey(i.title).includes(f))
      .filter((i) => {
        if (kind === 'movies') {
          const m = i as Movie
          if (kidsAdults !== 'all' && m.root_kind !== `movies_${kidsAdults}`) return false
          if (status === 'disk') return m.has_file
          if (status === 'missing') return !m.has_file
        } else {
          const s = i as Series
          if (status === 'monitored') return s.monitored
          if (status === 'unmonitored') return !s.monitored
          if (status === 'incomplete') return s.file_count < s.episode_count
        }
        return true
      })
      .sort((a, b) => sortKey(a.title).localeCompare(sortKey(b.title)))
  })

  const sections = $derived.by(() => {
    const map = new Map<string, Item[]>()
    for (const i of filtered) {
      const l = letterOf(i.title)
      map.set(l, [...(map.get(l) ?? []), i])
    }
    return [...map.entries()].sort(([a], [b]) => (a === '#' ? -1 : b === '#' ? 1 : a.localeCompare(b)))
  })
  const available = $derived(new Set(sections.map(([l]) => l)))

  function badge(i: Item): string {
    if (kind === 'movies') {
      const m = i as Movie
      return `${m.root_kind?.replace('movies_', '') ?? ''} · ${m.has_file ? 'on disk' : 'missing'}`
    }
    const s = i as Series
    return `${s.file_count}/${s.episode_count} episodes${s.monitored ? '' : ' · unmonitored'}`
  }

  function jump(l: string) {
    document.getElementById(`letter-${l === '#' ? 'num' : l}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function onscroll() {
    let cur = ''
    for (const [l] of sections) {
      const el = document.getElementById(`letter-${l === '#' ? 'num' : l}`)
      if (el && el.getBoundingClientRect().top <= 90) cur = l
    }
    active = cur
  }
</script>

<svelte:window {onscroll} />

{#if openSeries !== null}
  <SeriesDetail id={openSeries} onback={() => { openSeries = null; load() }} />
{:else}
  <div class="toolbar">
    <input class="search" bind:value={filter} placeholder={`Filter ${kind}…`} />
    {#if kind === 'movies'}
      <select bind:value={kidsAdults}><option value="all">Kids + adults</option><option value="kids">Kids</option><option value="adults">Adults</option></select>
      <select bind:value={status}><option value="all">All</option><option value="disk">On disk</option><option value="missing">Missing</option></select>
    {:else}
      <select bind:value={status}>
        <option value="all">All</option><option value="monitored">Monitored</option>
        <option value="unmonitored">Unmonitored</option><option value="incomplete">Incomplete</option>
      </select>
    {/if}
    <span class="count">{filtered.length}{filtered.length !== items.length ? ` / ${items.length}` : ''}</span>
    {#if admin}<button class="add alt" onclick={() => (addingTorrent = true)}>+ Torrent / magnet</button>{/if}
    <button class="add2" onclick={() => (adding = true)}>{admin ? '+ Add new' : '+ Request'}</button>
  </div>

  {#if error}<p class="err">{error}</p>{/if}
  {#if msg}<p>{msg}</p>{/if}
  {#if loading}<p>Loading…</p>
  {:else if items.length === 0}<p>Nothing here yet. Use “Add new” to add something.</p>
  {:else if filtered.length === 0}<p>No matches.</p>{/if}

  <div class="body">
    {#each sections as [letter, list] (letter)}
      <section id={`letter-${letter === '#' ? 'num' : letter}`}>
        <h2>{letter}</h2>
        <Grid items={list.map((i) => ({ ...i, badge: badge(i) }))} onremove={admin ? remove : undefined}
          onopen={kind === 'series' ? (id) => (openSeries = id) : (id) => (detailFor = id)}
          actions={kind === 'series' && admin ? [{ label: '🔍 Find releases', run: (id) => (openSeries = id), primary: true }] : kind === 'movies' && admin ? [
            { label: 'Search (auto)', run: autoSearch },
            { label: '🔍 Interactive search', run: (id) => (releasesFor = items.find((m) => m.id === id) as Movie), primary: true },
          ] : undefined} />
      </section>
    {/each}
  </div>

  <AZRail {available} {active} onjump={jump} />

  {#if addingTorrent}<AddTorrent {kind} onclose={() => (addingTorrent = false)} onadded={load} />{/if}
  {#if adding}<AddNew {kind} onclose={() => (adding = false)} onadded={load} onchoose={choose} />{/if}
  {#if detailFor !== null}<MovieDetail id={detailFor} onclose={() => (detailFor = null)} onchanged={load} onsearch={(m) => (releasesFor = m)} />{/if}
  {#if releasesFor}
    <Releases path={`/movies/${releasesFor.id}/releases`} grabBody={{ movie_id: releasesFor.id }} onclose={() => (releasesFor = null)} />
  {/if}
{/if}

<style>
  .toolbar { position: sticky; top: 0; z-index: 4; display: flex; gap: .5rem; align-items: center; background: #14171ccc;
    backdrop-filter: blur(6px); padding: .6rem 0; margin-bottom: .5rem; }
  .search { flex: 1; max-width: 26rem; padding: .45rem .6rem; }
  select { padding: .4rem; }
  .count { opacity: .7; font-size: .85rem; }
  .add, .add2 { background: #3b6fd8; color: #fff; border: 0; border-radius: 6px; padding: .45rem .9rem; cursor: pointer; }
  .add { margin-left: auto; } .add.alt { background: #2b3340; } .add2 { margin-right: 2.2rem; }
  .body { padding-right: 2.2rem; }
  section { scroll-margin-top: 4rem; content-visibility: auto; contain-intrinsic-size: 1px 400px; }
  h2 { margin: 1.2rem 0 .5rem; border-bottom: 1px solid #2b3340; padding-bottom: .2rem; }
  .err { color: #f66; }
</style>
