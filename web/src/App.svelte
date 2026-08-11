<script lang="ts">
  type Speaker = 'USER' | 'SOL' | 'OPUS'
  type Turn = { speaker: Speaker; text: string; time: string; tone?: 'error' }

  let draft = ''
  let selectedTarget: 'SOL' | 'OPUS' = 'SOL'
  let isRetrying = false
  let turns: Turn[] = [
    { speaker: 'USER', text: 'How should we frame the next decision?', time: '09:41' },
    { speaker: 'SOL', text: 'I suggest we start with the constraint, then make the trade-off explicit.', time: '09:42' },
    { speaker: 'OPUS', text: 'Agreed. I’ll pressure-test that framing against the options on the table.', time: '09:43' }
  ]

  const prompts = {
    SOL: 'Mock response from SOL: constraint noted. I would make the smallest reversible move first.',
    OPUS: 'Mock response from OPUS: the framing holds up. I see one assumption worth surfacing.'
  }

  function sendTo(target: 'SOL' | 'OPUS') {
    const text = draft.trim()
    selectedTarget = target
    if (!text) return

    turns = [...turns, { speaker: 'USER', text, time: now() }, { speaker: target, text: prompts[target], time: now() }]
    draft = ''
  }

  function retry() {
    isRetrying = true
    window.setTimeout(() => (isRetrying = false), 700)
  }

  function now() {
    return new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date())
  }
</script>

<svelte:head>
  <meta name="description" content="A local mock Council room shell" />
</svelte:head>

<div class="app-shell">
  <header class="topbar">
    <div class="brand"><span class="brand-mark">C</span><span>Council <em>/</em> room</span></div>
    <div class="session"><span class="live-dot"></span> Local mock session <span class="session-id">#04</span></div>
  </header>

  <main class="room">
    <section class="room-heading">
      <div>
        <p class="eyebrow">WORKSPACE / DECISION ROOM</p>
        <h1>Untitled council</h1>
        <p class="subheading">A quiet place to put the question in the middle.</p>
      </div>
      <div class="room-meta"><span>3 participants</span><span class="meta-divider"></span><span>Mock only</span></div>
    </section>

    <div class="workspace">
      <section class="transcript-panel" aria-label="Council transcript">
        <div class="panel-label"><span>TRANSCRIPT</span><span class="turn-count">{turns.length} turns</span></div>
        <div class="transcript">
          {#each turns as turn}
            <article class:has-error={turn.tone === 'error'} class="turn">
              <div class="turn-gutter">
                <span class="avatar {turn.speaker.toLowerCase()}">{turn.speaker[0]}</span>
                <span class="turn-line"></span>
              </div>
              <div class="turn-body">
                <div class="turn-header"><strong>{turn.speaker}</strong><time>{turn.time}</time></div>
                <p>{turn.text}</p>
              </div>
            </article>
          {/each}
          <article class="turn pending-turn">
            <div class="turn-gutter"><span class="avatar opus">O</span></div>
            <div class="turn-body"><div class="turn-header"><strong>OPUS</strong><span class="thinking"><i></i><i></i><i></i> thinking</span></div></div>
          </article>
        </div>
      </section>

      <aside class="side-panel" aria-label="Participant status">
        <div class="panel-label">PARTICIPANTS</div>
        <div class="participants">
          <div class="participant"><span class="avatar sol">S</span><div><strong>SOL</strong><small>Primary engineer</small></div><span class="status-dot ready"></span></div>
          <div class="participant"><span class="avatar opus">O</span><div><strong>OPUS</strong><small>Independent peer</small></div><span class="status-dot ready"></span></div>
          <div class="participant"><span class="avatar user">U</span><div><strong>YOU</strong><small>Room owner</small></div><span class="status-dot you"></span></div>
        </div>

        <div class="side-divider"></div>
        <div class="panel-label">ROOM STATUS</div>
        <div class="status-card"><span class="status-icon">✓</span><div><strong>Listening</strong><small>All participants are ready</small></div></div>
        <div class="error-card"><div class="error-title"><span class="warning">!</span><strong>Connection paused</strong></div><p>This is a simulated error state. Nothing has been sent.</p><button onclick={retry} disabled={isRetrying}>{isRetrying ? 'Trying again…' : 'Try again'}</button></div>
        <p class="safe-note">Mock actions are local only. No backend is connected yet.</p>
      </aside>
    </div>

    <section class="composer-wrap" aria-label="Message composer">
      <div class="composer-label"><span>YOUR TURN</span><span class="target-label">Target: <b>{selectedTarget}</b></span></div>
      <textarea bind:value={draft} placeholder="Add a thought to the room…" rows="3" onkeydown={(event) => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) sendTo(selectedTarget) }}></textarea>
      <div class="composer-footer"><span class="hint">⌘ Enter to send</span><div class="send-actions"><button class="target-button sol-button" onclick={() => sendTo('SOL')}><span>↗</span> To SOL</button><button class="target-button opus-button" onclick={() => sendTo('OPUS')}><span>↗</span> To OPUS</button></div></div>
    </section>
    <footer><span>COUNCIL ROOM SHELL</span><span>Built for a focused exchange <b>·</b> v0.1</span></footer>
  </main>
</div>
