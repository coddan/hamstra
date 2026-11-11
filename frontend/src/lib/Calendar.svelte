<script lang="ts">
  import { api } from './api'
  import { nav } from './nav.svelte'

  type Ev = { type: 'episode' | 'movie'; date: string; series: string; series_id?: number; movie_id?: number; season: number | null
    number: number | null; title: string | null; has_file: boolean; monitored: boolean }

  const pad = (n: number) => String(n).padStart(2, '0')
  const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  const todayIso = iso(new Date())
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  let { compact = false }: { compact?: boolean } = $props()
  let view = $state(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
  let events = $state<Ev[]>([])
  let loading = $state(true)
  let onlyMonitored = $state(false)
  let selected = $state<string | null>(null)
  let upcoming = $state<Ev[]>([])

  // the grid starts on the Monday of the first week and ends on the Sunday of the last week
  const days = $derived.by(() => {
    const first = new Date(view.getFullYear(), view.getMonth(), 1)
    const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7))
    const last = new Date(view.getFullYear(), view.getMonth() + 1, 0)
    const end = new Date(last); end.setDate(last.getDate() + (6 - ((last.getDay() + 6) % 7)))
    const out: Date[] = []
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) out.push(new Date(d))
    return out
  })

  async function load() {
    loading = true
    const r = await api<Ev[]>(`/calendar?start=${iso(days[0])}&end=${iso(days[days.length - 1])}`)
    events = r; loading = false
  }
  $effect(() => { view; load() })
  $effect(() => {
    const t = new Date(); const end = new Date(); end.setDate(t.getDate() + 7)
    api<Ev[]>(`/calendar?start=${iso(t)}&end=${iso(end)}`).then((r) => (upcoming = r))
  })

  const byDay = $derived.by(() => {
    const m = new Map<string, Ev[]>()
    for (const e of events) if (!onlyMonitored || e.monitored) m.set(e.date, [...(m.get(e.date) ?? []), e])
    return m
  })
  const label = (e: Ev) => e.type === 'movie' ? e.series : `${e.series} S${pad(e.season ?? 0)}E${pad(e.number ?? 0)}`
  const kindOf = (e: Ev) => (e.has_file ? 'have' : e.date < todayIso ? 'missing' : 'soon')
  const move = (n: number) => { view = new Date(view.getFullYear(), view.getMonth() + n, 1); selected = null }
  const goToday = () => { view = new Date(new Date().getFullYear(), new Date().getMonth(), 1); selected = todayIso }

  function open(e: Ev) {
    if (e.type === 'episode' && e.series_id) { nav.openSeries = e.series_id; nav.page = 'series' }
    else if (e.movie_id) { nav.showMovie = e.movie_id; nav.page = 'movies' }
  }
  const monthCount = $derived([...byDay.entries()].filter(([d]) => d.startsWith(`${view.getFullYear()}-${pad(view.getMonth() + 1)}`)).reduce((a, [, l]) => a + l.length, 0))
  const dayName = (d: string) => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
</script>

