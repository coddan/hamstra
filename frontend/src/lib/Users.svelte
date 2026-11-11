<script lang="ts">
  import { api } from './api'
  import { auth } from './auth.svelte'

  type U = { id: number; username: string; is_admin: boolean }
  let users = $state<U[]>([])
  let form = $state({ username: '', password: '', is_admin: false })
  let msg = $state('')

  async function load() { if (auth.user?.is_admin) users = await api('/users') }
  async function add() {
    try { await api('/users', 'POST', form); form = { username: '', password: '', is_admin: false }; msg = 'User added'; await load() }
    catch (e: any) { msg = e.message }
  }
  async function del(id: number) {
    try { await api(`/users/${id}`, 'DELETE'); await load() } catch (e: any) { msg = e.message }
  }
  async function reset(id: number) {
    const password = prompt('New password (min 8 characters)')
    if (!password) return
    try { await api(`/users/${id}/password`, 'PUT', { password }); msg = 'Password changed' } catch (e: any) { msg = e.message }
  }
  $effect(() => { load() })
</script>

<h3>Users</h3>
{#if !auth.user}
  <p>No accounts yet. Sign-in is not required until the first account exists.</p>
{:else if auth.user.is_admin}
  {#each users as u (u.id)}
    <div class="row">
      <span class="grow">{u.username} {u.is_admin ? '(admin)' : ''}</span>
      <button onclick={() => reset(u.id)}>Change password</button>
      <button onclick={() => del(u.id)} disabled={u.id === auth.user?.id}>Delete</button>
    </div>
  {/each}
  <form onsubmit={(e) => { e.preventDefault(); add() }}>
    <input placeholder="Username" bind:value={form.username} required />
    <input type="password" placeholder="Password (min 8)" bind:value={form.password} required />
    <label><input type="checkbox" bind:checked={form.is_admin} /> Admin</label>
    <button>Add user</button>
  </form>
{:else}
  <button onclick={() => auth.user && reset(auth.user.id)}>Change my password</button>
{/if}
<p>{msg}</p>

<style>
  .row { display: flex; gap: .5rem; align-items: center; background: #1c2128; padding: .4rem .6rem; margin-bottom: .3rem; border-radius: 6px; max-width: 34rem; }
  .grow { flex: 1; }
  form { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .6rem; align-items: center; }
  input:not([type='checkbox']) { padding: .35rem; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .3rem .6rem; cursor: pointer; }
</style>
