<script lang="ts">
  import { api } from './api'

  type P = { allowed: string[]; order: string[]; layout: string; min_seeders: number; max_size_mb: number; reject_words: string; prefer_words: string; all_qualities: string[] }
  let p = $state<P | null>(null)
  let msg = $state('')
  const label: Record<string, string> = { flac: 'FLAC (16 bit)', 'flac-24': 'FLAC 24 bit / hi-res', 'mp3-320': 'MP3 320', 'mp3-v0': 'MP3 V0', 'mp3-v1': 'MP3 V1', 'mp3-v2': 'MP3 V2',
    'mp3-256': 'MP3 256', 'mp3-192': 'MP3 192', 'mp3-128': 'MP3 128', 'mp3-unknown': 'MP3 (bitrate not stated)', aac: 'AAC / OGG' }

  $effect(() => { api<P>('/music/profile').then((r) => (p = r)) })
  function toggle(q: string) {
    if (!p) return
    const i = p.allowed.indexOf(q)
    if (i >= 0) p.allowed.splice(i, 1); else p.allowed.push(q)
  }
  function move(i: number, d: number) {
    if (!p) return
    const j = i + d
    if (j < 0 || j >= p.order.length) return;
    [p.order[i], p.order[j]] = [p.order[j], p.order[i]]
  }
  async function save() {
    if (!p) return
    try { p = await api<P>('/music/profile', 'PUT', p); msg = 'Saved' } catch (e: any) { msg = e.message }
  }
</script>

<p>Decides which music releases are accepted and which one is picked when several match. Used by automatic and interactive search.</p>
{#if p}
  <div class="form">
    <label>Folder layout
      <select bind:value={p.layout}>
        <option value="release">Genre / release folder (as your library is now: keeps the release's own folder name)</option>
        <option value="artist">Genre / Artist / Album (Year)</option>
      </select>
    </label>
    <fieldset><legend>Accept these qualities</legend>
      {#each p.all_qualities as q}<label class="inline"><input type="checkbox" checked={p.allowed.includes(q)} onchange={() => toggle(q)} /> {label[q] ?? q}</label>{/each}
    </fieldset>
    <fieldset><legend>Preference order (best first)</legend>
      {#each p.order as q, i (q)}
        <div class="ord" class:off={!p.allowed.includes(q)}><span>{i + 1}. {label[q] ?? q}</span>
          <button onclick={() => move(i, -1)} disabled={i === 0}>↑</button><button onclick={() => move(i, 1)} disabled={i === p.order.length - 1}>↓</button></div>
      {/each}
    </fieldset>
    <div class="row"><label>Min seeders <input type="number" min="0" bind:value={p.min_seeders} /></label>
      <label>Max size (MB) <input type="number" min="50" bind:value={p.max_size_mb} /></label></div>
    <label>Rejected words <input bind:value={p.reject_words} /><small>e.g. live, karaoke, tribute – ignored when the album's own title contains the word</small></label>
    <label>Preferred words <input bind:value={p.prefer_words} placeholder="e.g. remastered, deluxe" /></label>
    <div><button class="primary" onclick={save}>Save</button></div>
  </div>
{/if}
<p>{msg}</p>

<style>
  .form { display: flex; flex-direction: column; gap: .7rem; max-width: 34rem; }
  fieldset { border: 1px solid #2b3340; border-radius: 6px; } legend { padding: 0 .4rem; opacity: .8; }
  label { display: flex; flex-direction: column; gap: .2rem; } label.inline { flex-direction: row; align-items: center; gap: .4rem; display: flex; }
  .ord { display: flex; gap: .4rem; align-items: center; margin: .15rem 0; } .ord span { width: 14rem; } .ord.off { opacity: .4; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: .6rem; } input:not([type='checkbox']) { padding: .35rem; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 5px; padding: .3rem .7rem; cursor: pointer; } button.primary { background: #3b6fd8; color: #fff; padding: .4rem .9rem; }
</style>
