<script lang="ts">
  import { LETTERS } from './sort'

  let { available, active, onjump }: { available: Set<string>; active: string; onjump: (l: string) => void } = $props()
</script>

<nav class="rail" aria-label="Jump to letter">
  {#each LETTERS as l}
    <button class:off={!available.has(l)} class:on={active === l} disabled={!available.has(l)} onclick={() => onjump(l)}>{l}</button>
  {/each}
</nav>

<style>
  .rail { position: fixed; right: .3rem; top: 50%; transform: translateY(-50%); display: flex; flex-direction: column;
    background: #1c2128cc; border-radius: 10px; padding: .25rem .1rem; z-index: 5; }
  button { background: none; border: 0; color: #cfd6df; font-size: .72rem; line-height: 1.15; padding: .06rem .4rem; cursor: pointer; border-radius: 4px; }
  button:hover:not(:disabled) { background: #3b6fd8; color: #fff; }
  .on { color: #fff; font-weight: bold; background: #2b3340; }
  .off { opacity: .25; cursor: default; }
</style>
