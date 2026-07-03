---
name: calendar-sync
description: Syncs upcoming Google Calendar events into the local store.
version: 1
tags: []
uses: []
secrets: []
inputs:
- name: calendar_id
  type: string
  description: Google Calendar ID to read; use primary for the main calendar.
  required: false
- name: timezone_name
  type: string
  description: Optional IANA timezone such as America/New_York; defaults to the runtime local timezone.
  required: false
- name: days_ahead
  type: number
  description: How many days ahead to sync (default 7).
  required: false
goal: 'Keep the local calendar domain synced with upcoming Google Calendar events.'
built_at: '2026-07-03T00:00:00+00:00'
auth_status: not-required
oauth_scopes:
- https://www.googleapis.com/auth/calendar.readonly
---

Fetches the next N days (default 7) of events from Google Calendar using Artemis-provided Google
OAuth and emits them as a JSON row set ({"domain":"calendar","rows":[...]}) for the local data
spine to ingest. Read-only; one-way sync (never writes back to Google).
