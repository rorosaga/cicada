----------------------------- MODULE VideoQueue -----------------------------
(***************************************************************************)
(* The G162 video queue's lease lifecycle, one atomic step per locked      *)
(* read-modify-write in api/services/video_queue.py (`_locked` + `_write`, *)
(* lines 229-256). Every writer snapshots the saved videos BEFORE it takes *)
(* the lock (put:514, claim:623, release:647, complete:682, and the MCP    *)
(* handler at mcp_tools.py:1204), so each operation is two steps here,    *)
(* Begin (the snapshot) and its Locked step, fused where that is sound     *)
(* (see Fused). record_watch writes the                                    *)
(* episode first and credits the queue after (mcp_tools.py:613 then :629), *)
(* so a record is two steps too. Time is relative: a lease counts down     *)
(* `left` ticks, a failed row `fleft` ticks. Records keep only the facts   *)
(* newer than the row's requested_at, which is all `satisfies` reads       *)
(* (video_state.py:242). Statechart and coverage: statechart.md, SKILL.md. *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Keys, Sessions, Person,
          LeaseTicks, FailTicks, MaxAttempts,
          CallBudget,
          Break,
          Fixes,
          Churn, Crashes

Actors == Sessions \cup {Person}
Wants  == {"transcript", "watch"}
Bases  == {"transcript", "frames", "none"}
Nobody == "nobody"
SomeKey == CHOOSE k \in Keys : TRUE

Absent == [st |-> "absent", want |-> "transcript", att |-> 0, ses |-> Nobody, left |-> 0, fleft |-> 0]
Queued(w, a) == [st |-> "queued", want |-> w, att |-> a, ses |-> Nobody, left |-> 0, fleft |-> 0]
Failed(w, a) == [st |-> "failed", want |-> w, att |-> a, ses |-> Nobody, left |-> 0, fleft |-> FailTicks]
Claimed(w, a, s) == [st |-> "claimed", want |-> w, att |-> a, ses |-> s, left |-> LeaseTicks, fleft |-> 0]
Min(a, b) == IF a < b THEN a ELSE b
Idle == [op |-> "idle", snap |-> {}, key |-> SomeKey, arg |-> "-"]

VARIABLES q, recs, saved, holding, pc, calls, copy,
          lost, relTrespass, recTrespass, unsupported

vars == <<q, recs, saved, holding, pc, calls, copy, lost, relTrespass, recTrespass, unsupported>>

Rows == [st : {"absent", "queued", "claimed", "failed"}, want : Wants, att : 0..MaxAttempts,
         ses : Sessions \cup {Nobody}, left : 0..LeaseTicks, fleft : 0..FailTicks]

TypeOK ==
    /\ q \in [Keys -> Rows]
    /\ recs \in [Keys -> SUBSET {"T", "F"}]
    /\ saved \subseteq Keys
    /\ holding \in BOOLEAN
    /\ pc \in [Actors -> [op : {"idle", "claim", "claimWrite", "release", "complete", "put", "remove", "retry"},
                          snap : SUBSET Keys, key : Keys, arg : Bases \cup Wants \cup {"-"}]]

-----------------------------------------------------------------------------
(* The pure functions the locked steps share.                              *)

\* video_queue.py:276 `_lapsed`: a claimed row whose lease_until <= now.
Lapsed(r) ==
    CASE Break = "lapse_ignores_lease" -> r.st = "claimed"
      [] Break = "no_lapse"            -> FALSE
      [] OTHER                         -> r.st = "claimed" /\ r.left = 0

\* video_queue.py:308 a failed row past EXPIRE_FAILED_DAYS.
FailExpired(r) == r.st = "failed" /\ r.fleft = 0 /\ Break # "no_fail_expiry"

\* video_state.py:242 `satisfies` over the records newer than requested_at.
SatisfiesNew(rs, w) == "F" \in rs \/ ("T" \in rs /\ w = "transcript")

\* video_queue.py:294 `_settle`: failed expiry, then each lapsed lease (only when Sleep is not holding, :316).
SettleRow(r, rs, hold) ==
    IF FailExpired(r) THEN Absent
    ELSE IF Lapsed(r) /\ (~hold \/ Break = "settle_ignores_holding")
         THEN IF SatisfiesNew(rs, r.want) /\ Break # "settle_ignores_records"
              THEN Absent
              ELSE IF r.att + 1 >= MaxAttempts THEN Failed(r.want, Min(r.att + 1, MaxAttempts))
                   ELSE Queued(r.want, r.att + 1)
         ELSE r

Settle(qq, rr, hold) == [k \in Keys |-> SettleRow(qq[k], rr[k], hold)]

\* video_queue.py:474 `_open`: settle, then drop orphans only when the snapshot is non-empty (:482).
Open(qq, rr, hold, snap) ==
    LET s1 == Settle(qq, rr, hold) IN
    IF snap = {} THEN s1 ELSE [k \in Keys |-> IF k \in snap THEN s1[k] ELSE Absent]

Orphans(qq, rr, hold, snap) ==
    IF snap = {} THEN {} ELSE {k \in Keys : k \notin snap /\ Settle(qq, rr, hold)[k].st # "absent"}

\* video_queue.py:602 `_refresh`: any call by a session extends its unlapsed leases.
Refresh(qq, s) ==
    [k \in Keys |-> IF qq[k].st = "claimed" /\ qq[k].ses = s /\ ~Lapsed(qq[k])
                    THEN [qq[k] EXCEPT !.left = LeaseTicks] ELSE qq[k]]

\* video_queue.py:613 `claim`: lease queued rows whose key is in the snapshot (:627).
ClaimBase(qq, rr, hold, snap, s) == Refresh(Open(qq, rr, hold, snap), s)
ClaimFrom == IF Break = "claim_takes_failed" THEN {"queued", "failed"} ELSE {"queued"}
Claimable(qq, rr, hold, snap, s) == {k \in Keys : ClaimBase(qq, rr, hold, snap, s)[k].st \in ClaimFrom /\ k \in snap}
Takes(qq, rr, hold, snap, s) ==
    LET c == Claimable(qq, rr, hold, snap, s) IN IF c = {} THEN {{}} ELSE (SUBSET c) \ {{}}
ClaimFn(qq, rr, hold, snap, s, take) ==
    LET q1 == ClaimBase(qq, rr, hold, snap, s) IN
    [k \in Keys |-> IF k \in take THEN Claimed(q1[k].want, q1[k].att, s) ELSE q1[k]]

\* video_queue.py:641 `release`: any claimed row becomes failed (:661); the session is not compared.
Releasable(r, s) == r.st = "claimed" /\ ("F1" \in Fixes => r.ses = s)
ReleaseFn(qq, rr, hold, snap, s, k) ==
    LET q1 == Refresh(Open(qq, rr, hold, snap), s) IN
    IF Releasable(q1[k], s) THEN [q1 EXCEPT ![k] = Failed(q1[k].want, q1[k].att)] ELSE q1

\* video_queue.py:692 the satisfaction table. Fix F3: a stated basis closes only on a record newer than the request.
Done(r, rs, s, b) ==
    CASE b = "frames"     -> "F3" \in Fixes => "F" \in rs
      [] b = "transcript" -> r.want = "transcript" /\ ("F3" \in Fixes => "T" \in rs)
      [] OTHER            -> r.st = "claimed" /\ (r.ses = s \/ Break = "record_ignores_session")

\* video_queue.py:674 `complete`: no refresh when the row is absent (:688).
CompleteFn(qq, rr, hold, snap, s, k, b) ==
    LET q1 == Open(qq, rr, hold, snap) IN
    IF q1[k].st = "absent" THEN q1
    ELSE LET q2 == Refresh(q1, s) IN
         IF Done(q1[k], rr[k], s, b) THEN [q2 EXCEPT ![k] = Absent]
         ELSE IF Break = "stays_counts_attempt" /\ q2[k].att < MaxAttempts
              THEN [q2 EXCEPT ![k].att = q2[k].att + 1]
              ELSE q2

\* video_queue.py:493 `_upsert` (put:509): a new or failed row restarts requested_at.
Restartable == IF Break = "put_restarts_claimed" THEN {"failed", "claimed"} ELSE {"failed"}
PutFn(qq, rr, hold, snap, k, w) ==
    LET q1 == Open(qq, rr, hold, snap)
        r1 == IF w = "watch" THEN [q1[k] EXCEPT !.want = "watch"] ELSE q1[k]
    IN CASE q1[k].st = "absent"     -> [q1 EXCEPT ![k] = Queued(w, 0)]
         [] r1.st \in Restartable  -> [q1 EXCEPT ![k] = Queued(r1.want, 0)]
         [] OTHER               -> [q1 EXCEPT ![k] = r1]
PutRestarts(qq, rr, hold, snap, k) == Open(qq, rr, hold, snap)[k].st \in {"absent"} \cup Restartable

\* video_queue.py:526 `remove`, :545 `retry` (retry keeps requested_at).
RemoveFn(qq, rr, hold, snap, k) == [Open(qq, rr, hold, snap) EXCEPT ![k] = Absent]
RetryFn(qq, rr, hold, snap, k) ==
    LET q1 == Open(qq, rr, hold, snap) IN
    IF q1[k].st = "failed" THEN [q1 EXCEPT ![k] = Queued(q1[k].want, 0)] ELSE q1

FactsOf(b) == CASE b = "transcript" -> {"T"} [] b = "frames" -> {"F"} [] OTHER -> {}

\* A locked step's bookkeeping: an orphan dropped while its key is saved right now is a lost row.
Lose(dropped) == lost' = (lost \/ (dropped \cap saved # {}))

-----------------------------------------------------------------------------
Init ==
    /\ q = [k \in Keys |-> Absent]
    /\ recs = [k \in Keys |-> {}]
    /\ saved = Keys
    /\ holding = FALSE
    /\ pc = [a \in Actors |-> Idle]
    /\ calls = [s \in Sessions |-> 0]
    /\ copy = [s \in Sessions |-> [k \in Keys |-> Absent]]
    /\ lost = FALSE /\ relTrespass = FALSE /\ recTrespass = FALSE /\ unsupported = FALSE

(***************************************************************************)
(* With Churn off the saved set never changes, so a Begin step reads a     *)
(* constant and writes only its caller's pc; with fix F2 the locked step   *)
(* reads the saved set itself. Either way, running the Locked step next,   *)
(* with only time and Sleep allowed in between, drops no behaviour of the  *)
(* queue. The record-then-credit gap is not a Begin and always stays open. *)
(***************************************************************************)
SnapOnly == {"claim", "release", "put", "remove", "retry"}
Fused == ~Churn \/ "F2" \in Fixes
Free == ~(Fused /\ \E a \in Actors : pc[a].op \in SnapOnly)

CanCall(a) ==
    /\ Free
    /\ pc[a].op = "idle"
    /\ (a \in Sessions /\ CallBudget > 0) => calls[a] < CallBudget

Spend(a) == calls' = IF a \in Sessions /\ CallBudget > 0 THEN [calls EXCEPT ![a] = @ + 1] ELSE calls

Begin(a, op, k, arg) ==
    /\ CanCall(a)
    /\ pc' = [pc EXCEPT ![a] = [op |-> op, snap |-> IF "F2" \in Fixes THEN {} ELSE saved, key |-> k, arg |-> arg]]
    /\ Spend(a)

\* Fix F2: the saved videos are read under the lock, so the locked step sees them as they are now.
Snap(a) == IF "F2" \in Fixes THEN saved ELSE pc[a].snap

Ghosts == <<lost, relTrespass, recTrespass, unsupported>>

\* mcp_tools.py:1204 `saved` snapshot, then video_queue.claim under the lock.
ClaimBegin(s) == Begin(s, "claim", SomeKey, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, Ghosts>>

ClaimLocked(s) ==
    /\ pc[s].op = "claim"
    /\ LET sn == Snap(s) IN
       \E take \in Takes(q, recs, holding, sn, s) :
          IF Break = "nolock"
          THEN /\ copy' = [copy EXCEPT ![s] = ClaimFn(q, recs, holding, sn, s, take)]
               /\ pc' = [pc EXCEPT ![s] = [@ EXCEPT !.op = "claimWrite", !.snap = take]]
               /\ UNCHANGED <<q, lost>>
          ELSE /\ q' = ClaimFn(q, recs, holding, sn, s, take)
               /\ Lose(Orphans(q, recs, holding, sn))
               /\ pc' = [pc EXCEPT ![s] = Idle]
               /\ UNCHANGED copy
    /\ UNCHANGED <<recs, saved, holding, calls, relTrespass, recTrespass, unsupported>>

\* Break "nolock" only: the read and the write of one claim are separate steps.
ClaimWrite(s) ==
    /\ Free
    /\ pc[s].op = "claimWrite"
    /\ q' = copy[s]
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ copy' = [copy EXCEPT ![s] = [k \in Keys |-> Absent]]
    /\ UNCHANGED <<recs, saved, holding, calls, Ghosts>>

\* mcp_tools.py:1206 video_claim(release=[{url, code, reason}]).
ReleaseBegin(s, k) == Begin(s, "release", k, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, Ghosts>>

ReleaseLocked(s) ==
    /\ pc[s].op = "release"
    /\ LET sn == Snap(s)
           k  == pc[s].key
           q1 == Refresh(Open(q, recs, holding, sn), s)
       IN /\ q' = ReleaseFn(q, recs, holding, sn, s, k)
          /\ relTrespass' = (relTrespass \/ (Releasable(q1[k], s) /\ q1[k].ses # s))
          /\ Lose(Orphans(q, recs, holding, sn))
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ UNCHANGED <<recs, saved, holding, calls, copy, recTrespass, unsupported>>

\* mcp_tools.py:613 watch_record.record writes the episode; :629 then credits the queue.
RecordEpisode(s, k, b) ==
    /\ k \in saved
    /\ Begin(s, "complete", k, b)
    /\ recs' = [recs EXCEPT ![k] = @ \cup FactsOf(b)]
    /\ UNCHANGED <<q, saved, holding, copy, Ghosts>>

CompleteLocked(s) ==
    /\ Free
    /\ pc[s].op = "complete"
    /\ LET sn == Snap(s)
           k  == pc[s].key
           b  == pc[s].arg
           q1 == Open(q, recs, holding, sn)
           closes == q1[k].st # "absent" /\ Done(q1[k], recs[k], s, b)
           supported == SatisfiesNew(recs[k], q1[k].want) \/ (b = "none" /\ q1[k].st = "claimed" /\ q1[k].ses = s)
       IN /\ q' = CompleteFn(q, recs, holding, sn, s, k, b)
          /\ unsupported' = (unsupported \/ (closes /\ ~supported))
          /\ recTrespass' = (recTrespass \/ (closes /\ ~supported /\ q1[k].st = "claimed" /\ q1[k].ses # s))
          /\ Lose(Orphans(q, recs, holding, sn))
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ UNCHANGED <<recs, saved, holding, calls, copy, relTrespass>>

\* api/routers/videos.py:137 put, :151 remove, :156 retry (the person, through the app).
PutBegin(k, w) == k \in saved /\ Begin(Person, "put", k, w) /\ UNCHANGED <<q, recs, saved, holding, copy, Ghosts>>
RemoveBegin(k) == Begin(Person, "remove", k, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, Ghosts>>
RetryBegin(k)  == Begin(Person, "retry", k, "-") /\ UNCHANGED <<q, recs, saved, holding, copy, Ghosts>>

PersonLocked ==
    /\ pc[Person].op \in {"put", "remove", "retry"}
    /\ LET sn == Snap(Person)
           k  == pc[Person].key
           op == pc[Person].op
           dropped == Orphans(q, recs, holding, sn)
       IN /\ q' = (CASE op = "put"    -> PutFn(q, recs, holding, sn, k, pc[Person].arg)
                     [] op = "remove" -> RemoveFn(q, recs, holding, sn, k)
                     [] OTHER         -> RetryFn(q, recs, holding, sn, k))
          /\ recs' = IF op = "put" /\ PutRestarts(q, recs, holding, sn, k) THEN [recs EXCEPT ![k] = {}] ELSE recs
          /\ Lose(dropped)
    /\ pc' = [pc EXCEPT ![Person] = Idle]
    /\ UNCHANGED <<saved, holding, calls, copy, relTrespass, recTrespass, unsupported>>

\* A request the backend drops mid-way (a crash before os.replace writes nothing).
PersonAbort == Free /\ pc[Person].op # "idle" /\ pc' = [pc EXCEPT ![Person] = Idle]
               /\ UNCHANGED <<q, recs, saved, holding, calls, copy, Ghosts>>

\* The queue credit never runs: it raised and _credit_video_queue swallowed it (mcp_tools.py:1107), or the
\* MCP process died after the episode was written. A restart keeps the harness's session id.
DropCredit(s) ==
    /\ Free
    /\ Crashes
    /\ pc[s].op = "complete"
    /\ pc' = [pc EXCEPT ![s] = Idle]
    /\ UNCHANGED <<q, recs, saved, holding, calls, copy, Ghosts>>

\* A page saved (url_index row added) or hidden (archived, junk): video_state.saved_videos.
SaveVideo(k) == Free /\ Churn /\ k \notin saved /\ saved' = saved \cup {k} /\ UNCHANGED <<q, recs, holding, pc, calls, copy, Ghosts>>
HideVideo(k) == Free /\ Churn /\ k \in saved /\ saved' = saved \ {k} /\ UNCHANGED <<q, recs, holding, pc, calls, copy, Ghosts>>

\* write_admission: Sleep takes and lets go of the pages (ToolContext.pages_held).
SleepStart == ~holding /\ holding' = TRUE /\ UNCHANGED <<q, recs, saved, pc, calls, copy, Ghosts>>
SleepEnd   == holding /\ holding' = FALSE /\ UNCHANGED <<q, recs, saved, pc, calls, copy, Ghosts>>

Dec(n) == IF n > 0 THEN n - 1 ELSE 0
Tick ==
    /\ \E k \in Keys : q[k].left > 0 \/ q[k].fleft > 0
    /\ q' = [k \in Keys |-> [q[k] EXCEPT !.left = Dec(@), !.fleft = Dec(@)]]
    /\ UNCHANGED <<recs, saved, holding, pc, calls, copy, Ghosts>>

Next ==
    \/ \E s \in Sessions :
          \/ ClaimBegin(s) \/ ClaimLocked(s) \/ ClaimWrite(s)
          \/ \E k \in Keys : ReleaseBegin(s, k)
          \/ ReleaseLocked(s)
          \/ \E k \in Keys, b \in Bases : RecordEpisode(s, k, b)
          \/ CompleteLocked(s)
          \/ DropCredit(s)
    \/ \E k \in Keys, w \in Wants : PutBegin(k, w)
    \/ \E k \in Keys : RemoveBegin(k) \/ RetryBegin(k) \/ SaveVideo(k) \/ HideVideo(k)
    \/ PersonLocked \/ PersonAbort
    \/ SleepStart \/ SleepEnd
    \/ Tick

Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Tick) /\ WF_vars(SleepEnd)

-----------------------------------------------------------------------------
(* Properties. Each one's plain sentence and harm is in SKILL.md.          *)

\* P1. A lease that has not lapsed never passes to another session in one step.
LiveLease(r) == r.st = "claimed" /\ r.left > 0
NoDoubleClaim == [][\A k \in Keys : LiveLease(q[k]) /\ q'[k].st = "claimed" => q'[k].ses = q[k].ses]_vars

\* P2. A row leaves the queue only by Remove, a satisfying record, failed expiry, or its page going away.
NoLostRow == ~lost

\* P3. Only the leaseholder hands a leased video back.
ReleaseOnlyByHolder == ~relTrespass

\* P4. A record by a session that does not hold the lease cannot end it without a satisfying record.
RecordByOtherCorruptsNothing == ~recTrespass

\* P5. A row closes as done only on a record newer than its request, or its leaseholder's own record.
DoneIsSupported == ~unsupported

\* P6. Releasing or recording the same video twice leaves the queue as once did.
Idempotent ==
    \A s \in Sessions, k \in Keys :
        /\ LET once == ReleaseFn(q, recs, holding, saved, s, k)
           IN ReleaseFn(once, recs, holding, saved, s, k) = once
        /\ \A b \in Bases :
              LET once == CompleteFn(q, recs, holding, saved, s, k, b)
              IN CompleteFn(once, recs, holding, saved, s, k, b) = once

Burned(k) == q[k].st # "absent" /\ q'[k].st # "absent" /\ q'[k].att > q[k].att

\* P7. A lapse costs an attempt only while Sleep is not holding the pages (P5 of the spec).
NoBurnWhileHeld == [][\A k \in Keys : Burned(k) => ~holding]_vars

\* P8. A lapse never costs an attempt when a satisfying record already exists.
NoBurnWhenSatisfied == [][\A k \in Keys : Burned(k) => ~SatisfiesNew(recs[k], q[k].want)]_vars

\* P11. A failed video returns to the queue only when the person asks (Try again, or queueing it again).
PersonAsks == pc[Person].op \in {"put", "retry"} /\ pc'[Person].op = "idle"
FailedReturnsOnlyByPerson == [][\A k \in Keys : q[k].st = "failed" /\ q'[k].st \in {"queued", "claimed"} => PersonAsks]_vars

\* P12. A live lease ends only by a release, a record's credit, the person's Remove, or its page going away.
Finishing(a) == pc[a].op # "idle" /\ pc'[a].op = "idle"
LegitEnd(k) ==
    \E a \in Actors :
        /\ Finishing(a)
        /\ \/ pc[a].op \in {"release", "complete", "remove"} /\ pc[a].key = k
           \/ q'[k].st = "absent" /\ Snap(a) # {} /\ k \notin Snap(a)
NoLeaseTakenAway ==
    [][\A k \in Keys : LiveLease(q[k]) /\ ~(q'[k].st = "claimed" /\ q'[k].ses = q[k].ses) => LegitEnd(k)]_vars

EffClaimed(k) == q[k].st = "claimed" /\ ~(Lapsed(q[k]) /\ ~holding)

\* P9. Every lease ends in every reader's view: it lapses, is released, or is recorded.
LeaseEnds == \A k \in Keys : (q[k].st = "claimed") ~> ~EffClaimed(k)

\* P10. Every failed row eventually ages out or is tried again.
FailedEnds == \A k \in Keys : (q[k].st = "failed") ~> (q[k].st # "failed" \/ FailExpired(q[k]))

Perms == Permutations(Keys) \cup Permutations(Sessions)


=============================================================================
