import BraidedTrain.Braid

/-!
# BraidedTrain.Stacking — speculative stacking across a list of families

`Train.round` cuts the queue into families, folds each family onto the fold of every
family before it, gates all of them (in parallel, `jobs`), then lands them in order. Family
`k` is gated on the fold of families `1..k`, the tree the base branch will hold once
families `1..k` have landed. Finite lists, no Mathlib.

1. `stack_lands_gated`: if families `1..k` are each gated green on their stacked fold and
   the landing of families `1..k` replays (the per-merge tree check), then at every family
   boundary `j ≤ k` the base branch holds a tree some gate passed. Its hypotheses name
   families `1..k` only: nothing stacked above `k` can void what landed at or below it.
2. `fold_append`, `stack_fold_through`: the gated tree of every family above `k` is a fold
   through family `k`'s heads. `stacked_verdict_does_not_carry`: when family `k` is red and
   does not land, the verdict a family above it got says nothing about the tree it would
   land on instead (a concrete step and gate where it is green on its stacked tree and red
   on the tree without family `k`). So those verdicts must be thrown away and regated.
3. `stackStatus` is `Train.round`'s bookkeeping: families land in order until the first one
   that is not green and landed whole; that one is bisected (or retried), and every family
   after it is `SPECULATION_VOID`. `stackStatus_landed_iff`, `stackStatus_void_iff`: a red
   family voids exactly the families stacked above it and none below it.

Modelling boundary: a family that lands only partly (an outside move, a moved head) is
treated as not landed whole; the code requeues the rest of it with every later family.
-/

namespace BraidedTrain

variable {Tree Head : Type}

/-- The heads of the first `j` families, in order: what family `j` is gated on. -/
def stackHeads (fams : List (List Head)) (j : Nat) : List Head :=
  (fams.take j).flatten

/-- Families `1..k` are each gated green on the fold of the families up to and including them. -/
def StackGated (step : Tree → Head → Option Tree) (gate : Tree → Prop) (base : Tree)
    (fams : List (List Head)) (k : Nat) : Prop :=
  ∀ j, 1 ≤ j → j ≤ k → ∃ g, fold step base (stackHeads fams j) = some g ∧ gate g

variable (step : Tree → Head → Option Tree)

theorem fold_append : ∀ (t : Tree) (a b : List Head),
    fold step t (a ++ b) = (fold step t a).bind (fun t' => fold step t' b)
  | _, [], _ => rfl
  | t, h :: hs, b => by
    simp only [List.cons_append, fold]
    cases step t h with
    | none => rfl
    | some t' => exact fold_append t' hs b

/-- Stacked families gated green and landed with a replayed landing: the base branch holds
a gated tree at every family boundary. -/
theorem stack_lands_gated (gate : Tree → Prop) {base : Tree} {fams : List (List Head)}
    {k : Nat} (Ls : List (List (Head × Tree)))
    (hm : Ls.map (List.map Prod.fst) = fams) (hg : StackGated step gate base fams k)
    (hr : Replays step base (Ls.take k).flatten) :
    ∀ j, 1 ≤ j → j ≤ k → gate (landed base (Ls.take j).flatten) := by
  intro j hj hjk
  obtain ⟨g, hfold, hgate⟩ := hg j hj hjk
  have split : (Ls.take k).flatten = (Ls.take j).flatten ++ ((Ls.take k).drop j).flatten := by
    rw [← List.flatten_append]
    congr 1
    conv => lhs; rw [← List.take_append_drop j (Ls.take k)]
    rw [List.take_take, Nat.min_eq_left hjk]
  rw [split] at hr
  have hp := prefix_is_fold step hr
  have heads : ((Ls.take j).flatten).map Prod.fst = stackHeads fams j := by
    rw [stackHeads, ← hm, List.map_flatten, List.map_take]
  rw [heads, hfold] at hp
  rw [← Option.some.inj hp]
  exact hgate

theorem take_add_split {α : Type} : ∀ (l : List α) (a b : Nat),
    l.take (a + b) = l.take a ++ (l.drop a).take b
  | [], _, _ => by simp
  | _ :: _, 0, _ => by simp
  | x :: xs, a + 1, b => by
    rw [Nat.add_right_comm]
    simp only [List.take_succ_cons, List.drop_succ_cons, List.cons_append]
    rw [take_add_split xs a b]

/-- The gated tree of a family above family `k + 1` is a fold through family `k + 1`'s heads. -/
theorem stack_fold_through (base : Tree) (fams : List (List Head)) (k m : Nat) :
    fold step base (stackHeads fams (k + 1 + m)) =
      (fold step base (stackHeads fams (k + 1))).bind
        (fun g => fold step g ((fams.drop (k + 1)).take m).flatten) := by
  rw [← fold_append, stackHeads, stackHeads, ← List.flatten_append, take_add_split]

/-- Adding numbers: a toy step where a tree is a number and a head adds to it. -/
def addStep (t h : Nat) : Option Nat := some (t + h)

