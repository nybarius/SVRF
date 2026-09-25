/-!
# BraidedTrain.Landing — a batched landing lands the tree its gate checked

The train folds a family of pull-request heads onto the base branch with one
deterministic merge step, gates the folded tree once, and then lands the heads one merge
commit at a time, reading after each merge the tree the base branch actually holds. This
module states the condition that makes gating once sound. Finite lists, no Mathlib.

A merge step is a partial map `step : Tree → Head → Option Tree` (`none` on a conflict);
`fold` applies it along a list of heads. A landing is the list of merged heads, each
paired with the tree the base branch was observed to hold after it; `Replays` says every
observed tree is the step of the one before, and `landed` is the last observed tree.

1. `fold_of_replays`, `landed_eq_gated`, `landed_passes`: a replayed landing of the
   family's heads, in the gated order, lands exactly the gated fold, so whatever the gate
   passed holds of the landed tree.
2. `checkLanding_iff`, `checkLanding_refuses_moved`: the per-merge tree check the train
   runs is exactly `Replays`; one observed tree that is not the step of the one before
   (an outside commit moved the base between two merges) is refused.
3. `replays_append`, `landed_append`, `segments_land_last_gated`: landings compose, so
   segments each gated on the tree the previous segment actually landed (what bisection
   lands, and what a regate after an outside move lands) end on the last segment's gated
   tree.
4. `prefix_is_fold`: an intermediate base tree is the fold of a prefix. Nothing here says
   a prefix was gated; the gate covers the family's end tree only.
5. `retried_iff`, `retried_none`, `admitted_iff`, `read_failure_never_holds`,
   `held_not_retried_on_same_head`: admission and memory. A held head is read again iff
   its head changed; a head is admitted iff it is not opted out, is read again, and its
   admission check said mergeable; a failed read (a rate limit is one) leaves the held
   memory exactly as it was, so it never becomes a hold.

Modelling boundary: that git's merge of the prepared branch is `step` is not a theorem
about git. The train does not assume it: it reads each landed tree and compares it with
the tree it gated, which is the hypothesis `Replays` here.
-/

namespace BraidedTrain

variable {Tree Head : Type}

/-- Fold the heads onto a tree with the step, `none` at the first conflict. -/
def fold (step : Tree → Head → Option Tree) : Tree → List Head → Option Tree
  | t, [] => some t
  | t, h :: hs =>
    match step t h with
    | some t' => fold step t' hs
    | none => none

