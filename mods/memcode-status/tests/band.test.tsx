import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { agentState, ago, cols, latest, layout, parseFeed, problemOf, tally } from '../hooks/register'
import type { Feed } from '../types'

const BAND = { component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, bodyColumns: 160 } } as const

const T = 1_800_000_000
const FEED: Feed = {
  updated: T,
  counts: { memories: 37, from_you: 12 },
  events: [
    { ts: T - 30, kind: 'start', text: '12 from you, 8 memories at session start', n: 20 },
    { ts: T - 5, kind: 'saved', text: 'from you: Always use tabs for indentation in this repo.', n: 1 },
  ],
  problems: {},
  busy: {},
}

test('parses the feed and rejects junk', async () => {
  expect(parseFeed(JSON.stringify(FEED))?.counts.from_you).toBe(12)
  expect(parseFeed('{"counts": {"memories": 3, "rules": 2}, "events": []}')?.counts).toEqual({ memories: 3, from_you: 2 })
  expect(parseFeed('{not json')).toBeNull()
  expect(parseFeed('{"counts": {}}')).toBeNull()
  expect(ago(4_000)).toBe('4s ago')
  expect(ago(125_000)).toBe('2m ago')
  expect(latest(FEED, T * 1000)?.kind).toBe('saved')
  expect(latest(FEED, (T + 3600) * 1000)).toBeNull() // stale events fade to counts only
  const recalledAfter: Feed = { ...FEED, events: [...FEED.events, { ts: T - 2, kind: 'recalled', text: '1 memory', n: 1 }] }
  expect(latest(recalledAfter, T * 1000)?.kind).toBe('saved') // a fresh save holds the bar over a later recall
  expect(latest(recalledAfter, (T + 120) * 1000)?.kind).toBe('recalled')
})

// the world beneath the mod: the repo root, its activity file (or none), an engine-drawn empty band
function world(on: On, file: string | null) {
  on('session.root', () => ({ value: '/repo' }))
  on('fs.read', (_$, e) => {
    if (file === null || e.path !== '/repo/.memcode/activity.json') return { deny: 'ENOENT' }
    return { value: file }
  })
  on('ui.render', ($, e) => { const { Box } = $.ui.resolve(e); return <Box /> })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
}

test('the band shows counts and the latest memory event on every surface', async ($, on) => {
  mock.clock(on, { now: T * 1000 })
  world(on, JSON.stringify(FEED))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'memcode-status', surface, ...BAND })
    expect(await ui.find({ type: 'Text', text: /^37$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: / memories · / })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^12$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: / from you/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /🧠 SAVED/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /from you: Always use tabs/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /0s ago|5s ago/ })).toBeDefined()
    await ui.unmount()
  }
})

test('a new memory shows up on the next poll', async ($, on) => {
  const clock = mock.clock(on, { now: T * 1000 })
  let file = JSON.stringify({ ...FEED, events: FEED.events.slice(0, 1) })
  on('session.root', () => ({ value: '/repo' }))
  on('fs.read', () => ({ value: file }))
  on('ui.render', ($, e) => { const { Box } = $.ui.resolve(e); return <Box /> })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /from you: Always use tabs/ })).toBeUndefined()
  file = JSON.stringify({ ...FEED, updated: T + 1 })
  await clock.advance(2500)
  expect(await ui.find({ type: 'Text', text: /from you: Always use tabs/ })).toBeDefined()
  await ui.unmount()
})

test('says why when memcode is active but writes no feed (older memcode)', async ($, on) => {
  mock.clock(on, { now: T * 1000 })
  world(on, null)
  on('fs.exists', (_$, e) => ({ value: e.path === '/repo/.memcode/memory.db' }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /update memcode to 0\.8\.1/ })).toBeDefined()
  await ui.unmount()
})

test('nothing of its own when memcode is not active in the repo', async ($, on) => {
  mock.clock(on, { now: T * 1000 })
  world(on, null)
  on('fs.exists', () => ({ value: false }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /memcode/ })).toBeUndefined()
  await ui.unmount()
})

test('a worktree session finds the feed in the main working tree', async ($, on) => {
  // issue #32: hooks keep the store under the main checkout; the session root is the worktree
  mock.clock(on, { now: T * 1000 })
  on('session.root', () => ({ value: '/repo/.claude/worktrees/w1' }))
  on('session.repo', () => ({ value: { root: '/repo', remote: null, internal: false, name: null } }))
  on('fs.read', (_$, e) => (e.path === '/repo/.memcode/activity.json' ? { value: JSON.stringify(FEED) } : { deny: 'ENOENT' }))
  on('ui.render', ($, e) => { const { Box } = $.ui.resolve(e); return <Box /> })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/repo/.claude/worktrees/w1', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /^12$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /🧠 SAVED/ })).toBeDefined()
  await ui.unmount()
})