/-- Green on the tree its family was stacked on, red on the tree it would land on once the
red family below it is left out: a stacked verdict does not carry past a red family. -/
theorem stacked_verdict_does_not_carry :
    let gate : Nat → Bool := fun t => t != 3 && t != 4
    let fams : List (List Nat) := [[1], [2], [3]]
    fold addStep 0 (stackHeads fams 1) = some 1 ∧ gate 1 = true ∧
    fold addStep 0 (stackHeads fams 2) = some 3 ∧ gate 3 = false ∧
    fold addStep 0 (stackHeads fams 3) = some 6 ∧ gate 6 = true ∧
    fold addStep 1 [3] = some 4 ∧ gate 4 = false := by
  decide

/-! ## The round's bookkeeping -/

/-- What `Train.round` records for a family. -/
inductive FamilyStatus
  | landed
  | bisected
  | void
  deriving DecidableEq

/-- Statuses from per-family outcomes (`true`: gated green and landed whole): landed up to
the first other outcome, that one bisected or retried, every one after it void. -/
def stackStatus : List Bool → List FamilyStatus
  | [] => []
  | true :: gs => .landed :: stackStatus gs
  | false :: gs => .bisected :: gs.map (fun _ => .void)

/-- The index of the first family that did not land whole (the length if all did). -/
def firstRed : List Bool → Nat
  | [] => 0
  | true :: gs => firstRed gs + 1
  | false :: _ => 0

theorem stackStatus_length : ∀ gs : List Bool, (stackStatus gs).length = gs.length
  | [] => rfl
  | true :: gs => by simp [stackStatus, stackStatus_length gs]
  | false :: gs => by simp [stackStatus]

theorem firstRed_le : ∀ gs : List Bool, firstRed gs ≤ gs.length
  | [] => Nat.le_refl 0
  | true :: gs => by simp [firstRed, firstRed_le gs]
  | false :: _ => Nat.zero_le _

/-- A family lands exactly when every family up to and including it was green and landed. -/
theorem stackStatus_landed_iff : ∀ (gs : List Bool) (j : Nat),
    (stackStatus gs)[j]? = some .landed ↔ j < firstRed gs
  | [], j => by simp [stackStatus, firstRed]
  | true :: gs, 0 => by simp [stackStatus, firstRed]
  | true :: gs, j + 1 => by
    simp only [stackStatus, List.getElem?_cons_succ, firstRed]
    rw [stackStatus_landed_iff gs j]
    exact Nat.succ_lt_succ_iff.symm
  | false :: gs, 0 => by simp [stackStatus, firstRed]
  | false :: gs, j + 1 => by
    simp only [stackStatus, List.getElem?_cons_succ, firstRed, List.getElem?_map]
    constructor
    · intro h
      cases hj : gs[j]? with
      | none => rw [hj] at h; cases h
      | some _ => rw [hj] at h; cases h
    · intro h; exact absurd h (Nat.not_lt_zero _)

/-- A family is voided exactly when it is stacked above the first red family. -/
theorem stackStatus_void_iff : ∀ (gs : List Bool) (j : Nat),
    (stackStatus gs)[j]? = some .void ↔ firstRed gs < j ∧ j < gs.length
  | [], j => by simp [stackStatus]
  | true :: gs, 0 => by simp [stackStatus, firstRed]
  | true :: gs, j + 1 => by
    simp only [stackStatus, List.getElem?_cons_succ, firstRed, List.length_cons]
    rw [stackStatus_void_iff gs j]
    exact and_congr Nat.succ_lt_succ_iff.symm Nat.succ_lt_succ_iff.symm
  | false :: gs, 0 => by simp [stackStatus, firstRed]
  | false :: gs, j + 1 => by
    simp only [stackStatus, List.getElem?_cons_succ, firstRed, List.getElem?_map,
      List.length_cons]
    constructor
    · intro h
      cases hj : gs[j]? with
      | none => rw [hj] at h; cases h
      | some _ =>
        exact ⟨Nat.succ_pos j, Nat.succ_lt_succ (List.getElem?_eq_some_iff.mp hj).1⟩
    · intro h
      have hlt : j < gs.length := Nat.lt_of_succ_lt_succ h.2
      rw [List.getElem?_eq_getElem hlt]
      rfl

/-- The red family itself is the one handed to bisection. -/
theorem stackStatus_bisected_iff : ∀ (gs : List Bool) (j : Nat),
    (stackStatus gs)[j]? = some .bisected ↔ j = firstRed gs ∧ j < gs.length
  | [], j => ⟨fun h => (by cases h), fun h => absurd h.2 (Nat.not_lt_zero _)⟩
  | true :: gs, 0 => ⟨fun h => (by cases h), fun h => absurd h.1.symm (Nat.succ_ne_zero _)⟩
  | true :: gs, j + 1 => by
    simp only [stackStatus, List.getElem?_cons_succ, firstRed, List.length_cons]
    rw [stackStatus_bisected_iff gs j]
    exact and_congr ⟨fun h => h ▸ rfl, Nat.succ.inj⟩ Nat.succ_lt_succ_iff.symm
  | false :: gs, 0 => ⟨fun _ => ⟨rfl, Nat.succ_pos _⟩, fun _ => rfl⟩
  | false :: gs, j + 1 => by
    simp only [stackStatus, List.getElem?_cons_succ, firstRed, List.getElem?_map]
    constructor
    · intro h
      cases hj : gs[j]? with
      | none => rw [hj] at h; cases h
      | some _ => rw [hj] at h; cases h
    · intro h; exact absurd h.1 (Nat.succ_ne_zero j)

end BraidedTrain
