Drop one CSV per city here, named <city>.csv (vsk, kak, vjw, hyd, maa, blr, bom, del).
Header: reservoir,date,storage_pct      (an optional "city" column is allowed; "ALL" as the reservoir means total system storage)
Example:
reservoir,date,storage_pct
ALL,2026-10-03,95.84
Bhatsa,2026-10-03,98.13
The backend checks this folder every poll cycle (default 20 minutes). Unchanged files are ignored; a new or edited file is validated and ingested on the next cycle.
