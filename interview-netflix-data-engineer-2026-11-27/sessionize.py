#!/usr/bin/env python3
"""Netflix Data Engineer interview, reported and representative question.

Sessionize a play_events stream: deduplicate events, sort per user and
content, start a new session when the gap between consecutive events is
over 30 minutes, and report start, end, watch seconds and completion.

The matching SQL (window functions) is in sessionize.sql in this folder.
This Python version mirrors that logic exactly, so the two can be checked
against each other. Standard library only.

Setup: no install step. Run: python3 sessionize.py
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

GAP = timedelta(minutes=30)
COMPLETE_RATIO = 0.9  # watched at least 90 percent of runtime = completed


@dataclass(frozen=True)
class PlayEvent:
    user_id: str
    content_id: str
    event_type: str  # play, pause, progress, stop
    ts: datetime
    position_sec: int  # playback position when the event fired
    runtime_sec: int   # full runtime of the content


@dataclass
class Session:
    user_id: str
    content_id: str
    start: datetime
    end: datetime
    watch_sec: int
    completed: bool


def dedup(events):
    """Keep one event per user, content, timestamp and type.

    Late and duplicate delivery is normal in playback pipelines, so the
    first step is always an idempotent dedup on the natural key.
    """
    seen = {}
    for e in events:
        seen[(e.user_id, e.content_id, e.ts, e.event_type)] = e
    return sorted(seen.values(), key=lambda e: (e.user_id, e.content_id, e.ts))


def sessionize(events):
    """Group deduped events into sessions with a 30 minute gap rule."""
    sessions = []
    cur = None  # (user, content, start, last_ts, max_position, runtime)
    for e in dedup(events):
        new = (
            cur is None
            or e.user_id != cur[0]
            or e.content_id != cur[1]
            or e.ts - cur[3] > GAP
        )
        if new:
            if cur is not None:
                sessions.append(_close(cur))
            cur = (e.user_id, e.content_id, e.ts, e.ts, e.position_sec, e.runtime_sec)
        else:
            cur = (cur[0], cur[1], cur[2], e.ts,
                   max(cur[4], e.position_sec), cur[5])
    if cur is not None:
        sessions.append(_close(cur))
    return sessions


def _close(cur):
    user, content, start, end, max_pos, runtime = cur
    return Session(user, content, start, end, max_pos,
                   runtime > 0 and max_pos >= COMPLETE_RATIO * runtime)


def demo_events():
    t0 = datetime(2026, 11, 20, 20, 0, 0)
    m = timedelta(minutes=1)
    ev = [
        # user u1 watches film A: two events, then a 45 min gap, then resumes
        PlayEvent("u1", "filmA", "play", t0, 0, 3600),
        PlayEvent("u1", "filmA", "progress", t0 + 20 * m, 1200, 3600),
        PlayEvent("u1", "filmA", "play", t0 + 65 * m, 1200, 3600),
        PlayEvent("u1", "filmA", "stop", t0 + 85 * m, 3400, 3600),
        # exact duplicate of the stop event, must be removed by dedup
        PlayEvent("u1", "filmA", "stop", t0 + 85 * m, 3400, 3600),
        # user u2 starts film B and abandons it after 5 minutes
        PlayEvent("u2", "filmB", "play", t0, 0, 5400),
        PlayEvent("u2", "filmB", "stop", t0 + 5 * m, 300, 5400),
    ]
    return ev


def main():
    sessions = sessionize(demo_events())
    for s in sessions:
        print(f"{s.user_id} {s.content_id} start={s.start.time()} "
              f"end={s.end.time()} watch_sec={s.watch_sec} "
              f"completed={s.completed}")
    # Verified expectations: u1 gets 2 sessions (gap over 30 min splits),
    # the second is completed (3400 of 3600 sec is over 90 percent).
    # u2 gets 1 session, not completed.
    assert len(sessions) == 3, sessions
    assert sessions[0].completed is False
    assert sessions[1].completed is True
    assert sessions[2].completed is False
    print("OK: 3 sessions, dedup applied, completion flags correct")


if __name__ == "__main__":
    main()
