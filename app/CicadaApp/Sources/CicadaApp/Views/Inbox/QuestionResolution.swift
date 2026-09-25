import Foundation

/// What a focus-card answer resolves to — one value instead of four
/// positional arguments, so adding a channel (option key, remind window) never
/// churns every call site again.
struct QuestionResolution: Equatable {
    let action: String
    var answer: String? = nil
    var optionKey: String? = nil
    var remindDays: Int? = nil
    var mergeTarget: String? = nil
    var mergeSurvivor: String? = nil
}

/// "Keep separate" on a merge suggestion — a REMEMBERED verdict, not a
/// dismissal (G113 slice 3b: the backend records the pair in
/// `_merge_rejected.yaml` so neither `clarification_manager` nor the dedup
/// sweep proposes it again). `inbox_service.resolve` needs the other side of
/// the pair, taking `merge_target_hint` OR `mergeTarget`; the hint is absent
/// for a hintless "Possible duplicate" and for every migrated item, so the
/// view has to send what the person has in the target field. `nil` here means
/// "there is no pair yet" — the caller disables the button rather than firing
/// a request the backend must 400.
enum MergeReject {
    static func resolution(existingName: String) -> QuestionResolution? {
        let target = existingName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !target.isEmpty else { return nil }
        return QuestionResolution(action: "reject", mergeTarget: target)
    }
}
