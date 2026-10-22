----------------------------- MODULE VideoQueue -----------------------------
(***************************************************************************)
(* The G162 video queue's lease lifecycle. Each locked read-modify-write   *)
(* in api/services/video_queue.py is one step (video_queue._locked:250     *)
(* around video_queue._write:263). A call is a snapshot step and a locked  *)
(* step, fused where that drops no behaviour (see Free). Before ruling 34  *)
(* every writer read the saved videos BEFORE the lock (finding F2); fix F2 *)
(* reads them under it (video_queue.complete:739), so with F2 the snapshot *)
(* is never stale. A record is three steps: the episode                    *)
(* (mcp_tools.record_watch:635), the credit's snapshot, and the locked     *)
(* credit (mcp_tools.record_watch:651). Properties are judged on outcomes, *)
(* with history the code does not keep (`holder`, each record's place      *)
(* against the request), never with the operator a fix edits.              *)
(* Statechart: statechart.md. Coverage, bounds and abstractions: SKILL.md. *)
(* Ruling 34 (2026-10-22) put fixes F1, F2, F4 and F5 in the code: the     *)
(* code-* checks run with Fixes = {"F1", "F2", "F4", "F5"}. F3 is accepted *)
(* and stays a proposal (the fixed-* checks add it).                       *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Keys, Sessions, Person,
          LeaseTicks, FailTicks, MaxAttempts,
          CallBudget,
          Break,
          Fixes,
          Churn, Crashes,
          IdMode, Legacy, SubSecond

Actors == Sessions \cup {Person}
Wants  == {"transcript", "watch"}
Bases  == {"transcript", "frames", "none"}
Nobody == "nobody"
NoId   == <<>>
SomeKey == CHOOSE k \in Keys : TRUE
Min(a, b) == IF a < b THEN a ELSE b

\* The session id a session's calls carry: a stable harness id (session_identity.stdio_identity:54), none (the CLI
\* door's session_id "", cli_app.door:313), one shared by every conversation that omits its handle
\* (remote.runtime.resolve_handle:68), or one minted again when the process restarts (Restart). An id over 80
\* characters is "sessionless" here: video_queue.claim:679 stores it cut and every later compare is untruncated, so
\* no compare ever matches, exactly as with no id.
FirstId(s) == CASE IdMode = "shared"      -> <<"bucket", 0>>
                [] IdMode = "sessionless" -> NoId
                [] OTHER                  -> <<s, 0>>


\* `cap`: ticks left before the lease's cap (fix F4, video_queue.MAX_LEASE_PERIODS:67 lease periods from the claim,
\* video_queue._lease_cap:627); 0 when F4 is off or the row is not leased.
MaxLeasePeriods == 3
CapTicks == IF "F4" \in Fixes THEN MaxLeasePeriods * LeaseTicks ELSE 0
Row(st, w, a, ses, tok, left, fleft, cap) ==
    [st |-> st, want |-> w, att |-> a, ses |-> ses, tok |-> tok, left |-> left, fleft |-> fleft, cap |-> cap]
Absent        == Row("absent", "transcript", 0, Nobody, Nobody, 0, 0, 0)
Queued(w, a)  == Row("queued", w, a, Nobody, Nobody, 0, 0, 0)
Failed(w, a)  == Row("failed", w, a, Nobody, Nobody, 0, FailTicks, 0)
Claimed(w, a, id, tok) == Row("claimed", w, a, IF id = NoId THEN Nobody ELSE id, tok, LeaseTicks, 0, CapTicks)
Idle == [op |-> "idle", snap |-> {}, key |-> SomeKey, arg |-> "-", own |-> "-"]

(***************************************************************************)
(* A record is its fact (T transcript, F frames; a record with no basis    *)
(* satisfies nothing and is not kept) and where it sits against the row's  *)
(* current request:                                                        *)
(*   A1 written after the request, in the current wall-clock second        *)
(*   A0 written after the request, in an earlier second                    *)
(*   S1 written before the request, in its second, still the current one   *)
(*   S0 written before the request, in its second                          *)
(*   B0 written before the request, in an earlier second                   *)
(* A and the truth agree; the code also counts S as newer (CodeNewer).     *)
(* Each video keeps only the records no other record of the same fact      *)
(* dominates: every query below asks whether some record exists, and a     *)
(* dominating record answers yes to every query the dominated one does,    *)
(* now and after any new request or new second.                            *)
(***************************************************************************)
Fact(b) == CASE b = "transcript" -> "T" [] b = "frames" -> "F" [] OTHER -> "U"
Statuses == {"A1", "A0", "S1", "S0", "B0"}
DomPairs == {<<"A1", "A0">>, <<"A1", "S1">>, <<"A1", "S0">>, <<"A1", "B0">>, <<"A0", "S0">>, <<"A0", "B0">>,
             <<"S1", "S0">>, <<"S1", "B0">>, <<"S0", "B0">>}
Norm(rs) == {x \in rs : ~\E y \in rs : x.f = y.f /\ <<y.st, x.st>> \in DomPairs}
After(st) == st \in {"A1", "A0"}
Same(st)  == st \in {"S1", "S0"}
\* A new request: every record so far is older; one from the current second shares the request's second.
OnRequest(st) == CASE st = "A1" -> "S1" [] st = "S1" -> "S1" [] OTHER -> "B0"
OnSecond(st)  == CASE st = "A1" -> "A0" [] st = "S1" -> "S0" [] OTHER -> st
Fresh == IF SubSecond THEN "A1" ELSE "A0"

VARIABLES q, recs, saved, holding, pc, calls, copy, holder, sid

vars == <<q, recs, saved, holding, pc, calls, copy, holder, sid>>

Ids    == {NoId, <<"bucket", 0>>} \cup {<<s, n>> : s \in Sessions, n \in 0..1}
Recs   == [f : {"T", "F"}, st : Statuses]

TypeOK ==
    /\ \A k \in Keys : q[k].st \in {"absent", "queued", "claimed", "failed"} /\ q[k].att \in 0..MaxAttempts
                       /\ q[k].left \in 0..LeaseTicks /\ q[k].fleft \in 0..FailTicks /\ q[k].tok \in Sessions \cup {Nobody}
                       /\ q[k].cap \in 0..CapTicks /\ ("F4" \in Fixes /\ q[k].left > 0 => q[k].left <= q[k].cap)
    /\ recs \in [Keys -> SUBSET Recs]
    /\ saved \subseteq Keys
    /\ holding \in BOOLEAN
    /\ holder \in [Keys -> Sessions \cup {Nobody}]
    /\ sid \in [Sessions -> Ids]
    /\ pc \in [Actors -> [op : {"idle", "claim", "claimWrite", "release", "credit", "complete", "put", "remove", "retry"},
                          snap : SUBSET Keys, key : Keys, arg : Bases \cup Wants \cup {"-"},
                          own : Statuses \cup {"-"}]]

-----------------------------------------------------------------------------
(* The pure functions the locked steps share.                              *)

\* video_queue._lapsed:296: a claimed row whose lease_until <= now.
Lapsed(r) ==
    CASE Break = "lapse_ignores_lease" -> r.st = "claimed"
      [] Break = "no_lapse"            -> FALSE
      [] OTHER                         -> r.st = "claimed" /\ r.left = 0

\* video_queue._settle:329 a failed row past EXPIRE_FAILED_DAYS.
FailExpired(r) == r.st = "failed" /\ r.fleft = 0 /\ Break # "no_fail_expiry"

Meets(f, w) == f = "F" \/ (f = "T" /\ w = "transcript")

\* video_state.newer_than:232 compares at >=, requested_at is cut to the second (video_queue._iso:149) and an episode
\* timestamp keeps microseconds (episode_ids.utc_now_iso:221), so a record from the request's own second, even one
\* written before it, counts as newer. Fix F3 keeps requested_at to the microsecond.
CodeNewer(st) == After(st) \/ (Same(st) /\ "F3" \notin Fixes)
SatisfiesCode(rs, w) == \E r \in rs : CodeNewer(r.st) /\ Meets(r.f, w)
\* What the properties judge by: a record written after the request.
SatisfiesTrue(rs, w) == \E r \in rs : After(r.st) /\ Meets(r.f, w)
SatisfiesAny(rs, w)  == \E r \in rs : Meets(r.f, w)

\* video_queue._settle:314: failed expiry, then each lapsed lease, only when Sleep is not holding (video_queue._settle:336).
SettleRow(r, rs, hold) ==
    IF FailExpired(r) THEN Absent
    ELSE IF Lapsed(r) /\ (~hold \/ Break = "settle_ignores_holding")
         THEN IF SatisfiesCode(rs, r.want) /\ Break # "settle_ignores_records"
              THEN Absent
              ELSE IF r.att + 1 >= MaxAttempts THEN Failed(r.want, Min(r.att + 1, MaxAttempts))
                   ELSE Queued(r.want, r.att + 1)
         ELSE r

Settle(qq, rr, hold) == [k \in Keys |-> SettleRow(qq[k], rr[k], hold)]

\* video_queue._open:496: settle, then drop orphans only when the saved set is non-empty
\* (video_queue._open:505).
Open(qq, rr, hold, snap) ==
    LET s1 == Settle(qq, rr, hold) IN
    IF snap = {} THEN s1 ELSE [k \in Keys |-> IF k \in snap THEN s1[k] ELSE Absent]

\* video_queue._refresh:633: a call with a session id extends that id's unlapsed leases; no id, no refresh
\* (video_queue._refresh:637). Fix F4: never past the lease's cap (video_queue._refresh:644); a refresh only
\* extends (video_queue._refresh:645), and left <= cap always, so the new lease is Min(LeaseTicks, cap).
Extended(r) == IF "F4" \in Fixes /\ Break # "no_lease_cap" THEN Min(LeaseTicks, r.cap) ELSE LeaseTicks
Refresh(qq, id) ==
    IF id = NoId THEN qq
    ELSE [k \in Keys |-> IF qq[k].st = "claimed" /\ qq[k].ses = id /\ ~Lapsed(qq[k])
                         THEN [qq[k] EXCEPT !.left = Extended(qq[k])] ELSE qq[k]]

\* video_queue.claim:655: lease queued rows whose key is in the saved set
\* (video_queue.claim:671). Fix F1 mints a lease token per
\* claim and returns it (video_queue.claim:680); a token is modeled as the claimer itself (only its conversation
\* ever sees it). With Legacy, a row may carry no token (claimed by the code before ruling 34).
ClaimBase(qq, rr, hold, snap, id) == Refresh(Open(qq, rr, hold, snap), id)
ClaimFrom == IF Break = "claim_takes_failed" THEN {"queued", "failed"} ELSE {"queued"}
Claimable(qq, rr, hold, snap, id) == {k \in Keys : ClaimBase(qq, rr, hold, snap, id)[k].st \in ClaimFrom /\ k \in snap}
Takes(qq, rr, hold, snap, id) ==
    LET c == Claimable(qq, rr, hold, snap, id) IN IF c = {} THEN {{}} ELSE (SUBSET c) \ {{}}
Tokens(s) == IF "F1" \in Fixes THEN {s} \cup (IF Legacy THEN {Nobody} ELSE {}) ELSE {Nobody}
ClaimFn(qq, rr, hold, snap, id, take, tok) ==
    LET q1 == ClaimBase(qq, rr, hold, snap, id) IN
    [k \in Keys |-> IF k \in take THEN Claimed(q1[k].want, q1[k].att, id, tok) ELSE q1[k]]

\* video_queue.release:686: a claimed row becomes failed only with its own lease token (fix F1,
\* video_queue.release:712); a row without one answers not_yours and lapses instead. F1s, the first proposal,
\* rejected: compare session ids. With neither, the code before ruling 34: any claimed row.
MayRelease(r, s) ==
    /\ r.st = "claimed"
    /\ CASE Break = "release_ignores_token" -> TRUE
         [] "F1" \in Fixes  -> r.tok = s
         [] "F1s" \in Fixes -> sid[s] # NoId /\ r.ses = sid[s]
         [] OTHER           -> TRUE
ReleaseFn(qq, rr, hold, snap, s, k) ==
    LET q1 == Refresh(Open(qq, rr, hold, snap), sid[s]) IN
    IF MayRelease(q1[k], s) THEN [q1 EXCEPT ![k] = Failed(q1[k].want, q1[k].att)] ELSE q1

\* video_queue.complete:747. A stated basis closes the row whatever the record's age (F3, accepted by ruling
\* 34). F3s, the first proposal: compare the record's time with requested_at through newer_than (seconds). F3:
\* the same compare with requested_at kept to the microsecond. F5 (in the code): a record with no basis closes the
\* row only with the lease token (video_queue.complete:749); without F5, the code before ruling 34 compared the
\* session id.
OwnNewer(o) == CASE "F3" \in Fixes  -> After(o)
                 [] "F3s" \in Fixes -> After(o) \/ Same(o)
                 [] OTHER           -> TRUE
Done(r, o, s, b) ==
    CASE b = "frames"     -> OwnNewer(o)
      [] b = "transcript" -> r.want = "transcript" /\ OwnNewer(o)
      [] OTHER            -> /\ r.st = "claimed"
                             /\ \/ Break = "record_ignores_token"
                                \/ ("F5" \in Fixes /\ r.tok = s)
                                \/ ("F5" \notin Fixes /\ sid[s] # NoId /\ r.ses = sid[s])

\* video_queue.complete:725: no refresh when the row is absent (video_queue.complete:741). `o` is where the
\* credit's own record sits against the request.
CompleteFn(qq, rr, hold, snap, s, k, b, o) ==
    LET q1 == Open(qq, rr, hold, snap) IN
    IF q1[k].st = "absent" THEN q1
    ELSE LET q2 == Refresh(q1, sid[s]) IN
         IF Done(q1[k], o, s, b) THEN [q2 EXCEPT ![k] = Absent]
         ELSE IF Break = "stays_counts_attempt" /\ q2[k].att < MaxAttempts
              THEN [q2 EXCEPT ![k].att = q2[k].att + 1]
              ELSE q2

\* video_queue._upsert:516 (put:509): a new or failed row restarts requested_at.
Restartable == IF Break = "put_restarts_claimed" THEN {"failed", "claimed"} ELSE {"failed"}
PutFn(qq, rr, hold, snap, k, w) ==
    LET q1 == Open(qq, rr, hold, snap)
        r1 == IF w = "watch" THEN [q1[k] EXCEPT !.want = "watch"] ELSE q1[k]
    IN CASE q1[k].st = "absent"    -> [q1 EXCEPT ![k] = Queued(w, 0)]
         [] r1.st \in Restartable -> [q1 EXCEPT ![k] = Queued(r1.want, 0)]
         [] OTHER                 -> [q1 EXCEPT ![k] = r1]
PutRestarts(qq, rr, hold, snap, k) == Open(qq, rr, hold, snap)[k].st \in {"absent"} \cup Restartable

Restarted(rs) == Norm({[r EXCEPT !.st = OnRequest(r.st)] : r \in rs})
Seconded(rs)  == Norm({[r EXCEPT !.st = OnSecond(r.st)] : r \in rs})

\* video_queue.remove:550, video_queue.retry:569 (retry keeps requested_at).
RemoveFn(qq, rr, hold, snap, k) == [Open(qq, rr, hold, snap) EXCEPT ![k] = Absent]
RetryFn(qq, rr, hold, snap, k) ==
    LET q1 == Open(qq, rr, hold, snap) IN
    IF q1[k].st = "failed" THEN [q1 EXCEPT ![k] = Queued(q1[k].want, 0)] ELSE q1

\* History: who holds each lease, whatever the row's session field says.
HolderAfter(qn, a, taken) ==
    [k \in Keys |-> IF qn[k].st # "claimed" THEN Nobody ELSE IF k \in taken THEN a ELSE holder[k]]

-----------------------------------------------------------------------------
Init ==
    /\ q = [k \in Keys |-> Absent]
    /\ recs = [k \in Keys |-> {}]
    /\ saved = Keys
    /\ holding = FALSE
    /\ pc = [a \in Actors |-> Idle]
    /\ calls = [s \in Sessions |-> 0]
    /\ copy = [s \in Sessions |-> [rows |-> [k \in Keys |-> Absent], h |-> [k \in Keys |-> Nobody]]]
    /\ holder = [k \in Keys |-> Nobody]
    /\ sid = [s \in Sessions |-> FirstId(s)]

(***************************************************************************)
(* A snapshot step reads the saved set and writes only its caller's pc.    *)
(* When that read cannot be stale (Churn off, or fix F2 reads it under the *)
(* lock), the snapshot step commutes with every other step, so the model   *)
(* runs its locked step next, with only time, Sleep, a new second and a    *)
(* restart in between, and drops no behaviour of the queue. A stale        *)
(* snapshot is never fused. The episode-to-credit gap is never fused.      *)
(***************************************************************************)
SnapOnly == {"claim", "release", "complete", "put", "remove", "retry"}
StaleSnap(op) == Churn /\ ("F2" \notin Fixes \/ (op = "complete" /\ Break = "f2_credit_stale"))
Free == ~\E a \in Actors : pc[a].op \in SnapOnly /\ ~StaleSnap(pc[a].op)
Snap(a) == IF StaleSnap(pc[a].op) THEN pc[a].snap ELSE saved

CanCall(a) ==
    /\ Free
    /\ pc[a].op = "idle"
    /\ (a \in Sessions /\ CallBudget > 0) => calls[a] < CallBudget

Spend(a) == calls' = IF a \in Sessions /\ CallBudget > 0 THEN [calls EXCEPT ![a] = @ + 1] ELSE calls

Begin(a, op, k, arg) ==
    /\ CanCall(a)
    /\ pc' = [pc EXCEPT ![a] = [op |-> op, snap |-> IF op \in SnapOnly /\ StaleSnap(op) THEN saved ELSE {},
                                key |-> k, arg |-> arg, own |-> "-"]]
    /\ Spend(a)

\* video_queue.claim reads the saved videos under its lock (video_queue.claim:668, fix F2); before ruling 34 the
\* handler read them first.
ClaimBegin(s) == Begin(s, "claim", SomeKey, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, holder, sid>>

ClaimLocked(s) ==
    /\ pc[s].op = "claim"
    /\ LET sn == Snap(s) IN
       \E take \in Takes(q, recs, holding, sn, sid[s]), tok \in Tokens(s) :
          LET qn == ClaimFn(q, recs, holding, sn, sid[s], take, tok) IN
          IF Break = "nolock"
          THEN /\ copy' = [copy EXCEPT ![s] = [rows |-> qn, h |-> HolderAfter(qn, s, take)]]
               /\ pc' = [pc EXCEPT ![s].op = "claimWrite"]
               /\ UNCHANGED <<q, holder>>
          ELSE /\ q' = qn
               /\ holder' = HolderAfter(qn, s, take)
               /\ pc' = [pc EXCEPT ![s] = Idle]
               /\ UNCHANGED copy
    /\ UNCHANGED <<recs, saved, holding, calls, sid>>

\* Break "nolock" only: the read and the write of one claim are separate steps.
ClaimWrite(s) ==
    /\ Free
    /\ pc[s].op = "claimWrite"
    /\ q' = copy[s].rows
    /\ holder' = copy[s].h
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ copy' = [copy EXCEPT ![s] = [rows |-> [k \in Keys |-> Absent], h |-> [k \in Keys |-> Nobody]]]
    /\ UNCHANGED <<recs, saved, holding, calls, sid>>

\* mcp_tools.video_claim:1230 video_claim(release=[{url, code, reason}]).
ReleaseBegin(s, k) == Begin(s, "release", k, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, holder, sid>>

ReleaseLocked(s) ==
    /\ pc[s].op = "release"
    /\ LET qn == ReleaseFn(q, recs, holding, Snap(s), s, pc[s].key) IN
       /\ q' = qn
       /\ holder' = HolderAfter(qn, s, {})
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ UNCHANGED <<recs, saved, holding, calls, copy, sid>>

\* mcp_tools.record_watch:635 watch_record.record writes the episode; the credit has not run.
RecordEpisode(s, k, b) ==
    /\ k \in saved
    /\ CanCall(s)
    /\ pc' = [pc EXCEPT ![s] = [op |-> "credit", snap |-> {}, key |-> k, arg |-> b, own |-> Fresh]]
    /\ Spend(s)
    /\ recs' = IF b = "none" THEN recs ELSE [recs EXCEPT ![k] = Norm(@ \cup {[f |-> Fact(b), st |-> Fresh]})]
    /\ UNCHANGED <<q, saved, holding, copy, holder, sid>>

\* mcp_tools.record_watch:651 _credit_video_queue; video_queue.complete:739 reads the saved videos under its lock
\* (fix F2; before ruling 34, before it).
CreditBegin(s) ==
    /\ Free
    /\ pc[s].op = "credit"
    /\ pc' = [pc EXCEPT ![s].op = "complete", ![s].snap = IF StaleSnap("complete") THEN saved ELSE {}]
    /\ UNCHANGED <<q, recs, saved, holding, calls, copy, holder, sid>>

CompleteLocked(s) ==
    /\ pc[s].op = "complete"
    /\ LET k  == pc[s].key
           qn == CompleteFn(q, recs, holding, Snap(s), s, k, pc[s].arg, pc[s].own)
       IN /\ q' = qn
          /\ holder' = HolderAfter(qn, s, {})
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ UNCHANGED <<recs, saved, holding, calls, copy, sid>>

\* The queue credit never runs: it raised and _credit_video_queue swallowed it (mcp_tools._credit_video_queue:1132),
\* or the MCP process died after the episode was written.
DropCredit(s) ==
    /\ Free
    /\ Crashes
    /\ pc[s].op = "credit"
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ UNCHANGED <<q, recs, saved, holding, calls, copy, holder, sid>>

\* api/routers/videos.py _put, delete_video_queue, _retry (the person, through the app).
PutBegin(k, w) == k \in saved /\ Begin(Person, "put", k, w) /\ UNCHANGED <<q, recs, saved, holding, copy, holder, sid>>
RemoveBegin(k) == Begin(Person, "remove", k, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, holder, sid>>
RetryBegin(k)  == Begin(Person, "retry", k, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, holder, sid>>

PersonLocked ==
    /\ pc[Person].op \in {"put", "remove", "retry"}
    /\ LET sn == Snap(Person)
           k  == pc[Person].key
           op == pc[Person].op
           qn == (CASE op = "put"    -> PutFn(q, recs, holding, sn, k, pc[Person].arg)
                    [] op = "remove" -> RemoveFn(q, recs, holding, sn, k)
                    [] OTHER         -> RetryFn(q, recs, holding, sn, k))
           restart == op = "put" /\ PutRestarts(q, recs, holding, sn, k)
       IN /\ q' = qn
          /\ holder' = HolderAfter(qn, Person, {})
          /\ recs' = IF restart THEN [recs EXCEPT ![k] = Restarted(@)] ELSE recs
          \* A credit still in flight for this video now carries a record older than the new request.
          /\ pc' = [a \in Actors |-> IF a = Person THEN Idle
                                     ELSE IF restart /\ pc[a].own # "-" /\ pc[a].key = k
                                          THEN [pc[a] EXCEPT !.own = OnRequest(@)] ELSE pc[a]]
    /\ UNCHANGED <<saved, holding, calls, copy, sid>>

\* A page saved (url_index row added) or hidden (archived, junk): video_state.saved_videos.
SaveVideo(k) == Free /\ Churn /\ k \notin saved /\ saved' = saved \cup {k}
                /\ UNCHANGED <<q, recs, holding, pc, calls, copy, holder, sid>>
HideVideo(k) == Free /\ Churn /\ k \in saved /\ saved' = saved \ {k}
                /\ UNCHANGED <<q, recs, holding, pc, calls, copy, holder, sid>>

\* write_admission: Sleep takes and lets go of the pages (mcp_tools.ToolContext.pages_held:209).
SleepStart == ~holding /\ holding' = TRUE /\ UNCHANGED <<q, recs, saved, pc, calls, copy, holder, sid>>
SleepEnd   == holding /\ holding' = FALSE /\ UNCHANGED <<q, recs, saved, pc, calls, copy, holder, sid>>

\* A stdio process restarted under a harness that names no id mints a new one (session_identity.stdio_identity:61).
\* The conversation, and any lease token it was given, survives.
Restart(s) ==
    /\ IdMode = "restart"
    /\ pc[s].op = "idle"
    /\ sid[s] = FirstId(s)
    /\ sid' = [sid EXCEPT ![s] = <<s, 1>>]
    /\ UNCHANGED <<q, recs, saved, holding, pc, calls, copy, holder>>

\* The wall clock enters a new second: no record so far shares a second with a request made from now on.
Seconds == [a \in Actors |-> IF pc[a].own = "-" THEN pc[a] ELSE [pc[a] EXCEPT !.own = OnSecond(@)]]
NewSecond ==
    /\ SubSecond
    /\ \/ \E k \in Keys : \E r \in recs[k] : r.st \in {"A1", "S1"}
       \/ \E a \in Actors : pc[a].own \in {"A1", "S1"}
    /\ recs' = [k \in Keys |-> Seconded(recs[k])]
    /\ pc' = Seconds
    /\ UNCHANGED <<q, saved, holding, calls, copy, holder, sid>>

\* A lease tick (minutes) also ends the current second.
Dec(n) == IF n > 0 THEN n - 1 ELSE 0
Tick ==
    /\ \E k \in Keys : q[k].left > 0 \/ q[k].fleft > 0
    \* A lapsed lease is never refreshed again, so its cap no longer matters: it is cleared (one state, not many).
    /\ q' = [k \in Keys |-> [q[k] EXCEPT !.left = Dec(@), !.fleft = Dec(@),
                                         !.cap = IF Dec(q[k].left) = 0 THEN 0 ELSE Dec(@)]]
    /\ recs' = [k \in Keys |-> Seconded(recs[k])]
    /\ pc' = Seconds
    /\ UNCHANGED <<saved, holding, calls, copy, holder, sid>>

Next ==
    \/ \E s \in Sessions :
          \/ ClaimBegin(s) \/ ClaimLocked(s) \/ ClaimWrite(s)
          \/ \E k \in Keys : ReleaseBegin(s, k)
          \/ ReleaseLocked(s)
          \/ \E k \in Keys, b \in Bases : RecordEpisode(s, k, b)
          \/ CreditBegin(s) \/ CompleteLocked(s) \/ DropCredit(s)
          \/ Restart(s)
    \/ \E k \in Keys, w \in Wants : PutBegin(k, w)
    \/ \E k \in Keys : RemoveBegin(k) \/ RetryBegin(k) \/ SaveVideo(k) \/ HideVideo(k)
    \/ PersonLocked
    \/ SleepStart \/ SleepEnd
    \/ NewSecond
    \/ Tick

Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Tick) /\ WF_vars(SleepEnd)

-----------------------------------------------------------------------------
(* Properties. Each one's plain sentence and harm is in SKILL.md.          *)

LiveLease(r) == r.st = "claimed" /\ r.left > 0
Finishes(a, op, k) == pc[a].op = op /\ pc[a].key = k /\ pc'[a].op = "idle"
Gone(k) == q[k].st # "absent" /\ q'[k].st = "absent"
\* Reasons a row may leave that need no record: the person removed it, it aged out, its page is not saved now.
Excused(k) == Finishes(Person, "remove", k) \/ (q[k].st = "failed" /\ q[k].fleft = 0) \/ k \notin saved
\* The leaseholder's own record with no basis.
HolderRecord(k) == \E s \in Sessions : Finishes(s, "complete", k) /\ pc[s].arg = "none" /\ q[k].st = "claimed"
                                       /\ holder[k] = s
\* The lease survives the settle a locked step starts with.
StillLeased(k) == Settle(q, recs, holding)[k].st = "claimed"

\* P1. A lease that has not lapsed never passes to another session in one step.
NoDoubleClaim == [][\A k \in Keys : LiveLease(q[k]) /\ q'[k].st = "claimed" => holder'[k] = holder[k]]_vars

\* P2. A saved video's row never leaves without a reason: removed, aged out, or some record of it.
NoLostRow == [][\A k \in Keys : Gone(k) /\ ~Excused(k) => SatisfiesAny(recs[k], q[k].want) \/ HolderRecord(k)]_vars

\* P3. Only the leaseholder hands a leased video back.
ReleaseOnlyByHolder ==
    [][\A s \in Sessions, k \in Keys : Finishes(s, "release", k) /\ StillLeased(k) /\ q'[k].st = "failed"
                                       => holder[k] = s]_vars

\* P4. A credit by a session that does not hold the lease ends it only on a record newer than the request.
RecordByOtherCorruptsNothing ==
    [][\A s \in Sessions, k \in Keys :
         Finishes(s, "complete", k) /\ StillLeased(k) /\ holder[k] # s /\ k \in saved
         /\ ~(q'[k].st = "claimed" /\ holder'[k] = holder[k])
         => SatisfiesTrue(recs[k], q[k].want)]_vars

\* P5. A row closes as done only on a record written after its request, or on its leaseholder's own record.
DoneIsSupported ==
    [][\A k \in Keys : Gone(k) /\ ~Excused(k) => SatisfiesTrue(recs[k], q[k].want) \/ HolderRecord(k)]_vars

\* P6. Releasing or recording the same video twice leaves the queue as once did.
Idempotent ==
    \A s \in Sessions, k \in Keys :
        /\ LET once == ReleaseFn(q, recs, holding, saved, s, k)
           IN ReleaseFn(once, recs, holding, saved, s, k) = once
        /\ \A b \in Bases :
              LET once == CompleteFn(q, recs, holding, saved, s, k, b, Fresh)
              IN CompleteFn(once, recs, holding, saved, s, k, b, Fresh) = once

Burned(k) == q[k].st # "absent" /\ q'[k].st # "absent" /\ q'[k].att > q[k].att

\* P7. A lapse costs an attempt only while Sleep is not holding the pages.
NoBurnWhileHeld == [][\A k \in Keys : Burned(k) => ~holding]_vars

\* P8. A lapse never costs an attempt when a record newer than the request satisfies it.
NoBurnWhenSatisfied == [][\A k \in Keys : Burned(k) => ~SatisfiesTrue(recs[k], q[k].want)]_vars

\* P11. A failed video returns to the queue only when the person asks (Try again, or queueing it again).
PersonAsks == pc[Person].op \in {"put", "retry"} /\ pc'[Person].op = "idle"
FailedReturnsOnlyByPerson == [][\A k \in Keys : q[k].st = "failed" /\ q'[k].st \in {"queued", "claimed"} => PersonAsks]_vars

\* P12. A live lease ends only by a release, a record's credit, the person's Remove, or its page going away.
LegitEnd(k) ==
    \/ \E a \in Actors : \E op \in {"release", "complete", "remove"} : Finishes(a, op, k)
    \/ q'[k].st = "absent" /\ k \notin saved
NoLeaseTakenAway ==
    [][\A k \in Keys : LiveLease(q[k]) /\ ~(q'[k].st = "claimed" /\ holder'[k] = holder[k]) => LegitEnd(k)]_vars

\* P13. A session can always hand back a live lease it holds.
HolderCanRelease ==
    [][\A s \in Sessions, k \in Keys : Finishes(s, "release", k) /\ LiveLease(q[k]) /\ holder[k] = s /\ k \in saved
                                       => ~(q'[k].st = "claimed" /\ holder'[k] = s)]_vars

EffClaimed(k) == q[k].st = "claimed" /\ ~(Lapsed(q[k]) /\ ~holding)

\* P9. Every lease ends in every reader's view: it lapses, is released, or is recorded.
LeaseEnds == \A k \in Keys : (q[k].st = "claimed") ~> ~EffClaimed(k)

\* P10. Every failed row eventually ages out or is tried again.
FailedEnds == \A k \in Keys : (q[k].st = "failed") ~> (q[k].st # "failed" \/ FailExpired(q[k]))

Perms == Permutations(Keys) \cup Permutations(Sessions)

=============================================================================
