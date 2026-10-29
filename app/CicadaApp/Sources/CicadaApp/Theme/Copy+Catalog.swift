import Foundation

/// G217 (ruling 36 D6) — the Sources catalogue's words. Few on purpose: a row is a mark, a name and one status word.
extension Copy {
    enum Catalog {
        static let accounts = "Accounts and browser"
        static let thisMac = "This Mac"
        static let exports = "Exports"
        static let feeds = "Feeds"
        static let conversations = "Agents' conversations"

        static let connected = "Connected"
        static let needsSignIn = "Needs sign-in"
        static let off = "Off"
        /// A list that is on but that only the person's own agent reads, while no agent on this Mac is connected.
        static let waitingForAgent = "On · waits for your agent"
        static let waitingForAgentHelp = "Your own agent reads this in your signed-in browser. Connect one on the "
            + "Agents page; until then nothing is read."
        static let justNow = "just now"

        static let connect = "Connect"
        static let connectCalendar = "Connect the calendar"
        static let connectContacts = "Connect Contacts"
        static let connectReminders = "Connect Reminders"
        static let connectNotes = "Connect Notes"
        static let chooseChats = "Choose chats"
        static let addFolder = "Add a folder"
        static let addFeed = "Add a feed"
        static let turnOn = "Turn on"
        static let importFile = "Import a file"
        static let openAgents = "Open Agents"
        static let signIn = "Sign in"
        static let manage = "Manage"
        static let refresh = "Refresh"

        static let folders = "Folders"
        static let filesAndLinks = "Files and links"
        static let chatExports = "Chat exports"
        /// G219 slice 1: a Notion export, imported once through the one intake; Cicada never writes to Notion.
        static let notionHow = "In Notion, open Settings, then Export all workspace content (or Export on one page), "
            + "choose Markdown & CSV with subpages, and drop the zip here. Pages and database rows come in as they are, "
            + "dated when they were created; importing again only adds what changed. Cicada never writes to Notion."
        static let calendarFeeds = "Calendar feeds"

        /// 2026-10-26 — where each platform hands out the file an "Import a file" row takes, in the platform's own
        /// words, checked that day (TikTok against its data-types page; the backend reads today's JSON layout).
        static let howYouTube = "From Google Takeout: Deselect all, tick YouTube and YouTube Music, keep history and "
            + "playlists, export once, and drop the .zip here."
        static let howInstagram = "From Instagram: Accounts Center → Your information and permissions → Export your "
            + "information → Saved, format JSON. Unzip it and drop saved_posts.json here."
        static let howTikTok = "From TikTok: Profile → menu → Settings and privacy → Account → Download your data, "
            + "file format JSON. When it's ready (a few days), unzip it and drop user_data_tiktok.json here."
        static let howSpotify = "From Spotify: on spotify.com, open Account → Privacy settings → Download your "
            + "data, and ask for Extended streaming history (every play) or Account data (the last year and your "
            + "library). Spotify emails a .zip, which can take up to 30 days; drop it here. Each day of listening "
            + "becomes one entry, and your liked songs, albums and podcasts become saved items."
        static let howLinkedIn = "From LinkedIn: Settings → Data privacy → Get a copy of your data → Saved items. "
            + "Unzip the archive and drop Saved Items.csv here."
        static let howBookmarksFile = "A bookmarks file any browser exports (HTML or JSON) — in Chrome, Bookmarks → "
            + "Bookmark manager → ⋮ → Export bookmarks."
        static let whatCameIn = "What came in"
        static let reading = "Reading"
        static func readSite(_ name: String) -> String { "Your agent may read \(name) in your browser" }
        /// G206 (#426) — what exists: the person's own agent on this Mac reads the saved list in their signed-in browser
        /// once its switch is on, at most 10 reads a day; or an export. (2026-10-23: it said "coming".)
        static let instagramHonest = "Your own agent on this Mac can read your Saved posts in your signed-in browser — "
            + "turn on the list below. Or import a data export."
        static let savedListOff = "Your own agent reads this list in your signed-in browser, at most 10 times a day. "
            + "Saved posts are kept for lookup, never read."
        static func readSavedList(_ site: String) -> String {
            switch site {
            case "x": "Read my Bookmarks in my browser"
            case "linkedin": "Read my Saved posts in my browser"
            default: "Read my Saved in my browser"
            }
        }
        static let chatExportsHere = "Each chat export sits on its agent's row."
        static let dropHint = "Drop an export or a bookmarks file here."
        static func eyebrow(_ connected: Int) -> String { "\(connected) connected" }

        // 2026-10-23 — connectors that work, said as they work.
        static let disconnect = "Disconnect"
        static let howToSetUp = "How to set it up"
        /// Apple Notes keeps up once read, and only while Notes is open (`AppleNotesWatcher`).
        static let notesOff = "Cicada reads every folder once when you connect, then every two hours while Notes is "
            + "open. macOS asks once whether Cicada may read Notes."
        static let notesOn = "Reads new and edited notes every two hours while Notes is open."
        /// Telegram reaches Cicada only through a webhook on a public address (`POST /capture/telegram`).
        static let telegramHonest = "Telegram needs a public web address that reaches this Mac, and Cicada doesn't "
            + "open one. A developer setup for now."
    }
}
