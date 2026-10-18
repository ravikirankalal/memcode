import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { ago, latest, parseFeed } from '../hooks/register'
import type { Feed } from '../types'

const BAND = { component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false } } as const

const T = 1_800_000_000
const FEED: Feed = {
  updated: T,
  counts: { memories: 37, rules: 12, notes: 25, facts: 9 },
  events: [
    { ts: T - 30, kind: 'start', text: '12 rules, 8 notes at session start', n: 20 },
    { ts: T - 5, kind: 'saved', text: 'rule: Always use tabs for indentation in this repo.', n: 1 },
  ],
}

test('parses the feed and rejects junk', async () => {
  expect(parseFeed(JSON.stringify(FEED))?.counts.rules).toBe(12)
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
    expect(await ui.find({ type: 'Text', text: /37 memories · 12 rules · 9 facts/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /\+ rule: Always use tabs/ })).toBeDefined()
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
  expect(await ui.find({ type: 'Text', text: /rule: Always use tabs/ })).toBeUndefined()
  file = JSON.stringify({ ...FEED, updated: T + 1 })
  await clock.advance(2500)
  expect(await ui.find({ type: 'Text', text: /rule: Always use tabs/ })).toBeDefined()
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
