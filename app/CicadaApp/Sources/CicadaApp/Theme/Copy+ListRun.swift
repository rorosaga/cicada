import Foundation

/// G245 (owner 2026-11-24, answer 6) — the words for the one shell line that runs the person's own AI app over the lists
/// that are due. Cicada starts nothing and schedules nothing: it prints the line, the person's own scheduler runs it. Its
/// own file for the reason `Copy+Inbox.swift` gives. Provider-neutral (owner 2026-09-30): "your AI app", never a product.
extension Copy {
    enum ListRun {
        static let title = "Read your lists every day"
        static let sentence = "Put one line in your own scheduler, and your AI app reads the lists that are due once a day. "
            + "Cicada starts nothing and schedules nothing."
        /// What it is, said plainly (owner 2026-11-24): the exposure and the limit, in the row, never behind a link.
        static let exposure = "It runs your AI app with its normal tools with nobody watching, and it reads other people’s "
            + "posts while signed in as you. A separate browser profile signed in only to the sites being read is "
            + "recommended. Cicada cannot limit what your AI app does in your browser."
        static let copyCommand = "Copy the line"
        static let copyCommandHelp = "The one shell line for your own cron or launchd: your AI app and the words it is given"
        static let copied = "Copied. Put it in your own scheduler."
        static let unavailable = "Couldn’t get the line just now. Open this page again to retry."
        static let exampleFold = "A launchd example"
        /// The example the fold shows: the line goes in a file, the job runs the file. Placeholders only; launchd has a
        /// short PATH, so the file names the full path to the app's command.
        static let launchdIntro = "Save the copied line in a file, for example ~/cicada-daily.sh, and give the command its "
            + "full path (launchd’s PATH is short). Then save this as ~/Library/LaunchAgents/example.cicada-daily.plist "
            + "and load it with launchctl."
        static let launchdExample = """
            <?xml version="1.0" encoding="UTF-8"?>
            <plist version="1.0"><dict>
              <key>Label</key><string>example.cicada-daily</string>
              <key>ProgramArguments</key>
              <array><string>/bin/sh</string><string>/Users/you/cicada-daily.sh</string></array>
              <key>StartCalendarInterval</key>
              <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
            </dict></plist>
            """
    }
}
