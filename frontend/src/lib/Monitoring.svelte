<script lang="ts">
  import { api } from './api'
  import { nav } from './nav.svelte'

  type Summary = { movies_monitored: number; movies_total: number; series_monitored: number; series_total: number; albums_monitored: number; protect_existing: boolean }
  type SeriesRow = { id: number; title: string; status: string | null; missing: number; downloading: number; upcoming: number; next_air: string | null }
  type MovieRow = { id: number; title: string; year: number | null; downloading: boolean; release_date: string | null }
  type AlbumRow = { id: number; title: string; downloading: boolean }
  let data = $state<{ summary: Summary; series: SeriesRow[]; movies: MovieRow[]; albums: AlbumRow[] } | null>(null)
  let error = $state('')
  let filter = $state('')

  async function load() {
    try { data = await api('/wanted') } catch (e: any) { error = e.message }
  }
  $effect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) })

  const f = $derived(filter.trim().toLowerCase())
  const series = $derived(data?.series.filter((s) => !f || s.title.toLowerCase().includes(f)) ?? [])
  const searching = $derived(series.filter((s) => s.missing > 0))
  const watching = $derived(series.filter((s) => s.missing === 0))
  const movies = $derived(data?.movies.filter((m) => !f || m.title.toLowerCase().includes(f)) ?? [])

  const openSeries = (id: number) => { nav.openSeries = id; nav.page = 'series' }
  const openMovie = (id: number) => { nav.showMovie = id; nav.page = 'movies' }
</script>

{#if error}<p class="err">{error}</p>{/if}
{#if data}
  <div class="cards">
    <div><b>{data.summary.series_monitored}</b><small>of {data.summary.series_total} series monitored</small></div>
    <div><b>{data.summary.movies_monitored}</b><small>of {data.summary.movies_total} movies monitored</small></div>
    <div><b>{data.summary.albums_monitored}</b><small>albums monitored</small></div>
    <div><b>{searching.length + movies.length + data.albums.length}</b><small>being searched for</small></div>
  </div>
  <p class="note" class:on={data.summary.protect_existing}>
    {data.summary.protect_existing
      ? '🛡 Existing files are protected: anything already in your library is never searched for, replaced or deleted.'
      : '⚠ Existing-file protection is OFF (Settings → Downloads): better releases may replace files you already have.'}
  </p>
  <input class="filter" bind:value={filter} placeholder="Filter…" />

  <h3>Searching for ({searching.length + movies.length + data.albums.length})</h3>
  <p><small>Checked every hour, and new releases every 15 minutes. Nothing here means nothing is missing.</small></p>
  {#if searching.length + movies.length + data.albums.length === 0}<p>Nothing is missing. 🎉</p>{/if}
  <table>
    <tbody>
      {#each searching as s (s.id)}
        <tr>
          <td><button class="link" onclick={() => openSeries(s.id)}>{s.title}</button> <small>series</small></td>
          <td><b>{s.missing}</b> missing episode{s.missing === 1 ? '' : 's'}</td>
          <td>{s.downloading ? `⬇ ${s.downloading} downloading` : ''}</td>
          <td>{s.upcoming ? `${s.upcoming} upcoming` : ''}</td>
        </tr>
      {/each}
      {#each movies as m (m.id)}
        <tr>
          <td><button class="link" onclick={() => openMovie(m.id)}>{m.title}</button> <small>movie {m.year ?? ''}</small></td>
          <td>missing</td>
          <td>{m.downloading ? '⬇ downloading' : ''}</td>
          <td>{m.release_date && m.release_date > new Date().toISOString().slice(0, 10) ? `releases ${m.release_date}` : ''}</td>
        </tr>
      {/each}
      {#each data.albums as a (a.id)}
        <tr><td>{a.title} <small>album</small></td><td>missing</td><td>{a.downloading ? '⬇ downloading' : ''}</td><td></td></tr>
      {/each}
    </tbody>
  </table>

  <h3>Watching for new episodes ({watching.length})</h3>
  <p><small>Monitored series that have everything aired so far. New episodes are picked up automatically (list refreshed every 6 hours).</small></p>
  <table>
    <tbody>
      {#each watching as s (s.id)}
        <tr>
          <td><button class="link" onclick={() => openSeries(s.id)}>{s.title}</button></td>
          <td>{s.status ?? ''}</td>
          <td>{s.next_air ? `next episode ${s.next_air}` : s.upcoming ? 'date not announced' : 'nothing scheduled'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else if !error}
  <p>Loading…</p>
{/if}

<style>
  .cards { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
  .cards div { background: #1c2128; border-radius: 8px; padding: .8rem 1.2rem; display: flex; flex-direction: column; min-width: 9rem; }
  .cards b { font-size: 1.6rem; }
  .note { padding: .5rem .8rem; border-radius: 6px; background: #3a2e12; }
  .note.on { background: #14301d; }
  .filter { padding: .4rem .6rem; width: 18rem; margin: .5rem 0; }
  td { padding: .25rem 1rem .25rem 0; }
  .link { background: none; border: 0; color: #6ea0ff; cursor: pointer; padding: 0; font: inherit; text-decoration: underline; }
  .err { color: #f66; }
</style>