test('a failing memory agent holds the bar with its reason', async ($, on) => {
  // issue #34: capture failures were silent
  mock.clock(on, { now: T * 1000 })
  const why = 'memory agent: the claude CLI is not logged in (or its login expired): run `claude` in a terminal and /login'
  world(on, JSON.stringify({ ...FEED, problems: { capture: why } }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /⚠ PROBLEM/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /not logged in/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /🧠 SAVED/ })).toBeUndefined()
  expect(parseFeed(JSON.stringify(FEED))?.problems).toEqual({})
  await ui.unmount()
})

test('a spent scan budget shows as a warning, a failure outranks it', async ($, on) => {
  mock.clock(on, { now: T * 1000 })
  const budget = "memory agent: this session's $0.3 budget is spent; 120 transcript lines not scanned"
  world(on, JSON.stringify({ ...FEED, problems: { budget } }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /💸 BUDGET/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /120 transcript lines not scanned/ })).toBeDefined()
  await ui.unmount()
  const both: Feed = { ...FEED, problems: { budget, capture: 'memory agent: not logged in' } }
  expect(problemOf(both)?.look.tag).toBe('PROBLEM')
  expect(problemOf(FEED)).toBeNull()
})

test('routine scans never take the headline; the agent shows its state instead', async ($, on) => {
  mock.clock(on, { now: T * 1000 })
  const scans: Feed = { ...FEED, events: [
    { ts: T - 300, kind: 'recalled', text: '2 memories for this prompt', n: 2 },
    { ts: T - 20, kind: 'scanned', text: '2 candidates, kept 0', n: 2 },
  ] }
  expect(latest(scans, T * 1000)?.kind).toBe('recalled')
  expect(agentState(scans, T * 1000)).toEqual({ reading: false, lastScan: scans.events[1] })
  world(on, JSON.stringify(scans))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /💡 RECALLED/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /🔍 SCANNED/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /🔍 20s/ })).toBeDefined()
  await ui.unmount()
})

test('while the memory agent reads, the bar says so; a mark left by a dead worker is ignored', async ($, on) => {
  mock.clock(on, { now: T * 1000 })
  const busy: Feed = { ...FEED, busy: { agent: T - 3 } }
  expect(agentState(busy, T * 1000).reading).toBe(true)
  expect(agentState({ ...FEED, busy: { agent: T - 600 } }, T * 1000).reading).toBe(false)
  world(on, JSON.stringify(busy))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'memcode-status', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /🔍 reading\.+/ })).toBeDefined()
  await ui.unmount()
})

test("this session's tally counts only events since the session started", async () => {
  const f: Feed = { ...FEED, events: [
    { ts: T - 900, kind: 'saved', text: 'old', n: 1 },
    { ts: T - 50, kind: 'saved', text: 'a', n: 1 }, { ts: T - 40, kind: 'saved', text: 'b', n: 1 },
    { ts: T - 30, kind: 'recalled', text: 'c', n: 1 }, { ts: T - 20, kind: 'scanned', text: 'd', n: 1 },
  ] }
  expect(tally(f, (T - 100) * 1000)).toBe('2 saved · 1 recalled')
  expect(tally(f, (T + 1) * 1000)).toBe('')
})

test('a narrow terminal keeps the headline: the tally, the agent, then the count labels give way', async () => {
  const parts = { counts: '37 memories · 12 from you', countsShort: '🧠37 📜12', head: 60, agent: '🔍 2m',
    tally: '+2 saved' }
  expect(layout(160, parts)).toMatchObject({ long: true, agent: true, tally: true })
  expect(layout(90, parts)).toMatchObject({ long: true, agent: true, tally: false })
  expect(layout(70, parts)).toMatchObject({ long: false, agent: false, tally: false })
  expect(cols('🧠37')).toBe(4)
  expect(cols('✏️ x')).toBe(4)
})

test('/memcode-status reads as a dashboard', async ($, on) => {
  mock.clock(on, { now: T * 1000 })
  world(on, JSON.stringify({ ...FEED, events: [...FEED.events, { ts: T - 2, kind: 'scanned', text: '3 candidates, kept 1', n: 3 }] }))
  on('session.surfaces', () => ({ value: [] }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const out = await $.command.run({ command: 'memcode-status' })
  const text = (out as { text: string }).text
  expect(text).toMatch(/◆ memcode: 37 memories, 12 from you/)
  expect(text).toMatch(/memory agent: last read 2s ago \(3 candidates, kept 1\)/)
  expect(text).toMatch(/🧠 SAVED +from you: Always use tabs/)
  expect(text).toMatch(/no terminal or desktop surface/)
})
