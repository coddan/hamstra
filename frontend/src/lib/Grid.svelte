<script lang="ts">
  let { items, onremove, onopen, onmonitor, actions }: {
    items: { id: number; title: string; year: number | null; poster_url: string | null; badge?: string; monitored?: boolean }[]
    onremove?: (id: number) => void
    onopen?: (id: number) => void
    onmonitor?: (id: number, value: boolean) => void
    actions?: { label: string; run: (id: number) => void; primary?: boolean }[]
  } = $props()
</script>

<div class="grid">
  {#each items as i (i.id)}
    <div class="card">
      <div class="wrap">
        <button class="poster" onclick={() => onopen?.(i.id)} disabled={!onopen}>
          {#if i.poster_url}<img src={i.poster_url} alt={i.title} loading="lazy" decoding="async" />{:else}<div class="noimg"></div>{/if}
        </button>
        {#if i.monitored !== undefined}
          <button class="mon" class:on={i.monitored} disabled={!onmonitor}
            title={onmonitor ? (i.monitored ? 'Monitored: click to stop' : 'Not monitored: click to start') : ''}
            onclick={() => onmonitor?.(i.id, !i.monitored)}>{i.monitored ? '👁 Monitored' : '🚫 Not monitored'}</button>
        {/if}
      </div>
      <div class="meta">
        <strong>{i.title}</strong> <span>{i.year ?? ''}</span>
        {#if i.badge}<em>{i.badge}</em>{/if}
        <div class="row">
          {#each actions ?? [] as a}<button class:primary={a.primary} onclick={() => a.run(i.id)}>{a.label}</button>{/each}
          {#if onremove}<button class="danger" onclick={() => onremove(i.id)}>Remove</button>{/if}
        </div>
      </div>
    </div>
  {/each}
</div>

<style>
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 1rem; }
  .card { background: #1c2128; border-radius: 8px; overflow: hidden; }
  .wrap { position: relative; }
  .poster { padding: 0; border: 0; background: none; width: 100%; cursor: pointer; display: block; }
  img, .noimg { width: 100%; aspect-ratio: 2/3; object-fit: cover; background: #2b3340; display: block; }
  .meta { padding: .5rem; font-size: .85rem; display: flex; flex-direction: column; gap: .25rem; }
  .row { display: flex; gap: .25rem; flex-wrap: wrap; }
  span, em { opacity: .7; font-style: normal; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .2rem .5rem; cursor: pointer; }
  .danger { background: #3a2226; color: #f99; }
  .primary { background: #3b6fd8; color: #fff; width: 100%; padding: .35rem .5rem; }
  .mon { position: absolute; top: .4rem; left: .4rem; font-size: .7rem; padding: .15rem .45rem; border-radius: 999px;
    background: #000a; color: #bbb; backdrop-filter: blur(4px); }
  .mon.on { background: #1f6f3acc; color: #d6ffe2; }
  .mon:disabled { cursor: default; }
</style>
