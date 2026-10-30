import Foundation

/// G132 phase 3b — the words for the relay and for pairing a computer through it (Settings → Devices). DR-59: sentence
/// case, plain verbs. Provider-neutral: "the relay" is the step, never a company's name; the person's own relay
/// address is the only name shown. No key, slot, path or variable is shown.
extension Copy {
    enum Relay {
        static let title = "Relay"
        static let detailOff = "Off. Your computers reach each other directly on your network or private network."
        static let detailOn = "Your computers reach each other directly when they can, and through this relay when "
            + "they can't. It carries only sealed messages it can't read."
        static let addressTitle = "Relay address"
        static let addressPlaceholder = "wss://relay.example.net"
        static let save = "Use this relay"
        static let turnOff = "Turn off"
        static let badAddress = "A relay address starts with wss://."
        static let notReachable = "The relay isn't reachable from this computer right now. Pair on your network "
            + "instead, or try again in a moment."

        // The home's sheet
        static let pairButton = "Pair a computer through the relay"
        static let pairTitle = "Pair a computer through the relay"
        static let pairLead = "On the other computer, open Cicada → Settings → Devices, choose Join with a code, and "
            + "type this code with this computer's relay address."
        static func asks(_ name: String) -> String { "\(name) wants to keep a copy of your memory." }
        static let compare = "Check that the same six digits show on both screens."
        static let confirm = "They match, add it"
        static let confirmScanned = "Add it"
        static let waiting = "Waiting for the other computer…"
        static let added = "Added. It makes its copy through the relay now."
        static let voided = "Two devices answered this code, so neither was added. Start again with a new code."
        static let expired = "This code ran out. Start again with a new code."
        static let newCode = "New code"
        static let close = "Close"
        static let cancel = "Cancel"

        // The new computer's form
        static let joinTitle = "Join with a code"
        static let joinDetail = "Keep a copy of the memory another of your computers holds, through its relay."
        static let codeTitle = "Code"
        static let codePlaceholder = "The code the other computer shows"
        static let join = "Join"
        static let joinFailed = "That didn't work. Nothing was changed."
        static let joinConfirm = "They match"
    }
}
