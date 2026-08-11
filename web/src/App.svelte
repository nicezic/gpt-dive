<script lang="ts">
  import { onMount } from 'svelte'

  type Speaker = 'USER' | 'SOL' | 'OPUS'
  type Target = 'SOL' | 'OPUS'
  type Turn = { speaker: Speaker; text: string }
  type RoomState = {
    ok: boolean
    title: string
    turns: Turn[]
    bridge_started: boolean
    head: string
    contexts: Record<Target, string>
  }
  type TurnResult = {
    ok: boolean
    participant?: Target
    error?: string
  }

  let draft = ''
  let selectedTarget: Target = 'SOL'
  let turns: Turn[] = []
  let roomTitle = 'Council'
  let bridgeStarted = false
  let loading = true
  let busy: Target | null = null
  let errorMessage = ''
  let failedTarget: Target | null = null

  onMount(() => {
    void refresh()
  })

  async function readJson<T>(response: Response): Promise<T> {
    const body = await response.json()
    if (!response.ok) {
      throw new Error(body?.error ?? `${response.status} ${response.statusText}`)
    }
    return body as T
  }

  async function refresh() {
    try {
      const state = await readJson<RoomState>(await fetch('/api/state'))
      roomTitle = state.title
      turns = state.turns
      bridgeStarted = state.bridge_started
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error)
    } finally {
      loading = false
    }
  }

  async function sendTo(target: Target) {
    const text = draft.trim()
    selectedTarget = target
    if (!text || busy) return

    busy = target
    errorMessage = ''
    failedTarget = null
    try {
      const result = await readJson<TurnResult>(
        await fetch('/api/turn', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ target, message: text })
        })
      )
      if (!result.ok) {
        errorMessage = result.error ?? `${target} turn failed`
        failedTarget = target
      } else {
        draft = ''
      }
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error)
      failedTarget = target
    } finally {
      await refresh()
      busy = null
    }
  }

  async function retry() {
    const target = failedTarget
    if (!target || busy) return

    busy = target
    errorMessage = ''
    try {
      const result = await readJson<TurnResult>(
        await fetch('/api/retry', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ target })
        })
      )
      if (!result.ok) {
        errorMessage = result.error ?? `${target} retry failed`
      } else {
        failedTarget = null
      }
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error)
    } finally {
      await refresh()
      busy = null
    }
  }
</script>

<svelte:head>
  <meta name="description" content="GPT Dive Council shared room" />
  <title>{roomTitle} · Council</title>
</svelte:head>

<div class="app-shell">
  <header class="topbar">
    <div class="brand"><span class="brand-mark">C</span><span>Council <em>/</em> room</span></div>
    <div class="session"><span class="live-dot"></span> Local Council</div>
  </header>

  <main class="room">
    <section class="room-heading">
      <div>
        <p class="eyebrow">WORKSPACE / SHARED ROOM</p>
        <h1>{roomTitle}</h1>
        <p class="subheading">USER moderates. SOL and OPUS share the same chronological discussion.</p>
      </div>
      <div class="room-meta"><span>3 participants</span><span class="meta-divider"></span><span>Git-backed</span></div>
    </section>

    <div class="workspace">
      <section class="transcript-panel" aria-label="Council transcript">
        <div class="panel-label"><span>TRANSCRIPT</span><span class="turn-count">{turns.length} turns</span></div>
        <div class="transcript">
          {#if loading}
            <p class="empty-state">Loading Council…</p>
          {:else if turns.length === 0}
            <p class="empty-state">No turns yet. Put the first question in the room.</p>
          {/if}

          {#each turns as turn}
            <article class="turn">
              <div class="turn-gutter">
                <span class="avatar {turn.speaker.toLowerCase()}">{turn.speaker[0]}</span>
                <span class="turn-line"></span>
              </div>
              <div class="turn-body">
                <div class="turn-header"><strong>{turn.speaker}</strong></div>
                <p>{turn.text}</p>
              </div>
            </article>
          {/each}

          {#if busy}
            <article class="turn pending-turn">
              <div class="turn-gutter"><span class="avatar {busy.toLowerCase()}">{busy[0]}</span></div>
              <div class="turn-body">
                <div class="turn-header">
                  <strong>{busy}</strong>
                  <span class="thinking"><i></i><i></i><i></i> working</span>
                </div>
              </div>
            </article>
          {/if}
        </div>
      </section>

      <aside class="side-panel" aria-label="Participant status">
        <div class="panel-label">PARTICIPANTS</div>
        <div class="participants">
          <div class="participant"><span class="avatar sol">S</span><div><strong>SOL</strong><small>Primary engineer</small></div><span class="status-dot ready"></span></div>
          <div class="participant"><span class="avatar opus">O</span><div><strong>OPUS</strong><small>Independent peer</small></div><span class="status-dot ready"></span></div>
          <div class="participant"><span class="avatar user">U</span><div><strong>YOU</strong><small>Moderator / owner</small></div><span class="status-dot you"></span></div>
        </div>

        <div class="side-divider"></div>
        <div class="panel-label">ROOM STATUS</div>
        <div class="status-card">
          <span class="status-icon">{busy ? '…' : '✓'}</span>
          <div>
            <strong>{busy ? `${busy} turn in progress` : 'Ready'}</strong>
            <small>{bridgeStarted ? 'Web SOL bridge connected' : 'Web SOL bridge connects on first SOL turn'}</small>
          </div>
        </div>

        {#if errorMessage}
          <div class="error-card">
            <div class="error-title"><span class="warning">!</span><strong>Turn paused</strong></div>
            <p>{errorMessage}</p>
            {#if failedTarget}
              <button onclick={retry} disabled={busy !== null}>{busy ? 'Retrying…' : `Retry ${failedTarget}`}</button>
            {/if}
          </div>
        {/if}
        <p class="safe-note">The transcript and participant cursors are stored in the local Council Git repository.</p>
      </aside>
    </div>

    <section class="composer-wrap" aria-label="Message composer">
      <div class="composer-label"><span>YOUR TURN</span><span class="target-label">Target: <b>{selectedTarget}</b></span></div>
      <textarea bind:value={draft} placeholder="Add a thought to the room…" rows="3" disabled={busy !== null} onkeydown={(event) => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void sendTo(selectedTarget) }}></textarea>
      <div class="composer-footer">
        <span class="hint">Ctrl / ⌘ Enter to send</span>
        <div class="send-actions">
          <button class="target-button sol-button" onclick={() => void sendTo('SOL')} disabled={busy !== null || !draft.trim()}><span>↗</span> To SOL</button>
          <button class="target-button opus-button" onclick={() => void sendTo('OPUS')} disabled={busy !== null || !draft.trim()}><span>↗</span> To OPUS</button>
        </div>
      </div>
    </section>
    <footer><span>GPT DIVE COUNCIL</span><span>Automate transport <b>·</b> preserve judgment</span></footer>
  </main>
</div>
