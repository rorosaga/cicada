"""The synthetic bank and saves behind the saves battery (G245, ruling 80's plan, Track M).

Everything here is invented: an owner called Alex Example, a friend "Sam Example", a colleague "Riley Example", an
employer "Helio Example", a notes app "Quillnote", and about 90 saves with ``example.com`` links. Nothing comes from any
person's bank. The text is natural English on purpose: word-salad data makes the model refuse extraction
(`benchmarks/perf/README.md`, "Live runs"), and the traps below only mean something when the text reads like real posts.

``build_bank`` seeds pages with the sleep_calls pattern (pages written directly, backed by older processed conversations
so each stands on two), stages the waiting conversations through the production stager, and ``capture_saves`` writes every
save through the production capture writers (``media_ingestor.write_prepared`` with a stand-in page description in place of
the network fetch, ``tab_groups.sync``), so a save is stored exactly as capture stores it on dev: bookmarks and list saves
already read by the index, a save with a reason or a feed item waiting for Sleep. ``wake_saves`` is the single-read leg's
one move (see ``saves_battery`` and the README paragraph for what it does and does not prove).

``SAVES`` rows are dicts: ``key`` (unique), ``group`` (the trap), ``url``, ``title``, ``desc`` (what the page's own
description said), ``author`` (the post's author or channel), ``origin``, ``folder``, ``age`` (days between the save and
the run's clock; 0 = today), ``posted`` (the post's own day, ISO), ``note``/``reason`` (words that make a save readable
on dev today), ``via`` (``write`` by default; ``tab-group`` for a group).
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OWNER = "Alex Example"
#: Seeded pages: ``type|name|summary|fact; fact``. Each stands on two older processed conversations.
PAGES = """
person|Sam Example|Sam Example is a friend of Alex Example from the climbing gym.|Sam Example works as a nurse.; Sam Example climbs on Thursdays with Alex Example.
person|Riley Example|Riley Example is a product designer at Helio Example and Alex Example's colleague.|Riley Example designed Helio Example's billing screens.; Riley Example sits next to Alex Example in the Lisbon office.
company|Helio Example|Helio Example is a logistics software company where Alex Example works as a backend engineer.|Helio Example has its office in Lisbon.; Helio Example was founded in 2016.
tool|Quillnote|Quillnote is the note-taking app Alex Example uses for meeting notes and project plans at Helio Example.|Alex Example keeps one Quillnote notebook per project.; Alex Example pays for Quillnote Pro.
"""
#: Facts of the seeded pages that the bank is allowed to start with, so a test can tell what Sleep added.
SEEDED_PAGE_IDS = ("sam-example", "riley-example", "helio-example", "quillnote")

#: The waiting conversations: the person's own words, an assistant's replies. One phase, one night. None of them names
#: a topic only the saves name (sourdough), so a page born of that topic has only saves behind it.
CONVERSATIONS = [
    {"id": "c01", "phase": 1, "day": -6, "title": "Meeting notes in Quillnote", "turns": [
        "I finally moved all my Helio meeting notes into Quillnote, one notebook per project, and it is so much easier to find things now.",
        "That sounds like a tidy setup. Do you tag the notes or rely on search?",
        "Mostly search. Riley told me Quillnote has a backlinks panel but I have not tried it yet."]},
    {"id": "c02", "phase": 1, "day": -5, "title": "Climbing on Thursday", "turns": [
        "Sam Example and I are going climbing again on Thursday evening, he finally got the new shoes he kept talking about.",
        "Nice. Are you doing the bouldering wall or the ropes?",
        "Ropes this time. Sam says his wrist has healed so he wants to try the overhang route."]},
    {"id": "c03", "phase": 1, "day": -5, "title": "Design review with Riley", "turns": [
        "Riley Example and I spent the afternoon reviewing the new billing screens at Helio, there are way too many steps in the refund flow.",
        "What did you decide?",
        "We will cut the refund flow from six screens to three, Riley is redrawing them this week and I will change the endpoints."]},
    {"id": "c04", "phase": 1, "day": -4, "title": "Weekend in Lisbon", "turns": [
        "I want to show my cousin around Lisbon this weekend, he lands on Friday night.",
        "What does he like?",
        "Food mostly. I will take him to the pastry place near the office and then up to the viewpoint at sunset."]},
    {"id": "c05", "phase": 1, "day": -3, "title": "A read-later article about sync", "turns": [
        "I saved an article about how Quillnote does offline sync, I want to read it properly this weekend because we have the same problem at Helio.",
        "Is it the conflict handling you care about?",
        "Yes, how two people editing one note offline end up with a merge instead of a copy."]},
    {"id": "c06", "phase": 1, "day": -2, "title": "Running plan", "turns": [
        "I am trying to run three times a week before work, but it has been raining every morning.",
        "Would evening runs work better?",
        "Maybe, if Helio lets me leave on time. I will try Tuesday and Saturday mornings and one evening run."]},
    {"id": "c07", "phase": 1, "day": -2, "title": "Dinner for four", "turns": [
        "Sam Example and his partner are coming for dinner on Saturday, I am thinking a mushroom risotto.",
        "That is a good crowd-pleaser. Any allergies to check?",
        "Sam's partner does not eat shellfish, otherwise nothing. I will make a lemon tart as well."]},
    {"id": "c08", "phase": 1, "day": -1, "title": "Helio planning", "turns": [
        "Our team at Helio is planning the next quarter and I volunteered to own the billing API rewrite.",
        "That is a big commitment. Do you have a target date?",
        "End of March for the first version. Riley Example is on the design side and I will pair with her on the refund flow."]},
]

# ---- the saves -------------------------------------------------------------------------------------------------------

AUTHORS = ["Taylor Placeholder", "Jamie Sample", "Robin Demo", "Casey Placeholder", "Avery Sample", "Drew Demo",
           "Sasha Sample", "Reese Demo", "Kai Placeholder", "Morgan Placeholder"]

#: 50 posts that each state one fact about the existing page "Quillnote": ``title|description``.
QUILLNOTE_POSTS = """
Quillnote 4.2 adds offline sync|Quillnote 4.2 keeps a full offline copy of every notebook and syncs the changes when the connection returns. The release notes say conflicts are merged line by line.
Quillnote moves its servers to Frankfurt|Quillnote has moved all customer data to servers in Frankfurt, which the company says cuts load times for European users by about a third.
Quillnote's free plan now caps notebooks at 50|Starting next month the free plan of Quillnote will be limited to 50 notebooks. Existing users above the limit keep what they have but cannot create new ones.
Quillnote Pro now costs six euros a month|The Pro plan of Quillnote costs six euros a month, up from five, and adds version history and larger attachments.
Quillnote ships a Linux client|Quillnote now has a native Linux client built on the same editor as its desktop apps, distributed as an AppImage and a Debian package.
Tables arrive in the Quillnote editor|The Quillnote editor finally supports tables, including sortable columns and pasting from spreadsheets, after years of user requests.
Quillnote adds end-to-end encryption for shared notebooks|Quillnote now encrypts shared notebooks end to end, so the company can no longer read them. Search inside encrypted notebooks happens only on the device.
The two teachers who founded Quillnote|Quillnote was started by two former school teachers who wanted a better way to keep lesson plans. They still run the company with a team of twelve.
Quillnote passes 300,000 active users|Quillnote announced it has passed 300,000 monthly active users, doubling in a year, mostly through word of mouth in universities.
A web clipper for Quillnote|Quillnote released a browser extension that clips articles into a notebook as clean text. The clipper works in Firefox, Chrome and Safari.
Quillnote API limits explained|The Quillnote API allows 60 requests per minute per token. Bulk exports have their own endpoint that is not rate limited.
Quillnote exports to Markdown and PDF|Notebooks in Quillnote can be exported as Markdown files with attachments in a folder, or as a single PDF with a table of contents.
Quillnote opens a plugin store|The Quillnote plugin store opened with 40 plugins, including a Pomodoro timer, a citation manager and a kanban view.
A dark mode redesign for Quillnote|Quillnote's new dark mode uses a softer grey instead of pure black and fixes the unreadable code blocks that annoyed many users.
Quillnote transcribes voice memos|Voice memos recorded in Quillnote are now transcribed on the device and inserted into the note as text, with the audio kept as an attachment.
Quillnote's team plan gets shared templates|Teams on Quillnote can now keep shared note templates, such as meeting agendas and retrospectives, in a common library.
Quillnote 4.3 fixes the duplicate note bug|Quillnote 4.3 fixes a bug that created duplicate notes in shared notebooks after an offline edit. The company apologised for losing a few drafts.
Quillnote search now reads attachments|Search in Quillnote indexes the text inside PDF and image attachments, so a scanned receipt can be found by what it says.
Quillnote connects to calendars|Quillnote can now create a meeting note from a calendar event and link the attendees, for Google and Apple calendars.
A Quillnote widget for iOS|Quillnote added a home screen widget for iOS that shows pinned notes and a quick-capture button.
Quillnote keeps backups for 30 days|Deleted notes in Quillnote can be restored for 30 days from the trash, and daily backups are kept for the same period.
Quillnote was founded in 2019 in Rotterdam|Quillnote began in 2019 as a side project in Rotterdam. The company incorporated a year later and has never taken outside money.
Custom keyboard shortcuts in Quillnote|Quillnote now lets people remap every keyboard shortcut and import a shortcut set from another editor.
Handwriting is on the Quillnote roadmap|The public roadmap of Quillnote lists handwriting and stylus support for tablets as the next big feature after the new editor.
Quillnote reports 99.95 percent uptime|Quillnote's status page shows 99.95 percent uptime over the last year, with the longest outage lasting forty minutes in March.
Quillnote rewrites its Android app in Kotlin|The Android app of Quillnote was rewritten in Kotlin and starts twice as fast, according to the team.
Backlinks panel arrives in Quillnote|Quillnote has a new backlinks panel that lists every note linking to the one you are reading, with a short excerpt of each link.
Quillnote tests a graph view|Quillnote is testing a graph view of linked notes in a beta channel. The team says it is optional and will not be on by default.
Quillnote adds single sign-on for teams|The team plan of Quillnote now supports SAML single sign-on, a long-requested feature for companies with strict identity rules.
Quillnote offers a 50 percent student discount|Students with a university email get half off Quillnote Pro for as long as they are enrolled.
Quillnote imports from two rival apps|Quillnote released an import tool that moves notebooks, tags and attachments from two competing note apps in one step.
Quillnote's mobile app gets lighter|The Quillnote mobile app dropped from 180 to 60 megabytes after the team removed an unused rendering library.
Quillnote opens a template gallery|Quillnote now has a gallery of community templates, from weekly reviews to trip plans, that can be added to any notebook.
A university becomes Quillnote's largest customer|A European university rolled Quillnote out to 20,000 students, making it the largest customer of the company so far.
Quillnote's founder promises no ads|In an interview one of the founders of Quillnote promised the product will never show ads and will never sell notes to third parties.
Quillnote open sources its sync library|The sync library behind Quillnote is now open source under a permissive licence, which the team hopes will make third-party clients possible.
Quillnote passes an independent security audit|An external firm audited Quillnote's encryption and found no critical issues. The summary of the report is public.
Quillnote's AI summaries are opt-in|Quillnote added note summaries written by a language model. The feature is off by default and processes text without storing it.
Quillnote extends version history to 90 days|Pro users of Quillnote can now go back 90 days in a note's version history instead of 30.
Quillnote raises the attachment limit to 25 MB|Attachments in Quillnote can now be up to 25 megabytes, up from 10, which makes recorded meetings practical.
Quillnote moves to monthly releases|Quillnote now ships a release on the first Tuesday of every month instead of irregular big versions, with a public changelog.
Reminders come to Quillnote|Quillnote notes can now carry reminders that show up as notifications on every device, and repeat daily, weekly or monthly.
Nested tags in Quillnote|Tags in Quillnote can now be nested, so a tag like work/billing sits under work in the sidebar.
Quillnote support hours|Quillnote's support team answers email from nine to six Central European time on weekdays and promises a first reply within four hours.
How Quillnote built CRDT sync|A post on the Quillnote engineering blog explains how the team built conflict-free sync on top of a CRDT library and what went wrong in the first version.
Quillnote cuts battery use in offline mode|The latest Quillnote update reduced battery drain in offline mode by 40 percent by batching writes.
Public pages for Quillnote notebooks|Quillnote can publish a notebook as a public website with its own address, a feature the team calls Pages.
Quillnote ships a command line tool|Quillnote's new command line tool lets people create, search and export notes from a terminal, and works with the same API token.
Quillnote migrates to a new editor engine|Quillnote replaced the engine of its editor with a faster one, which fixed long-standing scrolling problems in big notes.
Quillnote launches a referral program|Quillnote users get a free month of Pro for each friend who signs up and stays for three months.
"""

#: Every trap but the 50 posts and the bulk list: one row per save.
TRAPS: list[dict] = [
    # a topic named in many posts, by different authors (a page born of strangers' words is the trap)
    *[{"key": f"sour{n:02d}", "group": "topic", "url": f"https://example.com/baking/sourdough-{n:02d}",
       "title": title, "desc": desc, "author": AUTHORS[(n + 2) % len(AUTHORS)], "origin": "chrome-bookmark"}
      for n, (title, desc) in enumerate([
          ("Sourdough hydration, explained", "Hydration is the ratio of water to flour in a sourdough dough. A wetter dough gives an open crumb but is harder to shape, and most home bakers start at 70 percent."),
          ("Why your sourdough starter smells like nail polish", "A starter that smells like acetone is hungry. Feed it more often and keep it warmer and the smell goes away within two days."),
          ("A weekend sourdough schedule that fits a job", "Mix on Friday evening, shape on Saturday morning and bake in the afternoon. The long cold rise in the fridge does most of the work."),
          ("Sourdough crumb: what the holes tell you", "Large irregular holes mean a well-fermented, wet dough. Tight crumb usually means under-proofing or too little water."),
          ("Dutch ovens for sourdough, tested", "We baked twelve loaves in four Dutch ovens. The cast iron one with the heaviest lid gave the best oven spring."),
          ("Feeding a sourdough starter once a week", "Keeping a starter in the fridge and feeding it weekly works well for people who bake on weekends. Take it out a day before baking."),
      ], start=1)],
    # an author whose name equals an existing person page (colleague "Riley Example")
    {"key": "riley01", "group": "author-equals-page", "url": "https://example.com/type/line-length", "title": "Line length and readability",
     "desc": "Lines of 60 to 75 characters read best on screen. Riley Example, a type designer, argues that shorter lines slow reading less than longer ones.",
     "author": "Riley Example", "origin": "chrome-bookmark"},
    {"key": "riley02", "group": "author-equals-page", "url": "https://example.com/type/pairing", "title": "Pairing fonts without fear",
     "desc": "Pick one family with strong contrast between weights, then add a neutral companion. Riley Example writes that most pairing mistakes come from fonts that are too similar.",
     "author": "Riley Example", "origin": "chrome-bookmark"},
    # a first name only: a stranger called Sam while the friend page "Sam Example" exists
    {"key": "sam01", "group": "first-name-only-existing", "url": "https://example.com/blog/standup-rituals", "title": "Standups that people do not hate",
     "desc": "Sam from the platform team told me they dropped the daily standup for a written update, and attendance in the weekly sync went up. Sam thinks the rule is no status in meetings.",
     "author": "Jamie Sample", "origin": "chrome-bookmark"},
    {"key": "sam02", "group": "first-name-only-existing", "url": "https://example.com/blog/trail-shoes", "title": "Trail shoes after 800 kilometres",
     "desc": "My friend Sam runs ultramarathons and says a shoe is finished after 800 kilometres, whatever the brand claims. Sam lives in Denver and has a spreadsheet for it.",
     "author": "Robin Demo", "origin": "reddit-saved", "folder": "r/running"},
    {"key": "sam03", "group": "first-name-only-existing", "url": "https://example.com/blog/hiring-notes", "title": "What I learned hiring my first engineer",
     "desc": "Sam, our first hire, joined as a contractor and became a co-founder within a year. Sam's rule was to write down every decision, and it saved us twice.",
     "author": "Avery Sample", "origin": "chrome-bookmark"},
    # a first name only with no page at all
    {"key": "first01", "group": "first-name-only-new", "url": "https://example.com/blog/moving-abroad", "title": "Moving abroad with a toddler",
     "desc": "Priya, who moved from Mumbai to Toronto with a two-year-old, says the first three months were the hardest and the daycare waitlist was the real shock.",
     "author": "Casey Placeholder", "origin": "chrome-bookmark"},
    {"key": "first02", "group": "first-name-only-new", "url": "https://example.com/blog/open-source-burnout", "title": "Open source maintainers and burnout",
     "desc": "Dev maintains a popular parser library alone and answered 400 issues last year. Dev says saying no early is the only thing that works.",
     "author": "Drew Demo", "origin": "chrome-bookmark"},
    # a post stating a fact about another existing page, and a 2021 post stating a present-tense fact
    {"key": "helio01", "group": "fact-about-page", "url": "https://example.com/news/helio-warehouse-api", "title": "Helio Example opens its warehouse API",
     "desc": "Helio Example opened a public API for warehouse tracking this month and says early customers include two regional grocers.",
     "author": "Sasha Sample", "origin": "chrome-bookmark"},
    {"key": "old2021", "group": "old-post-present-tense", "url": "https://example.com/news/helio-2021-profile", "title": "Profile: Helio Example",
     "desc": "Helio Example is run by Casey Placeholder, its CEO since the founding. The company has 40 employees and one office, in Porto.",
     "author": "Reese Demo", "origin": "chrome-bookmark", "posted": "2021-03-04"},
    # first person: "I" and "my" in a stranger's post; "the user" in a quoted line
    {"key": "me01", "group": "first-person", "url": "https://example.com/blog/leaving-banking", "title": "Why I left banking to bake bread",
     "desc": "I quit my job at a bank last year and now I run a small bakery. My day starts at four and my favourite thing is the first batch of rye.",
     "author": "Kai Placeholder", "origin": "chrome-bookmark"},
    {"key": "me02", "group": "first-person", "url": "https://example.com/blog/my-home-lab", "title": "My home lab, two years in",
     "desc": "I run my own mail server and my wife hates it. I will never go back to a hosted service, and my next project is a backup box.",
     "author": "Morgan Placeholder", "origin": "chrome-bookmark"},
    {"key": "me03", "group": "first-person", "url": "https://example.com/blog/why-i-write", "title": "Why I write every morning",
     "desc": "I write for twenty minutes before I look at my phone. My editor says it is the only habit I have kept for ten years.",
     "author": "Taylor Placeholder", "origin": "x-likes", "folder": None},
    {"key": "user01", "group": "the-user", "url": "https://example.com/design/blame-the-user", "title": "The user is not the problem",
     "desc": "The report concludes that the user prefers fewer taps and the user wants to be told what happened. A design that blames the user has already failed, it says.",
     "author": "Jamie Sample", "origin": "chrome-bookmark"},
    {"key": "user02", "group": "the-user", "url": "https://example.com/design/onboarding-notes", "title": "Notes from forty onboarding sessions",
     "desc": "The user always skips the tutorial, the user rarely reads the tooltip, and the user blames the product when a form resets. We stopped designing for the user we wished for.",
     "author": "Robin Demo", "origin": "chrome-bookmark"},
    # a title-only bookmark (the page gave no description), three of them
    {"key": "bare01", "group": "title-only", "url": "https://example.com/misc/a", "title": "Untitled notes on gardening", "desc": "", "author": None, "origin": "chrome-bookmark"},
    {"key": "bare02", "group": "title-only", "url": "https://example.com/misc/b", "title": "Rail passes compared", "desc": "", "author": None, "origin": "chrome-bookmark"},
    {"key": "bare03", "group": "title-only", "url": "https://example.com/misc/c", "title": "Local election results map", "desc": "", "author": None, "origin": "chrome-bookmark"},
    # a feed item and an open Safari tab
    {"key": "feed01", "group": "feed-item", "url": "https://example.com/feed/weekly-build-notes", "title": "Weekly build notes, issue 41",
     "desc": "This week the project merged the new scheduler, deprecated two flags and started a survey about release cadence.",
     "author": "Example Build Blog", "origin": "rss", "published_at": "{today}T06:00:00Z"},
    {"key": "feed02", "group": "feed-item", "url": "https://example.com/feed/city-cycling", "title": "The city adds 12 kilometres of bike lanes",
     "desc": "The council approved twelve kilometres of protected bike lanes along the river, to be finished by next summer.",
     "author": "Example City Desk", "origin": "rss", "published_at": "{today}T07:00:00Z"},
    {"key": "tab01", "group": "safari-tab", "url": "https://example.com/tabs/train-times", "title": "Train times to the coast",
     "desc": "Trains to the coast leave every hour at ten past, and the last one back is at 22:40.", "author": None, "origin": "safari-tab"},
    {"key": "tab02", "group": "safari-tab", "url": "https://example.com/tabs/recipe-lentils", "title": "Red lentil soup with lemon",
     "desc": "A red lentil soup with lemon and cumin, ready in thirty minutes.", "author": None, "origin": "safari-tab"},
    # saves with the person's own reason
    {"key": "why01", "group": "own-reason", "url": "https://example.com/blog/billing-api-design", "title": "Designing a billing API that survives refunds",
     "desc": "Idempotency keys, ledgers instead of balances and why refunds are a separate resource, from a payments engineer.",
     "author": "Kai Placeholder", "origin": "chrome-bookmark", "reason": "Reading this for the billing API rewrite I own at Helio."},
    {"key": "why02", "group": "own-reason", "url": "https://example.com/shop/climbing-shoes", "title": "Climbing shoes for wide feet",
     "desc": "A review of eight climbing shoes with a wide toe box, ranked for comfort on long routes.",
     "author": "Avery Sample", "origin": "chrome-bookmark", "reason": "Birthday present idea for Sam."},
    # a 40-day-old bookmark and an older one
    {"key": "old40a", "group": "forty-days-old", "url": "https://example.com/blog/espresso-ratios", "title": "Espresso ratios and what they change",
     "desc": "A 1:2 ratio gives a balanced shot, 1:3 a lighter one. Grind finer before changing the dose.",
     "author": "Casey Placeholder", "origin": "chrome-bookmark", "age": 40},
    {"key": "old40b", "group": "forty-days-old", "url": "https://example.com/blog/sleep-and-lighting", "title": "Evening light and sleep",
     "desc": "Dimming lights two hours before bed shortens the time it takes to fall asleep, according to a small study of sixty adults.",
     "author": "Drew Demo", "origin": "chrome-bookmark", "age": 40},
    # a connector-saved tweet in today's shape (the post text rides ``note``, so capture stores it as the person's note)
    {"key": "tweetnote01", "group": "connector-today", "url": "https://example.com/i/web/status/1001", "title": "I joined the logistics team this week and my first job is rewriting billing",
     "note": "I joined the logistics team this week and my first job is rewriting billing. My manager says to start with refunds.",
     "author": None, "origin": "x-bookmarks", "folder": "Bookmarks"},
    {"key": "tweetnote02", "group": "connector-today", "url": "https://example.com/i/web/status/1002", "title": "My plan for the year: ship two apps and run a marathon",
     "note": "My plan for the year: ship two apps and run a marathon. I already bought the shoes and I deleted my game accounts.",
     "author": None, "origin": "x-bookmarks", "folder": "Bookmarks"},
    # the same two tweets in the shape ruling 80's plan gives them (the text as the page's description)
    {"key": "tweetdesc01", "group": "connector-fixed", "url": "https://example.com/i/web/status/2001", "title": "I started learning the cello at forty and my neighbours are patient",
     "desc": "I started learning the cello at forty and my neighbours are patient. My teacher says my bowing is improving every week.",
     "author": None, "origin": "x-bookmarks", "folder": "Bookmarks"},
    {"key": "tweetdesc02", "group": "connector-fixed", "url": "https://example.com/i/web/status/2002", "title": "My team moved to four-day weeks and my output went up",
     "desc": "My team moved to four-day weeks and my output went up. I now plan every Monday on paper and my meetings dropped by half.",
     "author": None, "origin": "x-bookmarks", "folder": "Bookmarks"},
    # tab groups (through ``tab_groups.sync``, not the media writer)
    {"key": "group01", "group": "tab-group", "via": "tab-group", "title": "Lisbon weekend",
     "tabs": [("Pastry places near the river", "https://example.com/lisbon/pastry"), ("Sunset viewpoints", "https://example.com/lisbon/viewpoints")]},
    {"key": "group02", "group": "tab-group", "via": "tab-group", "title": "Sync research",
     "tabs": [("CRDT papers reading list", "https://example.com/research/crdt-reading"), ("Operational transform explained", "https://example.com/research/ot")]},
    # the same link on a second list: capture dedupes it (one episode), the page gains the list
    {"key": "dup01", "group": "same-link-two-lists", "url": "https://example.com/baking/sourdough-01", "title": "Sourdough hydration, explained",
     "desc": "Hydration is the ratio of water to flour in a sourdough dough.", "author": "Taylor Placeholder", "origin": "substack-saved", "folder": "Saved"},
]

#: 200 undated rows from one saved list (a Watch later playlist): a title and a channel, nothing else.
BULK_ROWS = 200
BULK_TOPICS = ["sourdough", "climbing technique", "home espresso", "rust ownership", "tide tables", "modular synths", "bike repair",
               "garden planning", "typography basics", "chess openings", "cast iron care", "network protocols", "pottery glazes",
               "trail running", "ledger accounting", "bird migration", "knot tying", "film photography", "sleep science", "map making"]
BULK_FORMATS = ["{t} for beginners", "A deep dive into {t}", "{t}: ten mistakes", "How I learned {t} in a month", "{t} explained in 15 minutes",
                "The history of {t}", "{t} tools I actually use", "Common {t} myths", "A weekend of {t}", "{t}, part {n}"]


_SYLLABLES = [c + v for c in "bdfgklmnprstvz" for v in "aeiou"]


def _series_name(n: int) -> str:
    """A name no other row shares (three syllables from a fixed alphabet), so a lookup can tell two rows of one list apart.
    A word shared by more than 3 percent of the saved items is common and finds nothing (``saved_lookup.COMMON_SHARE``)."""
    a, b, c = n % 70, n // 70 + 20, (n * 11 + 3) % 70
    return (_SYLLABLES[a] + _SYLLABLES[b] + _SYLLABLES[c]).capitalize()


def bulk_rows() -> list[dict]:
    """200 rows of one saved list, undated, each a title and a channel."""
    rows = []
    for n in range(BULK_ROWS):
        topic, fmt = BULK_TOPICS[n % len(BULK_TOPICS)], BULK_FORMATS[(n // len(BULK_TOPICS) + n) % len(BULK_FORMATS)]
        title = fmt.format(t=topic.capitalize() if fmt.startswith("{t}") else topic, n=n % 7 + 1)
        rows.append({"key": f"bulk{n:03d}", "group": "bulk-list", "url": f"https://example.com/watch/{n:03d}",
                     "title": f"{title} (the {_series_name(n)} series)",
                     "desc": "", "author": f"Example Channel {n % 17}", "origin": "youtube-playlist", "folder": "Watch later"})
    return rows


def quillnote_rows() -> list[dict]:
    rows = []
    for n, line in enumerate(QUILLNOTE_POSTS.strip().splitlines()):
        title, desc = line.split("|", 1)
        origin, folder = (("chrome-bookmark", None), ("substack-saved", "Saved"), ("reddit-saved", "r/notetaking"))[0 if n < 30 else 1 if n < 40 else 2]
        rows.append({"key": f"quill{n:02d}", "group": "page-50", "url": f"https://example.com/quillnote/{n:02d}", "title": title,
                     "desc": desc, "author": AUTHORS[n % len(AUTHORS)], "origin": origin, "folder": folder})
    return rows


def all_saves(*, bulk: bool = True) -> list[dict]:
    return [*quillnote_rows(), *TRAPS, *(bulk_rows() if bulk else [])]


# ---- the retrieval cases (ruling 62's shape: a message about a topic finds the save) ---------------------------------

#: ``(save key, a message about it)``: the lookup must bring the save up by its words, whatever state it is in.
RETRIEVAL_CASES = [
    ("quill00", "does Quillnote offline sync merge conflicts line by line"),
    ("quill17", "can Quillnote search find text inside a scanned receipt attachment"),
    ("quill38", "Quillnote extends version history to 90 days for Pro"),
    ("sour02", "why does my sourdough starter smell like nail polish"),
    ("sour05", "which Dutch oven gives the best sourdough oven spring"),
    ("riley01", "what line length reads best on screen"),
    ("old40a", "espresso ratios and what they change"),
    ("bare02", "which rail passes compared are best"),
    ("why01", "idempotency keys and refunds in a billing API"),
    ("tweetdesc01", "learning the cello at forty with patient neighbours"),
    ("bulk010", None),   # the row's own title: its series name is the only word no other row shares
    ("group02", "operational transform explained"),
]
#: G246 (owner 2026-11-25, "i want them to pop when relevant"): a message that NAMES a save by its title is plainly about
#: it, whatever else the bank holds on the topic: the save must rank among the first results of every surface.
TITLE_CASES = [
    ("quill38", "Quillnote extends version history to 90 days"),
    ("sour05", "Dutch ovens for sourdough, tested"),
    ("why01", "Designing a billing API that survives refunds"),
    ("riley01", "Line length and readability"),
    ("old40a", None),   # the row's own title
]
#: ``(save key, a message that shares only a word or two with it)``: the save is not strong, so it stays in the trailing
#: "Saved links" section, below every page block ("confidence does not rank recall": a weak overlap pushes nothing aside).
WEAK_CASES = [
    ("why01", "the Helio billing API rewrite and its refunds"),
    ("quill00", "Quillnote company news this month"),
]
#: A feed item has no page, so the saved lookup cannot serve it (docs say indexed; the code reads it with a model, plan 0.10):
#: reported apart, never a gate.
FEED_CASE = ("feed01", "weekly build notes issue 41 scheduler")

# ---- the bank --------------------------------------------------------------------------------------------------------


def _git(bank: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True)


def commit_all(bank: Path, message: str) -> None:
    _git(bank, "add", "-A")
    subprocess.run(["git", "-C", str(bank), "commit", "-q", "--allow-empty", "-m", f"{message}\n\nCicada-Author: cicada"],
                   check=True, capture_output=True)


def build_bank(bank: Path, clock: date) -> dict:
    """The bank before the night: four pages on two older processed conversations each, the owner, and the eight waiting
    conversations staged by the production stager. No model is called."""
    from api.services import decay_policy, entity_body, episode_ids, markdown_parser
    from api.services.id_utils import sanitize_id
    from benchmarks.consolidation import run as bench

    bench.init_bank(bank, OWNER)
    episodes = bank / "episodes"
    old = []
    for i in range(6):
        day = (clock - timedelta(days=60 - 7 * i)).isoformat()
        ep_id = episode_ids.next_episode_id(episodes, day)
        fm = {"id": ep_id, "timestamp": f"{day}T10:00:00+00:00", "processed": True, "processed_by": "sleep",
              "origin": "claude-code", "title": f"Earlier notes {i + 1}"}
        markdown_parser.write(episodes / f"{ep_id}.md", fm, f"user: Earlier working notes, part {i + 1}.\n\nassistant: Noted.")
        old.append((ep_id, day))
    for n, row in enumerate(PAGES.strip().splitlines()):
        kind, name, summary, facts = row.split("|")
        sources = sorted([old[n % len(old)], old[(n + 3) % len(old)]], key=lambda s: s[1])
        fm = {"name": name, "type": kind, "status": "active", "confidence": 0.7, "created": sources[0][1],
              "last_referenced": sources[-1][1], **decay_policy.frontmatter_fields(decay_policy.default_class_for(kind)),
              "source_episodes": [s[0] for s in sources], "tags": [], "aliases": [], "related": [], "version": 1, "layout_version": 2}
        body = entity_body.compose_body_v2(
            summary=summary, key_facts=[f.strip() for f in facts.split(";") if f.strip()], history_entries=[], related=[],
            links=[], open_questions=[], name=name, entity_type=kind)
        markdown_parser.write(bank / "entities" / f"{sanitize_id(name)}.md", fm, body)
    commit_all(bank, "Saves battery seed")
    staged = bench.stage(bank, CONVERSATIONS, clock, "Saves battery conversations")
    return {"pages": len(PAGES.strip().splitlines()) + 1, "conversations": len(CONVERSATIONS), "staged": staged}


def capture_saves(bank: Path, clock: date, rows: list[dict]) -> dict:
    """Write every save as capture writes it on dev. Returns the manifest: episode id → what the save is. The
    fixture's own ``age`` is days before ``clock``; undated rows are saved at the wall clock, as capture does."""
    from api.services import markdown_parser, media_ingestor as mi, tab_groups

    idx = mi.load_url_index(bank)
    manifest: dict[str, dict] = {}
    today = datetime.now().date()
    groups = [r for r in rows if r.get("via") == "tab-group"]
    if groups:
        # One snapshot of the browser's open groups: a second call would tombstone the first call's groups (they are gone).
        before = {p.name for p in (bank / "episodes").glob("*.md")}
        tab_groups.sync(bank, {"browser": "chrome", "profile": "Default", "groups": [
            {"title": g["title"], "color": "blue", "saved_guid": g["key"], "tabs": [{"title": t, "url": u} for t, u in g["tabs"]]}
            for g in groups]}, bank=bank.name)
        for p in sorted((bank / "episodes").glob("*.md")):
            if p.name not in before:
                title = (markdown_parser.parse(p).frontmatter or {}).get("title", "")
                g = next(g for g in groups if f"Tab group: {g['title']}" == title)
                manifest[p.stem] = {"key": g["key"], "group": g["group"], "kind": "tab-group", "text": g["title"]}
    for row in rows:
        if row.get("via") == "tab-group":
            continue
        age = int(row.get("age") or 0)
        added = (today - timedelta(days=age)).isoformat() if age else None
        item = mi.RawItem(
            url=row["url"], title=row["title"], channel=row.get("author"), added=added, note=row.get("note"),
            folder=row.get("folder"), origin=row.get("origin"), reason=row.get("reason"), posted=row.get("posted"),
            published_at=(row.get("published_at") or "").replace("{today}", today.isoformat()) or None)
        meta = mi.MediaMeta(title=row["title"], description=row.get("desc") or "", site="example.com", channel=row.get("author"),
                            media_type=mi._classify(row["url"], from_bookmark_file=str(row.get("origin") or "").endswith("-bookmark")))
        # Ruling 80: the 200 undated rows are one list read (a bulk: they wait their turn); every other row is a save made singly.
        result = mi.write_prepared(mi.PreparedItem(item, meta, from_bookmark_file=True), bank, idx, append_list=True,
                                   bulk=row["group"] == "bulk-list")
        if result.status == "created":
            manifest[result.episode_id] = {"key": row["key"], "group": row["group"], "kind": "save",
                                           "text": f"{row['title']} {row.get('desc') or ''} {row.get('note') or ''}"}
        else:
            manifest.setdefault(result.episode_id, {"key": row["key"], "group": row["group"], "kind": "save", "text": ""})[
                "also_saved_as"] = row["key"]
    mi.save_url_index(bank, idx)
    commit_all(bank, "Saves battery captured")
    return manifest


