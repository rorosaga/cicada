import Foundation

/// TODO ruling 4b and owner decision 2 (2026-10-16): Settings → Sleep's "Scheduled runs may use my plan" (on by default
/// since 2026-10-19), and what the page says when a schedule has no engine it may use. Its own file (one per track). Provider-neutral: the switch says
/// "my plan" — the plan the person signed in to — and no string names a provider as the one doing the job.
extension Copy {
    enum ServerPlan {
        static let groupTitle = "Scheduled runs"
        static let usePlanTitle = "Scheduled runs may use my plan"
        /// Said beside the switch while it is on (the default, 2026-10-19): what it costs.
        static let usePlanOnDetail =
            "Runs on their own may read with the plan you signed in to. They count against its limits, like the runs "
            + "you start; one that reaches a limit pauses, and the next picks up once the limit resets."
        static let usePlanOffDetail =
            "Off: a run on its own never reads with your plan — only with an API key you chose or a local model. Runs "
            + "you start may always use your plan."
        static let writeFailed = "That didn't save. Try again."

        /// The fix for each `warningCode` the server sends, in the app's words — connecting the plan first.
        static func fix(for code: String?) -> String? {
            switch code {
            case "no_engine":
                "Connect your plan in Engines and leave “\(usePlanTitle)” on, or choose an API key as Sleep's engine."
            case "plan_signed_out":
                "Sign in to your plan again in Engines."
            case "plan_not_chosen":
                "Choose your plan as Sleep's engine in Engines."
            case "local_down":
                "Start the local model, or choose another engine in Engines."
            default:
                nil
            }
        }

        /// The warning line: the server's sentence, then the app's fix.
        static func warningLine(_ warning: String?, code: String?) -> String? {
            guard let warning, !warning.isEmpty else { return nil }
            return [warning, fix(for: code)].compactMap { $0 }.joined(separator: " ")
        }
    }
}