/-- Every observed tree of the landing is the step of the one before. -/
def Replays (step : Tree → Head → Option Tree) : Tree → List (Head × Tree) → Prop
  | _, [] => True
  | t, (h, t') :: rest => step t h = some t' ∧ Replays step t' rest

/-- The tree the base branch holds after the landing: the last observed tree. -/
def landed : Tree → List (Head × Tree) → Tree
  | t, [] => t
  | _, (_, t') :: rest => landed t' rest

/-- The train's per-merge tree check. -/
def checkLanding [DecidableEq Tree] (step : Tree → Head → Option Tree) :
    Tree → List (Head × Tree) → Bool
  | _, [] => true
  | t, (h, t') :: rest => decide (step t h = some t') && checkLanding step t' rest

variable (step : Tree → Head → Option Tree)

theorem fold_of_replays : ∀ {base : Tree} {L : List (Head × Tree)},
    Replays step base L → fold step base (L.map Prod.fst) = some (landed base L)
  | _, [], _ => rfl
  | _, (h, t') :: rest, ⟨hs, hr⟩ => by
    simp only [List.map, fold, hs, landed]
    exact fold_of_replays hr

theorem landed_eq_gated {base g : Tree} {hs : List Head} {L : List (Head × Tree)}
    (hg : fold step base hs = some g) (hr : Replays step base L)
    (hl : L.map Prod.fst = hs) : landed base L = g := by
  have h := fold_of_replays step hr
  rw [hl, hg] at h
  exact (Option.some.inj h).symm

theorem landed_passes (gate : Tree → Prop) {base g : Tree} {hs : List Head}
    {L : List (Head × Tree)} (hg : fold step base hs = some g) (hpass : gate g)
    (hr : Replays step base L) (hl : L.map Prod.fst = hs) : gate (landed base L) := by
  rw [landed_eq_gated step hg hr hl]
  exact hpass

theorem checkLanding_iff [DecidableEq Tree] :
    ∀ (base : Tree) (L : List (Head × Tree)), checkLanding step base L = true ↔ Replays step base L
  | _, [] => Iff.intro (fun _ => trivial) (fun _ => rfl)
  | t, (h, t') :: rest => by
    simp only [checkLanding, Bool.and_eq_true, decide_eq_true_eq, Replays]
    exact and_congr Iff.rfl (checkLanding_iff t' rest)

theorem checkLanding_refuses_moved [DecidableEq Tree] {t t' : Tree} {h : Head}
    (hne : step t h ≠ some t') (rest : List (Head × Tree)) :
    checkLanding step t ((h, t') :: rest) = false := by
  simp only [checkLanding, decide_eq_false hne, Bool.false_and]

theorem replays_append : ∀ {base : Tree} {L₁ L₂ : List (Head × Tree)},
    Replays step base (L₁ ++ L₂) ↔ Replays step base L₁ ∧ Replays step (landed base L₁) L₂
  | _, [], _ => Iff.intro (fun h => ⟨trivial, h⟩) (fun h => h.2)
  | _, (h, t') :: rest, _ => by
    simp only [List.cons_append, Replays, landed]
    rw [replays_append]
    exact and_assoc.symm

theorem landed_append : ∀ (base : Tree) (L₁ L₂ : List (Head × Tree)),
    landed base (L₁ ++ L₂) = landed (landed base L₁) L₂
  | _, [], _ => rfl
  | _, (_, t') :: rest, L₂ => landed_append t' rest L₂

theorem segments_land_last_gated {base g₁ g₂ : Tree} {L₁ L₂ : List (Head × Tree)}
    (h₁ : fold step base (L₁.map Prod.fst) = some g₁) (r₁ : Replays step base L₁)
    (h₂ : fold step g₁ (L₂.map Prod.fst) = some g₂) (r₂ : Replays step g₁ L₂) :
    landed base (L₁ ++ L₂) = g₂ := by
  have e₁ : landed base L₁ = g₁ := landed_eq_gated step h₁ r₁ rfl
  rw [landed_append, e₁]
  exact landed_eq_gated step h₂ r₂ rfl

theorem prefix_is_fold {base : Tree} {L₁ L₂ : List (Head × Tree)}
    (hr : Replays step base (L₁ ++ L₂)) :
    fold step base (L₁.map Prod.fst) = some (landed base L₁) :=
  fold_of_replays step ((replays_append step).1 hr).1

/-! ## Admission and retry

`Sha` is a head identity; the memory of a pull request is the head it was held on, if any. -/

/-- What one round's admission check of a head returned. -/
inductive Verdict
  | mergeable
  | held
  | unread
  deriving DecidableEq

/-- A head is read again iff it was never held or its head changed since the hold. -/
def retried {Sha : Type} [DecidableEq Sha] : Option Sha → Sha → Bool
  | none, _ => true
  | some held, current => !decide (held = current)

/-- Admitted: not opted out, read again, and the check said mergeable. -/
def admitted {Sha : Type} [DecidableEq Sha] (optOut : Bool) (memory : Option Sha) (current : Sha)
    (r : Verdict) : Bool :=
  !optOut && retried memory current && decide (r = Verdict.mergeable)

/-- The memory after a round: a hold remembers the head it was held on, a failed read
keeps the memory, a mergeable verdict clears it. -/
def remember {Sha : Type} (memory : Option Sha) (current : Sha) : Verdict → Option Sha
  | Verdict.held => some current
  | Verdict.unread => memory
  | Verdict.mergeable => none

theorem retried_iff {Sha : Type} [DecidableEq Sha] (held current : Sha) :
    retried (some held) current = true ↔ held ≠ current := by
  simp [retried]

theorem retried_none {Sha : Type} [DecidableEq Sha] (current : Sha) :
    retried none current = true := rfl

theorem admitted_iff {Sha : Type} [DecidableEq Sha] (optOut : Bool) (memory : Option Sha)
    (current : Sha) (r : Verdict) :
    admitted optOut memory current r = true ↔
      optOut = false ∧ retried memory current = true ∧ r = Verdict.mergeable := by
  simp [admitted, Bool.and_eq_true, and_assoc]

theorem read_failure_never_holds {Sha : Type} (memory : Option Sha) (current : Sha) :
    remember memory current Verdict.unread = memory := rfl

theorem held_not_retried_on_same_head {Sha : Type} [DecidableEq Sha] (memory : Option Sha)
    (current : Sha) : retried (remember memory current Verdict.held) current = false := by
  simp [remember, retried]

end BraidedTrain