<div class="cal" class:compact>
  <div class="head">
    <button onclick={() => move(-1)} aria-label="Previous month">‹</button>
    <h2>{MONTHS[view.getMonth()]} {view.getFullYear()}</h2>
    <button onclick={() => move(1)} aria-label="Next month">›</button>
    <button class="today" onclick={goToday}>Today</button>
    <span class="count">{monthCount} release{monthCount === 1 ? '' : 's'} this month</span>
    <label class="mon"><input type="checkbox" bind:checked={onlyMonitored} /> only monitored</label>
  </div>

  <div class="legend"><span class="dot soon"></span>upcoming <span class="dot have"></span>on disk <span class="dot missing"></span>aired, missing <span class="dot movie"></span>movie</div>

  <div class="layout">
    <div class="grid" class:loading>
      {#each WEEKDAYS as w}<div class="wd">{w}</div>{/each}
      {#each days as d (iso(d))}
        {@const key = iso(d)}
        {@const items = byDay.get(key) ?? []}
        <div class="day" class:out={d.getMonth() !== view.getMonth()} class:today={key === todayIso} class:sel={selected === key}
          role="button" tabindex="0" onclick={() => (selected = selected === key ? null : key)} onkeydown={(e) => e.key === 'Enter' && (selected = key)}>
          <div class="num">{d.getDate()}</div>
          {#each items.slice(0, compact ? 2 : 4) as e}
            <button class="ev {kindOf(e)}" class:movie={e.type === 'movie'} title={`${label(e)}${e.title && e.type === 'episode' ? ' – ' + e.title : ''}`}
              onclick={(ev) => { ev.stopPropagation(); open(e) }}>{e.type === 'movie' ? '🎬 ' : ''}{label(e)}</button>
          {/each}
          {#if items.length > (compact ? 2 : 4)}<div class="more">+{items.length - (compact ? 2 : 4)} more</div>{/if}
        </div>
      {/each}
    </div>

    {#if !compact}
      <aside>
        {#if selected}
          <h3>{dayName(selected)}</h3>
          {#each byDay.get(selected) ?? [] as e}
            <button class="row {kindOf(e)}" onclick={() => open(e)}><b>{label(e)}</b>{#if e.type === 'episode' && e.title}<br /><small>{e.title}</small>{/if}</button>
          {:else}<p><small>Nothing on this day.</small></p>{/each}
        {:else}
          <h3>Next 7 days</h3>
          {#each upcoming as e}
            <button class="row {kindOf(e)}" onclick={() => open(e)}><small>{e.date}</small><br /><b>{label(e)}</b>{#if e.type === 'episode' && e.title}<br /><small>{e.title}</small>{/if}</button>
          {:else}<p><small>Nothing in the next 7 days.</small></p>{/each}
        {/if}
      </aside>
    {/if}
  </div>
</div>

<style>
  .head { display: flex; align-items: center; gap: .6rem; margin-bottom: .4rem; flex-wrap: wrap; } h2 { margin: 0; min-width: 11rem; text-align: center; }
  .head button { background: #2b3340; color: inherit; border: 0; border-radius: 6px; padding: .3rem .8rem; cursor: pointer; font-size: 1rem; } .today { font-size: .85rem !important; }
  .count { opacity: .7; font-size: .85rem; margin-left: auto; } .mon { font-size: .85rem; display: flex; gap: .3rem; align-items: center; }
  .legend { font-size: .78rem; opacity: .85; display: flex; gap: .5rem; align-items: center; margin-bottom: .5rem; }
  .dot { width: .7rem; height: .7rem; border-radius: 3px; display: inline-block; } .dot.soon { background: #c9a227; } .dot.have { background: #3fb950; } .dot.missing { background: #e5534b; } .dot.movie { background: #6a8dff; }
  .layout { display: grid; grid-template-columns: 1fr; gap: 1rem; } .cal:not(.compact) .layout { grid-template-columns: minmax(0, 1fr) 17rem; }
  .grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 3px; } .grid.loading { opacity: .6; }
  .wd { text-align: center; font-size: .75rem; opacity: .7; padding: .2rem 0; }
  .day { background: #1c2128; border-radius: 6px; min-height: 6.2rem; padding: .25rem; display: flex; flex-direction: column; gap: 2px; cursor: pointer; overflow: hidden; }
  .compact .day { min-height: 4.4rem; } .day.out { opacity: .4; } .day.today { outline: 2px solid #3b6fd8; } .day.sel { background: #26324a; }
  .num { font-size: .75rem; opacity: .8; text-align: right; } .day.today .num { color: #6ea0ff; font-weight: 700; }
  .ev { text-align: left; border: 0; border-left: 3px solid; background: #14171c; color: inherit; border-radius: 3px; padding: .1rem .3rem; font-size: .72rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
  .ev.soon, .row.soon { border-color: #c9a227; } .ev.have, .row.have { border-color: #3fb950; } .ev.missing, .row.missing { border-color: #e5534b; } .ev.movie { background: #1d2a44; }
  .more { font-size: .68rem; opacity: .7; padding-left: .3rem; }
  aside h3 { margin-top: 0; font-size: 1rem; } .row { display: block; width: 100%; text-align: left; background: #1c2128; color: inherit; border: 0; border-left: 3px solid #c9a227; border-radius: 6px; padding: .4rem .6rem; margin-bottom: .3rem; cursor: pointer; }
  @media (max-width: 1100px) { .cal:not(.compact) .layout { grid-template-columns: 1fr; } }
</style>
