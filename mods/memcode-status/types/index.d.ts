export type FeedEvent = { ts: number; kind: string; text: string; n: number }
export type Feed = {
  updated: number
  counts: { memories: number; rules: number; notes: number; facts: number }
  events: FeedEvent[]
  problems: Record<string, string> // what is broken right now (memcode/activity.py), e.g. a failing memory agent
}

declare module 'claude-code' {
  interface PluginState {
    'memcode-status': { feed: Feed | null; now: number; hint: string | null }
  }
}
