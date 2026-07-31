# library-sorts — design

Client-side comparators over statistics already in the index payload
(`statistics.size_on_disk`, `statistics.last_release_date`) — the screen
fetches the whole library and sorts in memory by design, so no API work.
"Latest issue" reads the last KNOWN release date (metadata), not file
mtimes: it answers "what moved most recently in publication terms".
Undated series sort last under recency (a series with no known dates is
not "new"). Both options persist via the existing uiStore whitelist.