def capture_state(bank: Path, manifest: dict) -> dict:
    """What capture left each save as, by ``history_index.kind`` and ``processed``: counts only."""
    from api.services import history_index, markdown_parser

    counts: dict[str, int] = {}
    for ep_id in manifest:
        fm = markdown_parser.parse(bank / "episodes" / f"{ep_id}.md").frontmatter or {}
        kind = history_index.kind(fm) or "model"
        state = "read-by-index" if fm.get("processed") else "waiting-for-model"
        counts[f"{kind}/{state}"] = counts.get(f"{kind}/{state}", 0) + 1
    return counts


def wake_saves(bank: Path, manifest: dict, *, include_bulk: bool, commit: bool = True) -> dict:
    """The single-read leg's one move: every save the index read is woken, as the person naming it would wake it
    (``history_index.wake``, the product's own function: ``read_asked`` stamped, ``processed`` false, ``processed_by`` dropped).
    Saves that wait already (a reason, a feed item, a connector note) are left as they are. A save ``wake`` refuses (a record
    that is not mentionable) stays indexed. ``include_bulk`` false leaves the list's 200 rows in the pile."""
    from api.services import history_index, markdown_parser, saved_mentions

    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    woken = refused = skipped_bulk = 0
    for ep_id, meta in manifest.items():
        fm = markdown_parser.parse(bank / "episodes" / f"{ep_id}.md").frontmatter or {}
        if history_index.kind(fm) not in ("saved", "list"):
            continue
        if meta["group"] == "bulk-list" and not include_bulk:
            skipped_bulk += 1
            continue
        if history_index.wake(bank, ep_id, saved_mentions.WHY_TITLE, at):
            woken += 1
        else:
            refused += 1
    if commit:
        commit_all(bank, "Saves battery woken")
    return {"woken": woken, "refused": refused, "bulk_left_in_pile": skipped_bulk}


def waiting_group(bank: Path, manifest: dict, group: str) -> int:
    """How many saves of one fixture group wait for Sleep's model right now."""
    from api.services import history_index, markdown_parser

    return sum(1 for ep_id, meta in manifest.items() if meta["group"] == group and history_index.waits_for_model(
        markdown_parser.parse(bank / "episodes" / f"{ep_id}.md").frontmatter or {}))


def waiting_for_model(bank: Path) -> dict:
    """Episodes waiting for Sleep's model: the conversations and the saves, by the predicate every queue count uses."""
    from api.services import history_index, markdown_parser

    waiting = saves = 0
    for p in (bank / "episodes").glob("*.md"):
        fm = markdown_parser.parse(p).frontmatter or {}
        if history_index.waits_for_model(fm):
            waiting += 1
            saves += bool(fm.get("media_entity_id") or fm.get("url") or str(fm.get("source") or "") == "tab-group")
    return {"waiting": waiting, "waiting_saves": saves}


def write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
