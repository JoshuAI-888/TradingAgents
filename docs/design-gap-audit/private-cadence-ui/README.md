# Private cadence UI checkpoint

The Changes header now opens owner-private, exact-screen cadence settings. Users can create/edit a name, IANA time zone, local time and weekdays. The current API deliberately rejects enabling automation; the dialog discloses this and only submits enabled=false.

Revision-safe PATCH and create POST preserve original pinned screen/preset rules. Conflict errors retain the draft; Load latest settings displays the persisted name/cadence and adopts that revision without replacing draft fields. Drafts are tab-only, owner/definition scoped and cleared on account change. Account/screen guards reject obsolete saves.

Verification:
- 143 JavaScript tests pass, covering matching versioned helper assets, disabled cadence submission, revision conflicts, draft preservation, empty-weekday and changed-owner rejection, and account clearing.
- The actual local API browser fixture saved Pacific/Auckland 09:15 Monday–Thursday and reopened revision 2 with matching values.
- At 390 × 844, the dialog had clientWidth=scrollWidth=333 and width=346; all seven weekday labels measured 44 CSS pixels high. The dialog scrolls vertically.
- Close/reopen restored an unsaved draft. Escape removed the dialog and returned focus to Capture schedule.
- [Phone screenshot](phone-settings.png).

Fixtures use synthetic Auth/store transport, not real Supabase/platform qualification. Runtime activation, provider/full-market/session/restart/maximum-size/performance, real account isolation and deployment remain open. User automation remains off. These controls configure calendar weekdays, not a holiday-aware exchange schedule.
