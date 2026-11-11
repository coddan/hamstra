<script lang="ts">
  import { api } from './api'

  type P = { id: number; name: string; is_default: boolean; resolutions: number[]; cutoff: number; sources: string[]
    source_order: string[]; prefer_codec: string | null; prefer_hdr: boolean; prefer_words: string; reject_words: string
    min_seeders: number; max_size_gb_movie: number; max_size_mb_episode: number; upgrade_allowed: boolean; in_use: number }

  const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
  const RES = [480, 576, 720, 1080, 2160]
  const SRC_LABEL: Record<string, string> = { remux: 'Remux', bluray: 'BluRay', 'web-dl': 'WEB-DL', webrip: 'WEBRip', hdtv: 'HDTV', dvd: 'DVD' }

  let profiles = $state<P[]>([])
  let sel = $state<P | null>(null)
  let msg = $state('')

  async function load(keep?: number) {
    profiles = await api('/profiles')
    sel = clone(profiles.find((p) => p.id === (keep ?? sel?.id)) ?? profiles[0] ?? null)
  }
  $effect(() => { load() })

  function toggle(list: number[] | string[], v: any) {
    const i = (list as any[]).indexOf(v)
    if (i >= 0) (list as any[]).splice(i, 1); else (list as any[]).push(v)
  }
  function move(i: number, d: number) {
    if (!sel) return
    const o = sel.source_order
    const j = i + d
    if (j < 0 || j >= o.length) return;
    [o[i], o[j]] = [o[j], o[i]]
  }
  async function save() {
    if (!sel) return
    try { await api(`/profiles/${sel.id}`, 'PUT', sel); msg = 'Saved'; await load(sel.id) } catch (e: any) { msg = e.message }
  }
  async function add() {
    const name = prompt('Name of the new profile')
    if (!name) return
    try {
      const base = sel ? { ...sel, name } : { name }
      const p = await api<P>('/profiles', 'POST', base)
      await load(p.id)
    } catch (e: any) { msg = e.message }
  }
  async function makeDefault() { if (sel) { await api(`/profiles/${sel.id}/default`, 'POST'); await load(sel.id) } }
  async function remove() {
    if (!sel || !confirm(`Delete profile "${sel.name}"? Items using it switch to the default profile.`)) return
    try { await api(`/profiles/${sel.id}`, 'DELETE'); sel = null; await load() } catch (e: any) { msg = e.message }
  }
</script>

<div class="tabs">
  {#each profiles as p (p.id)}
    <button class:on={sel?.id === p.id} onclick={() => (sel = clone(p))}>{p.name}{p.is_default ? ' ★' : ''}</button>
  {/each}
  <button onclick={add}>+ New profile</button>
</div>

{#if sel}
  <div class="form">
    <label>Name <input bind:value={sel.name} /></label>

    <fieldset><legend>Allowed resolutions</legend>
      {#each RES as r}<label class="inline"><input type="checkbox" checked={sel.resolutions.includes(r)} onchange={() => sel && toggle(sel.resolutions, r)} /> {r}p</label>{/each}
    </fieldset>
    <label>Stop upgrading at
      <select bind:value={sel.cutoff}>{#each RES as r}<option value={r}>{r}p</option>{/each}</select>
    </label>
    <label class="inline"><input type="checkbox" bind:checked={sel.upgrade_allowed} /> Replace existing files with better releases (until the cutoff)</label>

    <fieldset><legend>Allowed sources</legend>
      {#each Object.keys(SRC_LABEL) as s}<label class="inline"><input type="checkbox" checked={sel.sources.includes(s)} onchange={() => sel && toggle(sel.sources, s)} /> {SRC_LABEL[s]}</label>{/each}
    </fieldset>

    <fieldset><legend>Preferred source order (best first)</legend>
      {#each sel.source_order as s, i (s)}
        <div class="ord" class:off={!sel.sources.includes(s)}>
          <span>{i + 1}. {SRC_LABEL[s]}</span>
          <button onclick={() => move(i, -1)} disabled={i === 0}>↑</button>
          <button onclick={() => move(i, 1)} disabled={i === sel.source_order.length - 1}>↓</button>
        </div>
      {/each}
    </fieldset>

    <label>Preferred codec <select bind:value={sel.prefer_codec}><option value="">no preference</option><option value="x265">x265 / HEVC</option><option value="x264">x264 / AVC</option><option value="av1">AV1</option></select></label>
    <label class="inline"><input type="checkbox" bind:checked={sel.prefer_hdr} /> Prefer HDR / Dolby Vision</label>
    <label>Preferred words (comma separated, e.g. swedish, nordic, swesub) <input bind:value={sel.prefer_words} />
      <span class="presets"><small>Quick preset:</small>
        <button type="button" onclick={() => sel && (sel.prefer_words = 'swedish, swesub, svenska, nordic')}>Prefer Swedish audio / subtitles</button>
        <button type="button" onclick={() => sel && (sel.prefer_words = '')}>No language preference</button></span></label>
    <label>Rejected words (e.g. hardsub, korsub) <input bind:value={sel.reject_words} /></label>

    <div class="row3">
      <label>Min seeders <input type="number" min="0" bind:value={sel.min_seeders} /></label>
      <label>Max movie size (GB) <input type="number" min="1" bind:value={sel.max_size_gb_movie} /></label>
      <label>Max episode size (MB) <input type="number" min="50" bind:value={sel.max_size_mb_episode} /></label>
    </div>

    <p><small>Used by {sel.in_use} item(s). {sel.is_default ? 'This is the default profile for new items.' : ''}</small></p>
    <div class="btns">
      <button class="primary" onclick={save}>Save</button>
      {#if !sel.is_default}<button onclick={makeDefault}>Make default</button>{/if}
      <button class="danger" onclick={remove}>Delete</button>
    </div>
  </div>
{/if}
<p>{msg}</p>

<style>
  .tabs { display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: 1rem; }
  .tabs .on { background: #3b6fd8; }
  .form { display: flex; flex-direction: column; gap: .7rem; max-width: 34rem; }
  label { display: flex; flex-direction: column; gap: .2rem; } label.inline { flex-direction: row; align-items: center; gap: .4rem; display: inline-flex; margin-right: 1rem; }
  fieldset { border: 1px solid #2b3340; border-radius: 6px; } legend { padding: 0 .4rem; opacity: .8; }
  .presets { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; margin-top: .2rem; } .presets button { padding: .2rem .6rem; font-size: .8rem; }
  .ord { display: flex; gap: .4rem; align-items: center; } .ord span { width: 8rem; } .ord.off { opacity: .4; }
  .row3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: .6rem; } input:not([type='checkbox']), select { padding: .35rem; }
  .btns { display: flex; gap: .5rem; } button { background: #2b3340; color: inherit; border: 0; border-radius: 5px; padding: .35rem .8rem; cursor: pointer; }
  button.primary { background: #3b6fd8; color: #fff; } button.danger { background: #3a2226; color: #f99; }
</style>
