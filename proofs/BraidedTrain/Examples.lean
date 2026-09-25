import BraidedTrain.Landing
import BraidedTrain.Braid
import BraidedTrain.Interleaving
import BraidedTrain.Reland

/-!
# BraidedTrain.Examples — the statements as the train reads them, and concrete instances

Each `example` restates a theorem in the shape the code relies on; the concrete instances
close by `decide` or `rfl`. If a theorem's statement drifts, this file stops compiling.
-/

namespace BraidedTrain.Examples

open BraidedTrain

/-! ## Landing -/

example {Tree Head : Type} (step : Tree → Head → Option Tree) (base g : Tree)
    (hs : List Head) (L : List (Head × Tree)) (gate : Tree → Prop)
    (hg : fold step base hs = some g) (hpass : gate g) (hr : Replays step base L)
    (hl : L.map Prod.fst = hs) : landed base L = g ∧ gate (landed base L) :=
  ⟨landed_eq_gated step hg hr hl, landed_passes step gate hg hpass hr hl⟩

example {Tree Head : Type} [DecidableEq Tree] (step : Tree → Head → Option Tree)
    (base : Tree) (L : List (Head × Tree)) :
    checkLanding step base L = true ↔ Replays step base L :=
  checkLanding_iff step base L

example {Tree Head : Type} [DecidableEq Tree] (step : Tree → Head → Option Tree)
    (t t' : Tree) (h : Head) (rest : List (Head × Tree)) (hne : step t h ≠ some t') :
    checkLanding step t ((h, t') :: rest) = false :=
  checkLanding_refuses_moved step hne rest

example {Tree Head : Type} (step : Tree → Head → Option Tree) (base g₁ g₂ : Tree)
    (L₁ L₂ : List (Head × Tree))
    (h₁ : fold step base (L₁.map Prod.fst) = some g₁) (r₁ : Replays step base L₁)
    (h₂ : fold step g₁ (L₂.map Prod.fst) = some g₂) (r₂ : Replays step g₁ L₂) :
    landed base (L₁ ++ L₂) = g₂ :=
  segments_land_last_gated step h₁ r₁ h₂ r₂

example {Tree Head : Type} (step : Tree → Head → Option Tree) (base : Tree)
    (L₁ L₂ : List (Head × Tree)) (hr : Replays step base (L₁ ++ L₂)) :
    fold step base (L₁.map Prod.fst) = some (landed base L₁) :=
  prefix_is_fold step hr

/-- A toy merge step: a tree is the list of pull requests it contains, and merging one
that is already in conflicts. -/
def carry (t : List Nat) (h : Nat) : Option (List Nat) :=
  if h ∈ t then none else some (t ++ [h])

/-- A three-PR family folds to the tree containing all three. -/
example : fold carry [0] [1, 2, 3] = some [0, 1, 2, 3] := by decide

/-- Landing it one PR at a time, each observed tree the step of the last, checks. -/
example : checkLanding carry [0] [(1, [0, 1]), (2, [0, 1, 2]), (3, [0, 1, 2, 3])] = true := by
  decide

/-- An outside commit (9) lands between PRs 1 and 2: the check refuses, and the landed
tree is not the gated one. -/
example : checkLanding carry [0] [(1, [0, 1]), (2, [0, 1, 9, 2]), (3, [0, 1, 9, 2, 3])] = false := by
  decide

example : landed [0] [(1, [0, 1]), (2, [0, 1, 9, 2]), (3, [0, 1, 9, 2, 3])] ≠ [0, 1, 2, 3] := by
  decide

/-- A conflicting family does not fold. -/
example : fold carry [0] [1, 1] = none := by decide

/-! ## Admission and retry -/

example {Sha : Type} [DecidableEq Sha] (held current : Sha) :
    retried (some held) current = true ↔ held ≠ current :=
  retried_iff held current

example {Sha : Type} [DecidableEq Sha] (optOut : Bool) (memory : Option Sha) (current : Sha)
    (r : Verdict) :
    admitted optOut memory current r = true ↔
      optOut = false ∧ retried memory current = true ∧ r = Verdict.mergeable :=
  admitted_iff optOut memory current r

example {Sha : Type} (memory : Option Sha) (current : Sha) :
    remember memory current Verdict.unread = memory :=
  read_failure_never_holds memory current

/-- Held on head 7: not retried on 7, retried on 8; a failed read keeps the memory. -/
example : retried (remember none 7 Verdict.held) 7 = false := by decide
example : retried (remember none 7 Verdict.held) 8 = true := by decide
example : remember (some 7) 8 Verdict.unread = some 7 := by decide
example : admitted false (some 7) 8 Verdict.mergeable = true := by decide
example : admitted true none 8 Verdict.mergeable = false := by decide
example : admitted false none 8 Verdict.unread = false := by decide

/-! ## Braid -/

example {Tree Head : Type} (gate : Tree → Prop) (base : Tree) (L : List (Head × Tree)) :
    AllGated gate base L ↔ ∀ L₁ L₂, L = L₁ ++ L₂ → L₁ ≠ [] → gate (landed base L₁) :=
  all_gated_iff_each_prefix gate base L

example {Tree Head : Type} (gate : Tree → Prop) (base t₁ t₂ : Tree) (h₁ h₂ : Head)
    (hend : gate t₂) (hnot : ¬ gate t₁) :
    ¬ AllGated gate base [(h₁, t₁), (h₂, t₂)] :=
  end_gate_leaves_prefix_ungated gate base h₁ h₂ hend hnot

example {Sha Watched V : Type} [DecidableEq Sha] [DecidableEq Watched]
    (verdict : RetryKey Sha Watched → V) (held now : RetryKey Sha Watched)
    (h : retry held now = false) : verdict held = verdict now :=
  held_verdict_stands verdict h

example {Path Val : Type} [DecidableEq Path] (t : Path → Val) (s₁ s₂ : List (List (Path × Val)))
    (hd : ∀ a ∈ s₁, ∀ b ∈ s₂, DisjointWrites a b) :
    fold unionStep t (s₁ ++ s₂) = fold unionStep t (s₂ ++ s₁) :=
  strands_comm t hd

example : apply (apply (fun _ : Nat => 0) [(1, 7)]) [(2, 9)] 1 = 7 := rfl
example : apply (apply (fun _ : Nat => 0) [(2, 9)]) [(1, 7)] 2 = 9 := rfl
example : mains (0 : Nat) [((1 : Nat), (5 : Nat)), (2, 6)] = [5, 6] := rfl

/-! ## Interleaving -/

example {α : Type} (a b : α) : Interleaving [a] [b] [b, a] :=
  Interleaving.right (Interleaving.left Interleaving.nil)

example {Path Val : Type} [DecidableEq Path] (t : Path → Val) {s₁ s₂ s : List (List (Path × Val))}
    (hi : Interleaving s₁ s₂ s) (hd : ∀ a ∈ s₁, ∀ b ∈ s₂, DisjointWrites a b) :
    fold unionStep t s = fold unionStep t (s₁ ++ s₂) :=
  interleaved_landing t hi hd

/-! ## Re-land -/

example {Path Val : Type} [DecidableEq Path] (base : Path → Val) (h : List (List (Path × Val)))
    (kind : Path → Kind) : tree base (reland base h kind) = tree base h :=
  reland_tree base h kind

example {Path Val : Type} [DecidableEq Path] (base : Path → Val) (h : List (List (Path × Val)))
    (kind : Path → Kind) :
    reland base h kind = [testsOf base h kind, codeOf base h kind, docsOf base h kind] :=
  rfl

end BraidedTrain.Examples
